#!/usr/bin/env python3
"""
Caching module for Things MCP server.
Provides intelligent caching for frequently accessed data to improve performance.
"""
import time
import json
import hashlib
import logging
from typing import Any, Dict, Optional, Callable, Tuple
from functools import wraps
from threading import Lock

logger = logging.getLogger(__name__)

class ThingsCache:
    """
    Thread-safe cache for Things data with TTL support.
    """
    
    def __init__(self, default_ttl: int = 300):  # 5 minutes default
        """
        Initialize the cache.
        
        Args:
            default_ttl: Default time-to-live for cache entries in seconds
        """
        self.cache: Dict[str, Tuple[Any, float]] = {}
        self.default_ttl = default_ttl
        self.lock = Lock()
        self.hit_count = 0
        self.miss_count = 0
        
    def _make_key(self, operation: str, **kwargs) -> str:
        """Generate a cache key from operation and parameters."""
        # Sort kwargs to ensure consistent keys
        sorted_params = json.dumps(kwargs, sort_keys=True)
        key_string = f"{operation}:{sorted_params}"
        # Use hash for shorter keys
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def get(self, operation: str, **kwargs) -> Optional[Any]:
        """
        Get a value from cache if it exists and hasn't expired.
        
        Args:
            operation: The operation name
            **kwargs: Parameters for the operation
            
        Returns:
            Cached value if available and valid, None otherwise
        """
        key = self._make_key(operation, **kwargs)
        
        with self.lock:
            if key in self.cache:
                value, expiry_time = self.cache[key]
                if time.time() < expiry_time:
                    self.hit_count += 1
                    logger.debug(f"Cache hit for {operation}: {key}")
                    return value
                else:
                    # Expired, remove it
                    del self.cache[key]
                    logger.debug(f"Cache expired for {operation}: {key}")
            
            self.miss_count += 1
            return None
    
    def set(self, operation: str, value: Any, ttl: Optional[int] = None, **kwargs) -> None:
        """
        Set a value in the cache.
        
        Args:
            operation: The operation name
            value: The value to cache
            ttl: Time-to-live in seconds (uses default if not specified)
            **kwargs: Parameters for the operation
        """
        key = self._make_key(operation, **kwargs)
        ttl = ttl if ttl is not None else self.default_ttl
        expiry_time = time.time() + ttl
        
        with self.lock:
            self.cache[key] = (value, expiry_time)
            logger.debug(f"Cache set for {operation}: {key}, TTL: {ttl}s")
    
    def invalidate(self, operation: Optional[str] = None, **kwargs) -> None:
        """
        Invalidate cache entries.
        
        Args:
            operation: If specified, only invalidate entries for this operation
            **kwargs: If specified with operation, invalidate specific entry
        """
        with self.lock:
            if operation and kwargs:
                # Invalidate specific entry
                key = self._make_key(operation, **kwargs)
                if key in self.cache:
                    del self.cache[key]
                    logger.debug(f"Invalidated specific cache entry: {key}")
            elif operation:
                # Invalidate all entries for an operation
                keys_to_remove = [k for k in self.cache.keys() 
                                 if k.startswith(hashlib.md5(f"{operation}:".encode()).hexdigest()[:8])]
                for key in keys_to_remove:
                    del self.cache[key]
                logger.debug(f"Invalidated {len(keys_to_remove)} cache entries for operation: {operation}")
            else:
                # Clear entire cache
                self.cache.clear()
                logger.info("Cleared entire cache")
    
    def cleanup_expired(self) -> int:
        """Remove expired entries from cache. Returns number of entries removed."""
        current_time = time.time()
        removed_count = 0
        
        with self.lock:
            keys_to_remove = []
            for key, (_, expiry_time) in self.cache.items():
                if current_time >= expiry_time:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self.cache[key]
                removed_count += 1
        
        if removed_count > 0:
            logger.debug(f"Cleaned up {removed_count} expired cache entries")
        
        return removed_count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self.lock:
            total_requests = self.hit_count + self.miss_count
            hit_rate = (self.hit_count / total_requests * 100) if total_requests > 0 else 0
            
            return {
                "entries": len(self.cache),
                "hits": self.hit_count,
                "misses": self.miss_count,
                "hit_rate": f"{hit_rate:.1f}%",
                "total_requests": total_requests
            }

# Global cache instance
_cache = ThingsCache()

def cached(ttl: Optional[int] = None, invalidate_on: Optional[list] = None):
    """
    Decorator for caching function results.
    
    Args:
        ttl: Time-to-live for cached results in seconds
        invalidate_on: List of operation names that should invalidate this cache
        
    Example:
        @cached(ttl=60)
        def get_projects():
            return things.projects()
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create operation name from function
            operation = func.__name__
            
            # Check cache first
            cached_value = _cache.get(operation, **kwargs)
            if cached_value is not None:
                return cached_value
            
            # Call the actual function
            result = func(*args, **kwargs)
            
            # Cache the result
            _cache.set(operation, result, ttl=ttl, **kwargs)
            
            return result
        
        # Store invalidation info
        if invalidate_on:
            wrapper._invalidate_on = invalidate_on
        
        return wrapper
    return decorator

def invalidate_caches_for(operations: list) -> None:
    """
    Invalidate caches for specific operations.
    
    This is useful when data is modified and related caches need to be cleared.
    
    Args:
        operations: List of operation names to invalidate
    """
    for operation in operations:
        _cache.invalidate(operation)

def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    return _cache.get_stats()

def clear_cache() -> None:
    """Clear all cached data."""
    _cache.invalidate()

# TTL configurations for different types of data
CACHE_TTL = {
    "inbox": 30,          # 30 seconds - changes frequently
    "today": 30,          # 30 seconds - changes frequently  
    "upcoming": 60,       # 1 minute
    "anytime": 300,       # 5 minutes
    "someday": 300,       # 5 minutes
    "projects": 300,      # 5 minutes
    "areas": 600,         # 10 minutes - rarely changes
    "tags": 600,          # 10 minutes - rarely changes
    "logbook": 300,       # 5 minutes
    "trash": 300,         # 5 minutes
}

# Auto-cleanup task
def start_cache_cleanup_task(interval: int = 300):
    """Start a background task to clean up expired cache entries."""
    import threading
    
    def cleanup_task():
        while True:
            time.sleep(interval)
            _cache.cleanup_expired()
    
    thread = threading.Thread(target=cleanup_task, daemon=True)
    thread.start()
    logger.info(f"Started cache cleanup task with {interval}s interval")

# Start cleanup task when module is imported
start_cache_cleanup_task()