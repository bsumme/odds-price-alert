"""Background scheduler to refresh odds snapshots."""
from __future__ import annotations

import logging
import threading
from typing import Callable, Iterable, Optional

from services.snapshot import OddsSnapshot, SnapshotHolder
from services.snapshot_loader import SnapshotLoader

logger = logging.getLogger(__name__)


class SnapshotScheduler:
    """Run the snapshot loader on a fixed interval."""

    def __init__(
        self,
        loader: SnapshotLoader,
        holder: SnapshotHolder,
        *,
        interval_seconds: int,
        refresh_hooks: Optional[Iterable[Callable[[OddsSnapshot], None]]] = None,
        use_dummy_data: bool = False,
    ) -> None:
        self._loader = loader
        self._holder = holder
        self._interval_seconds = max(30, interval_seconds)
        self._refresh_hooks = list(refresh_hooks or [])
        self._use_dummy_data = use_dummy_data
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._thread:
            return

        self._stop_event.set()
        self._thread.join(timeout=5)

    def set_use_dummy_data(self, use_dummy_data: bool) -> None:
        """Toggle dummy-data usage for future refreshes."""
        self._use_dummy_data = use_dummy_data

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                snapshot = self._loader.load_snapshot(use_dummy_data=self._use_dummy_data)
                self._holder.set_snapshot(snapshot)
                logger.info(
                    "Snapshot refreshed at %s (dummy=%s, credits=%s)",
                    snapshot.fetched_at.isoformat(),
                    snapshot.use_dummy_data,
                    snapshot.total_credit_usage,
                )

                for hook in self._refresh_hooks:
                    try:
                        hook(snapshot)
                    except Exception:
                        logger.exception("Snapshot refresh hook failed")
            except Exception:
                logger.exception("Snapshot refresh failed")

            self._stop_event.wait(self._interval_seconds)
