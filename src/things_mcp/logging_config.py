#!/usr/bin/env python3
"""
Enhanced logging configuration for Things MCP server.
Provides structured logging with multiple outputs and log levels.
"""
import logging
import logging.handlers
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

# Create logs directory if it doesn't exist
LOGS_DIR = Path.home() / '.things-mcp' / 'logs'
LOGS_DIR.mkdir(parents=True, exist_ok=True)

class StructuredFormatter(logging.Formatter):
    """Custom formatter that outputs structured JSON logs for better analysis."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # Add any extra fields
        if hasattr(record, 'operation'):
            log_data['operation'] = record.operation
        if hasattr(record, 'duration'):
            log_data['duration'] = record.duration
        if hasattr(record, 'error_type'):
            log_data['error_type'] = record.error_type
        if hasattr(record, 'retry_count'):
            log_data['retry_count'] = record.retry_count
            
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
            
        return json.dumps(log_data)

class OperationLogFilter(logging.Filter):
    """Filter to add operation context to log records."""
    
    def __init__(self):
        super().__init__()
        self.operation_context = {}
    
    def set_operation_context(self, operation: str, **kwargs):
        """Set the current operation context."""
        self.operation_context = {
            'operation': operation,
            **kwargs
        }
    
    def clear_operation_context(self):
        """Clear the operation context."""
        self.operation_context = {}
    
    def filter(self, record: logging.LogRecord) -> bool:
        # Add operation context to the record
        for key, value in self.operation_context.items():
            setattr(record, key, value)
        return True

# Global operation filter instance
operation_filter = OperationLogFilter()

def setup_logging(
    console_level: str = "INFO",
    file_level: str = "DEBUG",
    structured_logs: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5
) -> None:
    """
    Configure comprehensive logging for the Things MCP server.
    
    Args:
        console_level: Log level for console output
        file_level: Log level for file output
        structured_logs: Whether to use structured JSON logging
        max_bytes: Maximum size of log files before rotation
        backup_count: Number of backup files to keep
    """
    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything, filter at handler level
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Console handler with simple formatting
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, console_level.upper()))
    console_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    console_handler.addFilter(operation_filter)
    root_logger.addHandler(console_handler)
    
    # File handlers with rotation
    if structured_logs:
        # Structured JSON logs for analysis
        json_file_handler = logging.handlers.RotatingFileHandler(
            LOGS_DIR / 'things_mcp_structured.json',
            maxBytes=max_bytes,
            backupCount=backup_count
        )
        json_file_handler.setLevel(getattr(logging, file_level.upper()))
        json_file_handler.setFormatter(StructuredFormatter())
        json_file_handler.addFilter(operation_filter)
        root_logger.addHandler(json_file_handler)
    
    # Human-readable file logs
    text_file_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / 'things_mcp.log',
        maxBytes=max_bytes,
        backupCount=backup_count
    )
    text_file_handler.setLevel(getattr(logging, file_level.upper()))
    text_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    text_file_handler.setFormatter(text_format)
    text_file_handler.addFilter(operation_filter)
    root_logger.addHandler(text_file_handler)
    
    # Error-only file handler
    error_file_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / 'things_mcp_errors.log',
        maxBytes=max_bytes,
        backupCount=backup_count
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(text_format)
    error_file_handler.addFilter(operation_filter)
    root_logger.addHandler(error_file_handler)
    
    # Log the logging configuration
    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured - Console: {console_level}, File: {file_level}, Structured: {structured_logs}")
    logger.info(f"Log files location: {LOGS_DIR}")

def log_operation_start(operation: str, **kwargs) -> None:
    """Log the start of an operation and set context."""
    operation_filter.set_operation_context(operation, **kwargs)
    logger = logging.getLogger(__name__)
    logger.info(f"Starting operation: {operation}", extra={'operation': operation, **kwargs})

def log_operation_end(operation: str, success: bool, duration: float = None, **kwargs) -> None:
    """Log the end of an operation."""
    logger = logging.getLogger(__name__)
    extra = {
        'operation': operation,
        'success': success,
        **kwargs
    }
    if duration is not None:
        extra['duration'] = duration
        
    if success:
        logger.info(f"Operation completed: {operation}", extra=extra)
    else:
        logger.error(f"Operation failed: {operation}", extra=extra)
    
    operation_filter.clear_operation_context()

def log_retry_attempt(operation: str, attempt: int, max_attempts: int, error: str) -> None:
    """Log a retry attempt."""
    logger = logging.getLogger(__name__)
    logger.warning(
        f"Retry attempt {attempt}/{max_attempts} for {operation}: {error}",
        extra={
            'operation': operation,
            'retry_count': attempt,
            'max_attempts': max_attempts,
            'error': error
        }
    )

def log_circuit_breaker_state(state: str, failure_count: int = None) -> None:
    """Log circuit breaker state changes."""
    logger = logging.getLogger(__name__)
    extra = {'circuit_breaker_state': state}
    if failure_count is not None:
        extra['failure_count'] = failure_count
        
    logger.warning(f"Circuit breaker state changed to: {state}", extra=extra)

def log_dead_letter_queue(operation: str, params: Dict[str, Any], error: str) -> None:
    """Log when an operation is added to the dead letter queue."""
    logger = logging.getLogger(__name__)
    logger.error(
        f"Added to dead letter queue: {operation}",
        extra={
            'operation': operation,
            'params': params,
            'error': error,
            'dlq': True
        }
    )

def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)

# Initialize logging when module is imported
setup_logging()