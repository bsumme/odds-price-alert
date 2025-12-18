"""In-memory cache for computed analytics derived from a snapshot."""
from __future__ import annotations

from typing import Any, Dict, Hashable, Tuple

from services.snapshot import OddsSnapshot


def _normalize_value(value: Any) -> Hashable:
    if isinstance(value, dict):
        return tuple(sorted((k, _normalize_value(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple, set)):
        return tuple(_normalize_value(v) for v in value)
    return value


class ResultsStore:
    """Cache computed results keyed by request parameters and snapshot version."""

    def __init__(self) -> None:
        self._store: Dict[Tuple[str, Hashable], Tuple[str, Any]] = {}

    def _build_key(self, scope: str, params: Dict[str, Any]) -> Tuple[str, Hashable]:
        return scope, _normalize_value(params)

    def get(self, *, scope: str, params: Dict[str, Any], snapshot: OddsSnapshot) -> Any:
        key = self._build_key(scope, params)
        entry = self._store.get(key)
        if not entry:
            return None

        snapshot_marker, value = entry
        if snapshot_marker != snapshot.fetched_at.isoformat():
            return None
        return value

    def set(
        self, *, scope: str, params: Dict[str, Any], snapshot: OddsSnapshot, value: Any
    ) -> None:
        key = self._build_key(scope, params)
        self._store[key] = (snapshot.fetched_at.isoformat(), value)

    def clear(self) -> None:
        self._store.clear()
