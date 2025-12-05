#!/usr/bin/env python3
"""Lightweight background hedge watcher CLI.

This module polls the existing "best value" logic to surface hedge
(opposite-side arbitrage) opportunities without running the web server.
Run it in the background with a long interval so it consumes minimal resources
and stop it by terminating the process (Ctrl+C or `kill`).
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Set

from fastapi import HTTPException

from main import (
    BestValuePlayOutcome,
    BestValuePlaysRequest,
    BestValuePlaysResponse,
    get_best_value_plays,
)
from utils.formatting import format_start_time_est, pretty_book_label


@dataclass
class HedgeWatcherConfig:
    """User configuration for the hedge watcher loop."""

    target_book: str
    compare_book: str
    sport_keys: List[str]
    markets: List[str]
    interval_seconds: int = 300
    max_results: int = 15
    min_margin_percent: float = 0.0
    use_dummy_data: bool = False

    def __post_init__(self) -> None:
        if self.interval_seconds < 5:
            raise ValueError("Poll interval must be at least 5 seconds to avoid hammering the API.")
        if self.max_results <= 0:
            raise ValueError("Max results must be positive.")


def play_identifier(play: BestValuePlayOutcome) -> str:
    """Create a stable identifier for deduplicating plays across polls."""

    return f"{play.event_id}:{play.market}:{play.outcome_name}"


def filter_by_margin(
    plays: Iterable[BestValuePlayOutcome], min_margin_percent: float
) -> List[BestValuePlayOutcome]:
    """Return plays whose arbitrage margin meets or exceeds the threshold."""

    return [
        play
        for play in plays
        if play.arb_margin_percent is not None and play.arb_margin_percent >= min_margin_percent
    ]


def format_odds(odds: int | None) -> str:
    """Display odds with a leading plus sign when appropriate."""

    if odds is None:
        return "N/A"
    return f"+{odds}" if odds > 0 else str(odds)


def format_play_summary(play: BestValuePlayOutcome) -> str:
    """Build a single-line summary for console logging."""

    margin = "N/A"
    if play.arb_margin_percent is not None:
        margin = f"{round(play.arb_margin_percent, 2)}%"

    start_time = play.start_time or "TBD"
    start_label = format_start_time_est(start_time) if play.start_time else start_time

    return (
        f"{play.matchup} | {play.sport_key} {play.market} | {play.outcome_name}"
        f" @ {format_odds(play.book_price)} (hedge {format_odds(play.novig_reverse_price)})"
        f" — margin {margin}, starts {start_label}"
    )


class HedgeWatcher:
    """Loop that polls the best-value endpoint and logs hedge opportunities."""

    def __init__(self, config: HedgeWatcherConfig):
        self.config = config
        self._stop_event = threading.Event()
        self._seen_ids: Set[str] = set()

    def _poll(self) -> List[BestValuePlayOutcome]:
        """Fetch and filter hedge plays using the shared best-value logic."""

        request = BestValuePlaysRequest(
            sport_keys=self.config.sport_keys,
            markets=self.config.markets,
            target_book=self.config.target_book,
            compare_book=self.config.compare_book,
            max_results=self.config.max_results,
            use_dummy_data=self.config.use_dummy_data,
        )

        response: BestValuePlaysResponse = get_best_value_plays(request)
        return filter_by_margin(response.plays, self.config.min_margin_percent)

    def _log_cycle(self, plays: List[BestValuePlayOutcome]) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not plays:
            print(
                f"[{timestamp}] No hedge opportunities (margin ≥ {self.config.min_margin_percent}%)."
                f" Next check in {self.config.interval_seconds}s."
            )
            return

        print(
            f"[{timestamp}] Found {len(plays)} hedge opportunities with margin ≥"
            f" {self.config.min_margin_percent}% (showing up to {self.config.max_results})."
        )

        new_count = 0
        for play in plays:
            pid = play_identifier(play)
            is_new = pid not in self._seen_ids
            if is_new:
                new_count += 1
            self._seen_ids.add(pid)

            marker = " [new]" if is_new else ""
            print(f"  • {format_play_summary(play)}{marker}")

        print(
            f"[{timestamp}] Cycle complete: {new_count} new. Next check in {self.config.interval_seconds}s."
        )

    def run_forever(self) -> None:
        """Start the watcher loop until interrupted."""

        def _handle_signal(signum: int, _: object) -> None:
            print(f"\nReceived signal {signum}. Shutting down hedge watcher...")
            self._stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, _handle_signal)

        target_label = pretty_book_label(self.config.target_book)
        compare_label = pretty_book_label(self.config.compare_book)
        print(
            "🛡️  Hedge watcher started."
            f" Watching {target_label} versus {compare_label} every {self.config.interval_seconds}s.\n"
            f"Sports: {', '.join(self.config.sport_keys)} | Markets: {', '.join(self.config.markets)}\n"
            f"Minimum margin: {self.config.min_margin_percent}% | Max results: {self.config.max_results}\n"
            "Use Ctrl+C or kill the process to stop it."
        )

        while not self._stop_event.is_set():
            try:
                plays = self._poll()
                self._log_cycle(plays)
            except HTTPException as http_exc:
                print(f"Watcher error: {http_exc.detail}. Retrying in {self.config.interval_seconds}s...")
            except Exception as exc:  # pragma: no cover - safety net for background runtime
                print(f"Unexpected error: {exc}. Retrying in {self.config.interval_seconds}s...")

            self._stop_event.wait(self.config.interval_seconds)

        print("Hedge watcher stopped.")


def parse_args(argv: List[str]) -> HedgeWatcherConfig:
    parser = argparse.ArgumentParser(description="Background hedge watcher that polls in a loop.")
    parser.add_argument(
        "--target-book",
        default="draftkings",
        help="Sportsbook to monitor for your primary bets (default: draftkings)",
    )
    parser.add_argument(
        "--compare-book",
        default="novig",
        help="Exchange/book to compare against for the hedge side (default: novig)",
    )
    parser.add_argument(
        "--sport",
        dest="sports",
        action="append",
        default=["basketball_nba", "americanfootball_nfl"],
        help="Sport key to include (can be provided multiple times).",
    )
    parser.add_argument(
        "--market",
        dest="markets",
        action="append",
        default=["h2h"],
        help="Market to include (can be provided multiple times, default: h2h).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Poll interval in seconds (default: 300). Use a higher value to minimize resource usage.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=15,
        help="Maximum number of plays to print each cycle (default: 15).",
    )
    parser.add_argument(
        "--min-margin",
        type=float,
        default=0.0,
        help="Only surface plays with arbitrage margin at or above this percent (default: 0.0).",
    )
    parser.add_argument(
        "--use-dummy-data",
        action="store_true",
        help="Use built-in dummy odds instead of hitting the real API (no API key required).",
    )

    args = parser.parse_args(argv)

    return HedgeWatcherConfig(
        target_book=args.target_book,
        compare_book=args.compare_book,
        sport_keys=args.sports,
        markets=args.markets,
        interval_seconds=args.interval,
        max_results=args.max_results,
        min_margin_percent=args.min_margin,
        use_dummy_data=args.use_dummy_data,
    )


def main(argv: List[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    config = parse_args(argv)
    watcher = HedgeWatcher(config)
    watcher.run_forever()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
