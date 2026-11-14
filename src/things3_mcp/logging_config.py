#!/usr/bin/env python3
"""Enhanced logging configuration for Things MCP server.

Provides structured logging with multiple outputs and log levels.
"""

import json
import logging
import logging.handlers
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

LOGS_DIR = Path.home() / ".things-mcp" / "logs"


class StructuredFormatter(logging.Formatter):
    """Custom formatter that outputs structured JSON logs for better analysis."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON string.

        Args:
            record: The log record to format.

        Returns:
            str: The formatted log record as a JSON string.
        """
        log_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add any extra fields
        if hasattr(record, "operation"):
            log_data["operation"] = record.operation
        if hasattr(record, "duration"):
            log_data["duration"] = record.duration
        if hasattr(record, "error_type"):
            log_data["error_type"] = record.error_type
        if hasattr(record, "retry_count"):
            log_data["retry_count"] = record.retry_count

        # Add exception info if present
        if record.exc_info:
            log_data["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"

        return json.dumps(log_data)


class OperationLogFilter(logging.Filter):
    """Filter to add operation context to log records."""

    def __init__(self):
        """Initialize the operation log filter."""
        super().__init__()
        self._context = ContextVar("things_operation_context", default=None)

    def set_operation_context(self, operation: str, **kwargs):
        """Set the current operation context."""
        self._context.set({"operation": operation})

    def clear_operation_context(self):
        """Clear the operation context."""
        self._context.set(None)

    def filter(self, record: logging.LogRecord) -> bool:
        """Add operation context to log records.

        Args:
            record: The log record to filter.

        Returns:
            bool: Always returns True to allow the record.
        """
        # MCP/http client debug messages can include complete requests, results
        # or validation errors. Retain diagnostic locations, never their text.
        if not record.name.startswith(("things3_mcp.", "things3_mcp_bridge.", "clawbridge.")):
            record.msg = "External component diagnostic (message omitted)"
            record.args = ()
        if record.exc_info:
            record.error_type = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None

        for key, value in (self._context.get() or {}).items():
            setattr(record, key, value)
        return True


# Global operation filter instance
operation_filter = OperationLogFilter()


def setup_logging(
    console_level: str = "INFO",
    file_level: str = "DEBUG",
    structured_logs: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> None:
    """Configure comprehensive logging for the Things MCP server.

    Args:
    ----
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
    console_format = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    console_handler.setFormatter(console_format)
    console_handler.addFilter(operation_filter)
    root_logger.addHandler(console_handler)

    # File handlers with rotation. The server must still start where the home
    # directory cannot be written, so log files are optional and the console is not.
    logger = logging.getLogger(__name__)
    file_handlers: list[logging.Handler] = []
    text_format = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        if structured_logs:
            # Structured JSON logs for analysis
            json_file_handler = logging.handlers.RotatingFileHandler(LOGS_DIR / "things3_mcp_structured.json", maxBytes=max_bytes, backupCount=backup_count)
            json_file_handler.setLevel(getattr(logging, file_level.upper()))
            json_file_handler.setFormatter(StructuredFormatter())
            file_handlers.append(json_file_handler)

        # Human-readable file logs
        text_file_handler = logging.handlers.RotatingFileHandler(LOGS_DIR / "things3_mcp.log", maxBytes=max_bytes, backupCount=backup_count)
        text_file_handler.setLevel(getattr(logging, file_level.upper()))
        text_file_handler.setFormatter(text_format)
        file_handlers.append(text_file_handler)

        # Error-only file handler
        error_file_handler = logging.handlers.RotatingFileHandler(LOGS_DIR / "things3_mcp_errors.log", maxBytes=max_bytes, backupCount=backup_count)
        error_file_handler.setLevel(logging.ERROR)
        error_file_handler.setFormatter(text_format)
        file_handlers.append(error_file_handler)
    except OSError as error:
        for handler in file_handlers:
            handler.close()
        logger.warning("Log files are unavailable (%s); logging to the console only", type(error).__name__)
        return
    for handler in file_handlers:
        handler.addFilter(operation_filter)
        root_logger.addHandler(handler)

    # Log the logging configuration
    logger.info(f"Logging configured - Console: {console_level}, File: {file_level}, Structured: {structured_logs}")
    logger.info(f"Log files location: {LOGS_DIR}")


def log_operation_start(operation: str, **kwargs) -> None:
    """Log the start of an operation and set context."""
    operation_filter.set_operation_context(operation, **kwargs)
    logger = logging.getLogger(__name__)
    logger.info(f"Starting operation: {operation}", extra={"operation": operation})


def log_operation_end(operation: str, success: bool, duration: float = None, **kwargs) -> None:
    """Log the end of an operation."""
    logger = logging.getLogger(__name__)
    extra = {"operation": operation, "success": success}
    if duration is not None:
        extra["duration"] = duration

    if success:
        logger.info(f"Operation completed: {operation}", extra=extra)
    else:
        logger.error(f"Operation failed: {operation}", extra=extra)

    operation_filter.clear_operation_context()


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)


# Initialize logging when module is imported
setup_logging()
