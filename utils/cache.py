"""
Simple in-memory cache with TTL support for API responses.
"""
from datetime import datetime, timedelta
from typing import Any, Optional, Callable, TypeVar, cast
import functools
import hashlib
import json
from cachetools import TTLCache

# Generic type for function return values
T = TypeVar('T')

# Global cache instance - 100 items max, 30 second TTL
_odds_cache: TTLCache = TTLCache(maxsize=100, ttl=30)


def cache_key(*args, **kwargs) -> str:
    """Generate a stable cache key from function arguments."""
    # Convert args and kwargs to a stable string representation
    key_data = {
        'args': args,
        'kwargs': sorted(kwargs.items())  # Sort for stability
    }
    key_str = json.dumps(key_data, sort_keys=True, default=str)
    # Hash for shorter keys
    return hashlib.md5(key_str.encode()).hexdigest()


def cached_odds(ttl: int = 30):
    """
    Decorator to cache function results with a TTL.
    
    Args:
        ttl: Time to live in seconds (default 30)
    
    Usage:
        @cached_odds(ttl=30)
        def fetch_data(...):
            return expensive_operation()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        # Use a separate cache instance per TTL value
        func_cache: TTLCache = TTLCache(maxsize=100, ttl=ttl)
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # Skip caching if use_dummy_data is True
            if kwargs.get('use_dummy_data', False):
                return func(*args, **kwargs)
            
            # Generate cache key
            key = cache_key(*args, **kwargs)
            
            # Check cache
            if key in func_cache:
                return cast(T, func_cache[key])
            
            # Call function and cache result
            result = func(*args, **kwargs)
            func_cache[key] = result
            
            return result
        
        # Add method to clear this function's cache
        wrapper.clear_cache = lambda: func_cache.clear()  # type: ignore
        
        return wrapper
    
    return decorator


def clear_all_caches() -> None:
    """Clear all cached data."""
    _odds_cache.clear()