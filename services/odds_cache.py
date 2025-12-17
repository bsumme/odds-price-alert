"""Lightweight in-memory caching helpers for odds API calls."""

from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable, Dict, Hashable, Tuple

CacheKey = Tuple[Hashable, ...]
CacheEntry = Tuple[float, Any]

_CACHE: Dict[CacheKey, CacheEntry] = {}
_SKIP_CACHE_KEYS = {"credit_tracker"}


def _freeze(value: Any) -> Hashable:
    """Convert common container types into hashable equivalents for cache keys."""

    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple, set)):
        return tuple(_freeze(v) for v in value)
    return value  # type: ignore[return-value]


def _build_cache_key(func_name: str, args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> CacheKey:
    """Create a stable cache key from function inputs, omitting volatile fields."""

    filtered_kwargs = {k: v for k, v in kwargs.items() if k not in _SKIP_CACHE_KEYS}
    frozen_args = tuple(_freeze(arg) for arg in args)
    frozen_kwargs = tuple(sorted((k, _freeze(v)) for k, v in filtered_kwargs.items()))
    return (func_name, frozen_args, frozen_kwargs)


def clear_odds_cache() -> None:
    """Reset all cached odds responses (useful in tests)."""

    _CACHE.clear()


def cached_odds(ttl: int) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a function to cache its result for ``ttl`` seconds."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("use_dummy_data"):
                return func(*args, **kwargs)

            cache_key = _build_cache_key(func.__name__, args, kwargs)
            now = time.monotonic()

            cached = _CACHE.get(cache_key)
            if cached:
                expires_at, value = cached
                if now < expires_at:
                    return value

            result = func(*args, **kwargs)
            _CACHE[cache_key] = (now + ttl, result)
            return result

        return wrapper

    return decorator

