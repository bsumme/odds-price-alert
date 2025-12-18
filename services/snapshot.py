"""In-memory snapshot of odds, player props, and metadata."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass
class SnapshotEntry:
    """Payload captured for a single fetch call."""

    category: str
    sport_key: str
    markets: Tuple[str, ...]
    bookmaker_keys: Tuple[str, ...]
    events: List[Dict]
    fetched_at: datetime
    credit_usage: int = 0

    def matches(
        self,
        *,
        sport_key: str,
        markets: Iterable[str],
        bookmaker_keys: Iterable[str],
        category: Optional[str] = None,
    ) -> bool:
        markets_set = set(markets)
        bookmakers_set = set(bookmaker_keys)
        return (
            (category is None or self.category == category)
            and self.sport_key == sport_key
            and markets_set.issubset(set(self.markets))
            and bookmakers_set.issubset(set(self.bookmaker_keys))
        )


@dataclass
class OddsSnapshot:
    """Aggregate cached payloads for all configured sports/markets."""

    use_dummy_data: bool
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    total_credit_usage: int = 0
    entries: List[SnapshotEntry] = field(default_factory=list)

    def add_entry(
        self,
        *,
        category: str,
        sport_key: str,
        markets: Iterable[str],
        bookmaker_keys: Iterable[str],
        events: List[Dict],
        fetched_at: Optional[datetime] = None,
        credit_usage: int = 0,
    ) -> None:
        self.entries.append(
            SnapshotEntry(
                category=category,
                sport_key=sport_key,
                markets=tuple(sorted(set(markets))),
                bookmaker_keys=tuple(sorted(set(bookmaker_keys))),
                events=events,
                fetched_at=fetched_at or datetime.now(timezone.utc),
                credit_usage=credit_usage,
            )
        )
        self.total_credit_usage += max(0, credit_usage)

    def get_events(
        self,
        *,
        sport_key: str,
        markets: Iterable[str],
        bookmaker_keys: Iterable[str],
        category: str = "odds",
    ) -> List[Dict]:
        """Return the most recent payload that satisfies the requested scope."""

        candidates = [
            entry
            for entry in self.entries
            if entry.matches(
                sport_key=sport_key,
                markets=markets,
                bookmaker_keys=bookmaker_keys,
                category=category,
            )
        ]
        if not candidates:
            return []

        # Prefer the newest payload that covers all requested markets/books.
        selected = max(candidates, key=lambda e: e.fetched_at)
        return selected.events


class SnapshotHolder:
    """Thread-safe holder for the latest snapshot instance."""

    def __init__(self) -> None:
        self._snapshot: Optional[OddsSnapshot] = None
        self._lock = None
        # Lazy import to avoid threading unless required in constrained environments.
        import threading

        self._lock = threading.RLock()

    def set_snapshot(self, snapshot: OddsSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    def get_snapshot(self) -> Optional[OddsSnapshot]:
        with self._lock:
            return self._snapshot

