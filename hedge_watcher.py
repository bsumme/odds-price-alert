#!/usr/bin/env python3
"""Lightweight background hedge watcher CLI.

This module polls the existing "best value" logic to surface hedge
(opposite-side arbitrage) opportunities without running the web server.
Run it in the background with a long interval so it consumes minimal resources
and stop it by terminating the process (Ctrl+C or `kill`).
"""

from __future__ import annotations

import argparse
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Sequence, Set
import signal

from fastapi import HTTPException
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imports for type checking only to avoid circular imports
    from main import (
        BestValuePlayOutcome,
        BestValuePlaysRequest,
        BestValuePlaysResponse,
        get_best_value_plays,
    )
from utils.formatting import BOOK_LABELS, format_start_time_est, pretty_book_label

DEFAULT_SPORTS = ["basketball_nba", "americanfootball_nfl", "baseball_mlb", "icehockey_nhl"]
DEFAULT_MARKETS = ["h2h", "spreads", "totals"]
DEFAULT_TARGET_BOOK = "draftkings"
DEFAULT_COMPARE_BOOK = "novig"
DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_MAX_RESULTS = 15
DEFAULT_MIN_MARGIN = 0.0


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


def _prompt_single_choice(prompt: str, options: Sequence[str], default: str) -> str:
    """Prompt the user to pick a single value from a numbered list."""

    print(prompt)
    for idx, option in enumerate(options, start=1):
        print(f"  {idx}) {option}")

    raw = input(f"Enter choice (1-{len(options)}) [default {default}]: ").strip()
    if not raw:
        return default

    try:
        selection = int(raw)
        if 1 <= selection <= len(options):
            return options[selection - 1]
    except ValueError:
        pass

    print(f"Invalid selection '{raw}'. Using default '{default}'.")
    return default


def _prompt_multi_choice(prompt: str, options: Sequence[str], defaults: Sequence[str]) -> List[str]:
    """Prompt the user to pick one or more values from a numbered list."""

    print(prompt)
    for idx, option in enumerate(options, start=1):
        print(f"  {idx}) {option}")

    default_indexes = ",".join(str(options.index(value) + 1) for value in defaults if value in options)
    raw = input(
        "Enter comma-separated choices (e.g. 1,3) "
        f"[default {default_indexes or 'none'}]: "
    ).strip()
    if not raw:
        return list(defaults)

    selections: List[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            selection = int(token)
            if 1 <= selection <= len(options):
                value = options[selection - 1]
                if value not in selections:
                    selections.append(value)
        except ValueError:
            continue

    if not selections:
        print("No valid selections provided. Using defaults.")
        return list(defaults)

    return selections


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


def _prompt_numeric(
    prompt: str, default: float, cast: type, minimum: float | None = None
) -> float | int:
    """Prompt the user for a numeric value with validation and defaults."""

    raw = input(f"{prompt} [default {default}]: ").strip()
    if not raw:
        return default

    try:
        value = cast(raw)
        if minimum is not None and value < minimum:
            raise ValueError
        return value
    except (ValueError, TypeError):
        min_msg = f" (minimum {minimum})" if minimum is not None else ""
        print(f"Invalid value. Using default {default}{min_msg}.")
        return default


def prompt_interactive_config() -> HedgeWatcherConfig:
    """Collect watcher parameters through a multiple-choice CLI flow."""

    print("\n🎛️  Interactive hedge watcher setup\n")

    book_options = list(BOOK_LABELS.keys())
    target_book = _prompt_single_choice(
        "Select the primary sportsbook (where your main bets are placed):",
        book_options,
        DEFAULT_TARGET_BOOK,
    )
    compare_book = _prompt_single_choice(
        "Select the exchange/book for hedge opportunities:",
        book_options,
        DEFAULT_COMPARE_BOOK,
    )

    sport_keys = _prompt_multi_choice(
        "Select sports to monitor (comma-separated for multiple):",
        DEFAULT_SPORTS,
        DEFAULT_SPORTS,
    )
    markets = _prompt_multi_choice(
        "Select markets to monitor (comma-separated for multiple):",
        DEFAULT_MARKETS,
        DEFAULT_MARKETS[:1],
    )

    interval_seconds = int(
        _prompt_numeric(
            "Polling interval in seconds (higher values reduce API usage)",
            DEFAULT_INTERVAL_SECONDS,
            int,
            minimum=5,
        )
    )
    max_results = int(
        _prompt_numeric("Maximum number of plays to display each cycle", DEFAULT_MAX_RESULTS, int, minimum=1)
    )
    min_margin_percent = float(
        _prompt_numeric(
            "Minimum arbitrage margin percent to surface", DEFAULT_MIN_MARGIN, float, minimum=0.0
        )
    )

    use_dummy_data = (
        input("Use dummy odds data instead of live API? (y/N): ").strip().lower() in {"y", "yes"}
    )

    print("\nStarting hedge watcher with your selections...\n")

    return HedgeWatcherConfig(
        target_book=target_book,
        compare_book=compare_book,
        sport_keys=sport_keys,
        markets=markets,
        interval_seconds=interval_seconds,
        max_results=max_results,
        min_margin_percent=min_margin_percent,
        use_dummy_data=use_dummy_data,
    )


class HedgeWatcher:
    """Loop that polls the best-value endpoint and logs hedge opportunities."""

    def __init__(self, config: HedgeWatcherConfig):
        self.config = config
        self._stop_event = threading.Event()
        self._seen_ids: Set[str] = set()

    def _poll(self) -> List[BestValuePlayOutcome]:
        """Fetch and filter hedge plays using the shared best-value logic."""

        # Import runtime dependencies here to avoid circular-imports when the
        # FastAPI app imports this module (the server may import hedge_watcher
        # dynamically to start a watcher). Importing at call-time keeps module
        # import-time side-effects minimal.
        from main import BestValuePlaysRequest, get_best_value_plays  # local import

        request = BestValuePlaysRequest(
            sport_keys=self.config.sport_keys,
            markets=self.config.markets,
            target_book=self.config.target_book,
            compare_book=self.config.compare_book,
            max_results=self.config.max_results,
            use_dummy_data=self.config.use_dummy_data,
        )

        response = get_best_value_plays(request)
        # response.plays is a list of BestValuePlayOutcome instances
        return filter_by_margin(response.plays, self.config.min_margin_percent)

    def _log_cycle(self, plays: List[BestValuePlayOutcome], log_fn=print) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not plays:
            log_fn(
                f"[{timestamp}] No hedge opportunities (margin ≥ {self.config.min_margin_percent}%)."
                f" Next check in {self.config.interval_seconds}s."
            )
            return

        log_fn(
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
            log_fn(f"  • {format_play_summary(play)}{marker}")

        log_fn(
            f"[{timestamp}] Cycle complete: {new_count} new. Next check in {self.config.interval_seconds}s."
        )

    def run_forever(self) -> None:
        """Start the watcher loop until interrupted."""

        try:
            self.run_with_stop_event(self._stop_event, log_fn=print)
        except KeyboardInterrupt:
            print("\nKeyboard interrupt received. Shutting down hedge watcher...")
            self._stop_event.set()

    def run_with_stop_event(self, stop_event: threading.Event, log_fn=print) -> None:
        """Run the watcher loop using an external stop event and logger."""

        target_label = pretty_book_label(self.config.target_book)
        compare_label = pretty_book_label(self.config.compare_book)
        log_fn(
            "🛡️  Hedge watcher started."
            f" Watching {target_label} versus {compare_label} every {self.config.interval_seconds}s.\n"
            f"Sports: {', '.join(self.config.sport_keys)} | Markets: {', '.join(self.config.markets)}\n"
            f"Minimum margin: {self.config.min_margin_percent}% | Max results: {self.config.max_results}\n"
            "Use the API stop endpoint or press Ctrl-C (or Ctrl-Break) to stop it."
        )

        while not stop_event.is_set():
            try:
                plays = self._poll()
                self._log_cycle(plays, log_fn=log_fn)
            except HTTPException as http_exc:
                log_fn(
                    "Watcher error:"
                    f" {http_exc.detail}. Retrying in {self.config.interval_seconds}s..."
                )
            except Exception as exc:  # pragma: no cover - safety net for background runtime
                log_fn(
                    "Unexpected error:"
                    f" {exc}. Retrying in {self.config.interval_seconds}s..."
                )

            if stop_event.wait(self.config.interval_seconds):
                break

        log_fn("Hedge watcher stopped.")


def parse_args(argv: List[str]) -> HedgeWatcherConfig:
    parser = argparse.ArgumentParser(description="Background hedge watcher that polls in a loop.")
    parser.add_argument(
        "--target-book",
        default=DEFAULT_TARGET_BOOK,
        help="Sportsbook to monitor for your primary bets (default: draftkings)",
    )
    parser.add_argument(
        "--compare-book",
        default=DEFAULT_COMPARE_BOOK,
        help="Exchange/book to compare against for the hedge side (default: novig)",
    )
    parser.add_argument(
        "--sport",
        dest="sports",
        action="append",
        default=DEFAULT_SPORTS,
        help="Sport key to include (can be provided multiple times).",
    )
    parser.add_argument(
        "--market",
        dest="markets",
        action="append",
        default=DEFAULT_MARKETS[:1],
        help="Market to include (can be provided multiple times, default: h2h).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Poll interval in seconds (default: 300). Use a higher value to minimize resource usage.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=DEFAULT_MAX_RESULTS,
        help="Maximum number of plays to print each cycle (default: 15).",
    )
    parser.add_argument(
        "--min-margin",
        type=float,
        default=DEFAULT_MIN_MARGIN,
        help="Only surface plays with arbitrage margin at or above this percent (default: 0.0).",
    )
    parser.add_argument(
        "--use-dummy-data",
        action="store_true",
        help="Use built-in dummy odds instead of hitting the real API (no API key required).",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Launch an interactive menu to choose parameters instead of command-line flags.",
    )

    args = parser.parse_args(argv)

    if args.interactive:
        return prompt_interactive_config()

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
    # Install OS signal handlers so Ctrl-C / Ctrl-Break / termination requests
    # set the watcher's stop event and allow the loop to exit cleanly.
    def _handler(signum, frame):
        print("\nSignal received. Stopping hedge watcher...")
        watcher._stop_event.set()

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, sig_name):
            try:
                signal.signal(getattr(signal, sig_name), _handler)
            except Exception:
                # Ignore platforms where a signal can't be set
                pass
    watcher.run_forever()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
