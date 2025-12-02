"""
line_tracker.py

Track line movement for specific games (moneyline, spread, and total)
by polling The Odds API every minute and logging snapshots.

Example usage (interactive):
  python line_tracker.py

You will be prompted for:
  - Sport key        (e.g. americanfootball_nfl, basketball_nba)
  - Bookmakers       (DraftKings, FanDuel, Novig, Fliff)
  - Teams to track   (e.g. New Orleans Saints vs Atlanta Falcons)
  - Markets to track (ML, spreads, totals)

The script will then:
  - Print the current lines for each selected game once per minute.
  - Append structured JSONL records into logs/line_movement_tracker.jsonl
    with a clear log_type label so they are easy to analyze later.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from services.odds_api import get_api_key, fetch_odds
from utils.regions import compute_regions_for_books
from utils.formatting import pretty_book_label


POLL_INTERVAL_SECONDS = 60  # print & log lines every minute


@dataclass
class GameSelection:
    sport_key: str
    home_query: str
    away_query: str
    bookmaker_keys: List[str]
    track_ml: bool
    track_spreads: bool
    track_totals: bool


BOOK_CHOICES = [
    ("draftkings", "DraftKings"),
    ("fanduel", "FanDuel"),
    ("novig", "Novig (exchange)"),
    ("fliff", "Fliff"),
]


def _ensure_logs_dir() -> str:
    """Return path to logs directory, creating it if needed."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(base_dir)
    logs_dir = os.path.join(project_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir


def _log_line_snapshot(record: Dict[str, Any]) -> None:
    """
    Append one line-movement snapshot to logs/line_movement_tracker.jsonl.
    Failures here should not break the tracker.
    """
    try:
        logs_dir = _ensure_logs_dir()
        log_path = os.path.join(logs_dir, "line_movement_tracker.jsonl")
        # Add a stable label so this log can be filtered later
        record.setdefault("log_type", "line_movement_tracker")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record))
            f.write("\n")
    except Exception:
        # Logging is best-effort only
        pass


def _matches_team(query: str, team_name: Optional[str]) -> bool:
    """Case-insensitive substring match helper for team selection."""
    if not query:
        return False
    if not team_name:
        return False
    return query.lower() in team_name.lower()


def _extract_market_lines(
    event: Dict[str, Any],
    bookmaker_keys: List[str],
    track_ml: bool,
    track_spreads: bool,
    track_totals: bool,
) -> Dict[str, Any]:
    """
    Extract ML, spread, and total info for an event for each requested bookmaker.
    Returns a dict keyed by bookmaker with nested market data.
    """
    home = event.get("home_team")
    away = event.get("away_team")

    per_book: Dict[str, Any] = {}

    for bookmaker in event.get("bookmakers", []):
        book_key = bookmaker.get("key")
        if book_key not in bookmaker_keys:
            continue

        book_entry: Dict[str, Any] = {}

        # Moneyline (h2h)
        if track_ml:
            h2h_market = next(
                (m for m in bookmaker.get("markets", []) if m.get("key") == "h2h"),
                None,
            )
            if h2h_market:
                home_price = None
                away_price = None
                for outcome in h2h_market.get("outcomes", []):
                    name = outcome.get("name")
                    if name == home:
                        home_price = outcome.get("price")
                    elif name == away:
                        away_price = outcome.get("price")
                book_entry["moneyline"] = {
                    "home_price": home_price,
                    "away_price": away_price,
                }

        # Spreads
        if track_spreads:
            spread_market = next(
                (m for m in bookmaker.get("markets", []) if m.get("key") == "spreads"),
                None,
            )
            if spread_market:
                home_point = None
                home_price = None
                away_point = None
                away_price = None
                for outcome in spread_market.get("outcomes", []):
                    name = outcome.get("name")
                    if name == home:
                        home_point = outcome.get("point")
                        home_price = outcome.get("price")
                    elif name == away:
                        away_point = outcome.get("point")
                        away_price = outcome.get("price")
                book_entry["spread"] = {
                    "home_point": home_point,
                    "home_price": home_price,
                    "away_point": away_point,
                    "away_price": away_price,
                }

        # Totals
        if track_totals:
            totals_market = next(
                (m for m in bookmaker.get("markets", []) if m.get("key") == "totals"),
                None,
            )
            if totals_market:
                total_point = None
                over_price = None
                under_price = None
                for outcome in totals_market.get("outcomes", []):
                    name = outcome.get("name", "")
                    price = outcome.get("price")
                    point = outcome.get("point")
                    # The Odds API typically uses names like "Over 45.5" / "Under 45.5"
                    if "over" in name.lower():
                        total_point = point
                        over_price = price
                    elif "under" in name.lower():
                        total_point = point
                        under_price = price
                book_entry["total"] = {
                    "point": total_point,
                    "over_price": over_price,
                    "under_price": under_price,
                }

        if book_entry:
            per_book[book_key] = book_entry

    return per_book


def _print_game_snapshot(
    event: Dict[str, Any],
    per_book: Dict[str, Any],
    track_ml: bool,
    track_spreads: bool,
    track_totals: bool,
) -> None:
    """Pretty-print the current lines for a single event."""
    home = event.get("home_team")
    away = event.get("away_team")
    start_time = event.get("commence_time")
    matchup = f"{away} @ {home}"

    print("-" * 80)
    print(f"Matchup: {matchup}")
    print(f"Start:   {start_time}")
    print()

    for book_key, markets in per_book.items():
        label = pretty_book_label(book_key)
        print(f"{label}:")

        if track_ml:
            ml = markets.get("moneyline")
            if ml:
                print(
                    f"  ML   - Home: {ml.get('home_price')!s:>5} | "
                    f"Away: {ml.get('away_price')!s:>5}"
                )
            else:
                print("  ML   - (no line)")

        if track_spreads:
            sp = markets.get("spread")
            if sp:
                print(
                    "  SP   - "
                    f"Home: {sp.get('home_point')} ({sp.get('home_price')}) | "
                    f"Away: {sp.get('away_point')} ({sp.get('away_price')})"
                )
            else:
                print("  SP   - (no line)")

        if track_totals:
            tot = markets.get("total")
            if tot:
                print(
                    "  TOT  - "
                    f"{tot.get('point')}  Over: {tot.get('over_price')} | "
                    f"Under: {tot.get('under_price')}"
                )
            else:
                print("  TOT  - (no line)")

        print()


def prompt_for_game_selection() -> GameSelection:
    """
    Gather user input for which game/markets to track.
    """
    print("=" * 80)
    print("LINE MOVEMENT TRACKER")
    print("=" * 80)
    print("This tool prints and logs line movement for a specific game.")
    print("You'll choose a sport, books, teams, and which markets to track.")
    print("=" * 80)
    print()

    sport_key = input(
        "Enter sport key (e.g. americanfootball_nfl, basketball_nba): "
    ).strip()
    if not sport_key:
        print("No sport key provided. Exiting.")
        sys.exit(0)

    print("\nSelect books to track for this game:")
    for idx, (key, label) in enumerate(BOOK_CHOICES, start=1):
        print(f"  {idx}. {label} ({key})")

    choice = input(
        "Enter comma-separated numbers (e.g. 1,2,4), or press Enter for all: "
    ).strip()

    if not choice:
        bookmaker_keys = [key for key, _ in BOOK_CHOICES]
    else:
        try:
            indices = [
                int(x.strip()) for x in choice.split(",") if x.strip()
            ]
        except ValueError:
            print("  !! Invalid selection. Using all books.\n")
            bookmaker_keys = [key for key, _ in BOOK_CHOICES]
        else:
            bookmaker_keys = []
            for idx in indices:
                if 1 <= idx <= len(BOOK_CHOICES):
                    bookmaker_keys.append(BOOK_CHOICES[idx - 1][0])
            if not bookmaker_keys:
                print("  !! No valid selection. Using all books.\n")
                bookmaker_keys = [key for key, _ in BOOK_CHOICES]

    print("\nEnter team names or keywords to identify the matchup.")
    print("For example, for Saints vs Falcons you might enter:")
    print("  Home team keyword:  Saints")
    print("  Away team keyword:  Falcons")
    print("Matching is case-insensitive and uses substring search.\n")

    home_query = input("Home team keyword: ").strip()
    away_query = input("Away team keyword: ").strip()
    if not home_query or not away_query:
        print("Both home and away team keywords are required. Exiting.")
        sys.exit(0)

    print("\nWhich markets do you want to track?")
    track_ml = input("  Track moneyline (ML)? [Y/n]: ").strip().lower() != "n"
    track_spreads = (
        input("  Track spreads? [Y/n]: ").strip().lower() != "n"
    )
    track_totals = (
        input("  Track totals? [Y/n]: ").strip().lower() != "n"
    )

    if not (track_ml or track_spreads or track_totals):
        print("No markets selected. Exiting.")
        sys.exit(0)

    return GameSelection(
        sport_key=sport_key,
        home_query=home_query,
        away_query=away_query,
        bookmaker_keys=bookmaker_keys,
        track_ml=track_ml,
        track_spreads=track_spreads,
        track_totals=track_totals,
    )


def main() -> None:
    try:
        api_key = get_api_key()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    selection = prompt_for_game_selection()

    # Compute regions for this set of books
    regions = compute_regions_for_books(selection.bookmaker_keys)

    markets_to_request: List[str] = []
    if selection.track_ml:
        markets_to_request.append("h2h")
    if selection.track_spreads:
        markets_to_request.append("spreads")
    if selection.track_totals:
        markets_to_request.append("totals")
    markets_param = ",".join(markets_to_request)

    print("\n" + "=" * 80)
    print("Starting line movement tracker...")
    print(f"Sport:   {selection.sport_key}")
    print(f"Regions: {regions}")
    print(
        "Books:   "
        + ", ".join(sorted(selection.bookmaker_keys))
    )
    print(
        "Markets: "
        + ", ".join(markets_to_request)
    )
    print(f"Polling every {POLL_INTERVAL_SECONDS} seconds.")
    print("Press Ctrl+C to stop.")
    print("=" * 80 + "\n")

    while True:
        try:
            events = fetch_odds(
                api_key=api_key,
                sport_key=selection.sport_key,
                regions=regions,
                markets=markets_param,
                bookmaker_keys=selection.bookmaker_keys,
                use_dummy_data=False,
            )
        except requests.HTTPError as http_err:
            print(
                f"[ERROR] HTTP error: {http_err} "
                f"(status {http_err.response.status_code})",
                file=sys.stderr,
            )
            time.sleep(POLL_INTERVAL_SECONDS * 2)
            continue
        except Exception as e:
            print(f"[ERROR] Fetching odds failed: {e}", file=sys.stderr)
            time.sleep(POLL_INTERVAL_SECONDS * 2)
            continue

        now_utc = datetime.utcnow().isoformat() + "Z"
        print(f"\n[{now_utc}] Current lines:")

        any_match = False

        for event in events:
            home = event.get("home_team")
            away = event.get("away_team")
            if not (
                _matches_team(selection.home_query, home)
                and _matches_team(selection.away_query, away)
            ):
                continue

            any_match = True

            per_book = _extract_market_lines(
                event=event,
                bookmaker_keys=selection.bookmaker_keys,
                track_ml=selection.track_ml,
                track_spreads=selection.track_spreads,
                track_totals=selection.track_totals,
            )

            # Print to console
            _print_game_snapshot(
                event=event,
                per_book=per_book,
                track_ml=selection.track_ml,
                track_spreads=selection.track_spreads,
                track_totals=selection.track_totals,
            )

            # Log to file
            snapshot_record = {
                "timestamp": now_utc,
                "sport_key": selection.sport_key,
                "regions": regions,
                "markets": markets_to_request,
                "bookmaker_keys": selection.bookmaker_keys,
                "event_id": event.get("id"),
                "home_team": home,
                "away_team": away,
                "start_time": event.get("commence_time"),
                "lines": per_book,
            }
            _log_line_snapshot(snapshot_record)

        if not any_match:
            print(
                "No events found matching "
                f"home='{selection.home_query}' and away='{selection.away_query}'."
            )

        try:
            time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("\nStopping line movement tracker. Goodbye.")
            sys.exit(0)


if __name__ == "__main__":
    main()




