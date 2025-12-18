"""Lightweight HTTP gateway that centralizes outbound calls."""
from __future__ import annotations

import threading
from typing import Any, Dict, Iterable

import requests


class ApiGateway:
    """Perform outbound HTTP GET requests with a simple allow list."""

    def __init__(
        self,
        *,
        allowed_callers: Iterable[str] | None = None,
        timeout: int = 15,
    ) -> None:
        self._allowed_callers = set(allowed_callers or {"snapshot_loader"})
        self._timeout = timeout
        self._lock = threading.Lock()

    def _ensure_allowed(self, caller: str) -> None:
        if caller not in self._allowed_callers:
            raise RuntimeError(
                f"ApiGateway may only be used by {sorted(self._allowed_callers)}; got caller '{caller}'"
            )

    def get(self, url: str, params: Dict[str, Any], *, caller: str) -> requests.Response:
        """
        Execute an HTTP GET request.

        The caller label is required to guard against accidental usage outside the
        snapshot loader path.
        """
        self._ensure_allowed(caller)
        # A lock avoids flooding external services when multiple snapshot iterations
        # overlap; it keeps the gateway usage serialized without impacting the rest
        # of the application.
        with self._lock:
            return requests.get(url, params=params, timeout=self._timeout)

