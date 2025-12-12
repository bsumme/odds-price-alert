"""
bet_watcher.py

Interactive odds watcher for The Odds API.

You can enter one or more bets like:
  - Team: New York Knicks
  - Target odds: -290  (meaning "-290 or better")
  - Books: DraftKings, FanDuel, Fliff (skip Novig)

Modes:
  - Normal: watch & alert in a loop
  - Snapshot: with --snapshot-only / -s, just print current odds once and exit

# NOTE: This script now serves as the single CLI watcher; the older
# nba_price_alert.py one-off script was removed because it duplicated
# the same polling logic. Fully merging the configs would require
# untangling interactive prompts and defaults across both tools, which
# is more involved than the quick cleanup we can safely do here.
"""

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Set

import requests

# Import shared utilities
from services.odds_api import get_api_key, fetch_odds
from services.odds_utils import is_price_or_better
from utils.regions import compute_regions_for_books
from utils.formatting import pretty_book_label

# Global configuration (you can tweak these if you want)
POLL_INTERVAL_SECONDS = 60  # how often to refresh odds
SPORT_KEY = "basketball_nba"  # for now we focus on NBA moneyline (h2h)


# --- Data structures --------------------------------------------------------


@dataclass
class BetConfig:
    team_name: str
    target_odds: int  # e.g. -290 or +120
    bookmaker_keys: List[str]  # e.g. ["draftkings", "fanduel", "fliff"]


BOOK_CHOICES = [
    ("draftkings", "DraftKings"),
    ("fanduel", "FanDuel"),
    ("novig", "Novig (exchange)"),
    ("fliff", "Fliff"),
]

# --- CLI args ---------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Watch NBA moneyline odds and get alerts when prices hit your lines."
    )
    parser.add_argument(
        "-s",
        "--snapshot-only",
        action="store_true",
        help="Just print current odds snapshot for the bets you enter, then exit.",
    )
    return parser.parse_args()


# --- Utility functions ------------------------------------------------------




def fetch_odds_for_watcher(
    api_key: str,
    sport_key: str,
    regions: str,
    markets: str = "h2h",
    bookmaker_keys: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """
    Wrapper for fetch_odds that matches bet_watcher's interface.
    """
    if not bookmaker_keys:
        bookmaker_keys = []
    return fetch_odds(api_key, sport_key, regions, markets, bookmaker_keys, use_dummy_data=False)


def sign_to_int(s: str) -> int:
    """
    Convert a string like '-290', '+120', '120' into an int.
    """
    s = s.strip()
    if s.startswith("+"):
        s = s[1:]
    return int(s)


# --- Core logic -------------------------------------------------------------


def extract_team_prices(
    events: List[Dict[str, Any]],
    team_name: str,
    bookmaker_keys: List[str],
    market_key: str = "h2h",
) -> List[Dict[str, Any]]:
    """
    For each event involving `team_name`, gather that team's price at each
    selected book (for the given market key).
    Returns list of dicts:
      {
        "event_id": ...,
        "home": ...,
        "away": ...,
        "start_time": ...,
        "prices": {book_key: price or None}
      }
    """
    games: List[Dict[str, Any]] = []

    for event in events:
        home = event.get("home_team")
        away = event.get("away_team")
        start_time = event.get("commence_time")
        event_id = event.get("id", "")

        if team_name not in (home, away):
            continue

        prices_for_game: Dict[str, Any] = {}

        for bookmaker in event.get("bookmakers", []):
            book_key = bookmaker.get("key")
            if book_key not in bookmaker_keys:
                continue

            market = next(
                (m for m in bookmaker.get("markets", []) if m.get("key") == market_key),
                None,
            )
            if not market:
                prices_for_game[book_key] = None
                continue

            price_for_team = None
            for outcome in market.get("outcomes", []):
                if outcome.get("name") == team_name:
                    price_for_team = outcome.get("price")
                    break

            prices_for_game[book_key] = price_for_team

        if prices_for_game:
            games.append(
                {
                    "event_id": event_id,
                    "home": home,
                    "away": away,
                    "start_time": start_time,
                    "prices": prices_for_game,
                }
            )

    return games




def print_snapshot(bets: List[BetConfig], events: List[Dict[str, Any]]) -> None:
    """
    Nice-looking snapshot of all tracked bets and current odds.
    """
    print("\n" + "=" * 80)
    print("CURRENT ODDS SNAPSHOT")
    print("=" * 80)

    any_games = False

    for i, bet in enumerate(bets, start=1):
        games = extract_team_prices(events, bet.team_name, bet.bookmaker_keys)
        if not games:
            print(f"[Bet {i}] {bet.team_name} — no upcoming games found.")
            print("-" * 80)
            continue

        any_games = True
        print(f"[Bet {i}] Team: {bet.team_name}, Target: {bet.target_odds} or better")
        for game in games:
            home = game["home"]
            away = game["away"]
            start_time = game["start_time"]
            prices = game["prices"]

            print(f"  Matchup: {away} @ {home}")
            print(f"  Start:   {start_time}")
            for book_key in bet.bookmaker_keys:
                price = prices.get(book_key)
                label = pretty_book_label(book_key)
                if price is None:
                    print(f"    {label:<15}: (no line)")
                else:
                    print(f"    {label:<15}: {price}")
            print("  " + "-" * 60)
        print("-" * 80)

    if not any_games:
        print("No upcoming games found for any tracked teams (check team names).")

    print("=" * 80 + "\n")


def find_alerts(
    bets: List[BetConfig],
    events: List[Dict[str, Any]],
    already_alerted: Set[str],
) -> List[Dict[str, Any]]:
    """
    Scan all bets and events for alert conditions.
    Returns list of alert dictionaries.
    """
    alerts: List[Dict[str, Any]] = []

    for bet_index, bet in enumerate(bets):
        games = extract_team_prices(events, bet.team_name, bet.bookmaker_keys)
        for game in games:
            event_id = game["event_id"]
            home = game["home"]
            away = game["away"]
            start_time = game["start_time"]
            prices = game["prices"]

            for book_key in bet.bookmaker_keys:
                price = prices.get(book_key)
                if price is None:
                    continue

                if not is_price_or_better(price, bet.target_odds):
                    continue

                alert_key = f"{bet_index}:{event_id}:{book_key}:{price}"
                if alert_key in already_alerted:
                    continue

                alerts.append(
                    {
                        "bet_index": bet_index,
                        "bet": bet,
                        "event_id": event_id,
                        "home": home,
                        "away": away,
                        "start_time": start_time,
                        "book_key": book_key,
                        "book_name": pretty_book_label(book_key),
                        "price": price,
                    }
                )
                already_alerted.add(alert_key)

    return alerts


def notify_console(alert: Dict[str, Any]) -> None:
    """
    Print a big alert block and beep.
    """
    bet: BetConfig = alert["bet"]
    team = bet.team_name
    target = bet.target_odds
    home = alert["home"]
    away = alert["away"]
    start_time = alert["start_time"]
    book_name = alert["book_name"]
    price = alert["price"]
    bet_index = alert["bet_index"] + 1

    # Beep (might or might not make a sound depending on terminal)
    try:
        print("\a", end="")
    except Exception:
        pass

    print("=" * 80)
    print(f"ALERT HIT! (Bet {bet_index})")
    print("-" * 80)
    print(f"Team:       {team}")
    print(f"Matchup:    {away} @ {home}")
    print(f"Start time: {start_time}")
    print(f"Book:       {book_name}")
    print(f"Current:    {price}")
    print(f"Target:     {target} or better")
    print("=" * 80 + "\n")


# --- Interactive setup (wizard) --------------------------------------------


def prompt_for_bets() -> List[BetConfig]:
    bets: List[BetConfig] = []

    print("=" * 80)
    print("WELCOME TO BET WATCHER")
    print("=" * 80)
    print("This tool watches NBA moneyline (h2h) odds for the teams you care about.")
    print("You can track multiple bets at once.")
    print()
    print("Example: New York Knicks -290 or better at DraftKings/FanDuel/Fliff.")
    print("=" * 80)
    print()

    while True:
        team = input("Enter team name (or just press Enter to finish): ").strip()
        if not team:
            break

        target_str = input(
            "Enter target odds (e.g. -290 or +120) meaning 'or better': "
        ).strip()
        try:
            target_odds = sign_to_int(target_str)
        except ValueError:
            print("  !! Could not parse odds. Please try that bet again.\n")
            continue

        print("\nSelect books to track for this bet:")
        for idx, (key, label) in enumerate(BOOK_CHOICES, start=1):
            print(f"  {idx}. {label} ({key})")

        choice = input(
            "Enter comma-separated numbers (e.g. 1,2,4), or press Enter for all: "
        ).strip()

        if not choice:
            book_keys = [key for key, _ in BOOK_CHOICES]
        else:
            try:
                indices = [
                    int(x.strip())
                    for x in choice.split(",")
                    if x.strip()
                ]
            except ValueError:
                print("  !! Invalid selection. Using all books for this bet.\n")
                book_keys = [key for key, _ in BOOK_CHOICES]
            else:
                book_keys = []
                for idx in indices:
                    if 1 <= idx <= len(BOOK_CHOICES):
                        book_keys.append(BOOK_CHOICES[idx - 1][0])
                if not book_keys:
                    print("  !! No valid selection. Using all books.\n")
                    book_keys = [key for key, _ in BOOK_CHOICES]

        bets.append(
            BetConfig(
                team_name=team,
                target_odds=target_odds,
                bookmaker_keys=book_keys,
            )
        )

        print("\nAdded bet:")
        print(f"  Team:   {team}")
        print(f"  Target: {target_odds} or better")
        print(
            "  Books:  "
            + ", ".join(pretty_book_label(bk) for bk in book_keys)
        )
        print("\n---\n")

    if not bets:
        print("No bets entered. Exiting.")
        sys.exit(0)

    print("SUMMARY OF TRACKED BETS:")
    for i, bet in enumerate(bets, start=1):
        print(
            f"  [{i}] {bet.team_name} @ {', '.join(pretty_book_label(bk) for bk in bet.bookmaker_keys)} "
            f"(target {bet.target_odds} or better)"
        )
    print()
    input("Press Enter to continue...")

    return bets


# --- Main loop -------------------------------------------------------------


def main() -> None:
    args = parse_args()

    try:
        api_key = get_api_key()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    bets = prompt_for_bets()

    # Compute all unique books to request, and regions for them
    all_book_keys: Set[str] = set()
    for bet in bets:
        all_book_keys.update(bet.bookmaker_keys)

    regions = compute_regions_for_books(list(all_book_keys))

    # Snapshot-only mode: just fetch once, print, and exit
    if args.snapshot_only:
        print("\n=== SNAPSHOT-ONLY MODE ===")
        print("Fetching current odds once and printing snapshot (no tracking).\n")
        try:
            events = fetch_odds_for_watcher(
                api_key=api_key,
                sport_key=SPORT_KEY,
                regions=regions,
                markets="h2h",
                bookmaker_keys=list(all_book_keys),
            )
        except requests.HTTPError as http_err:
            print(
                f"[ERROR] HTTP error: {http_err} "
                f"(status {http_err.response.status_code})",
                file=sys.stderr,
            )
            sys.exit(1)
        except Exception as e:
            print(f"[ERROR] Fetching odds failed: {e}", file=sys.stderr)
            sys.exit(1)

        print_snapshot(bets, events)
        print("Snapshot complete. Exiting because --snapshot-only was used.")
        return

    # Normal watch & alert mode
    print("\n" + "=" * 80)
    print("Starting odds watcher...")
    print(f"Sport:   {SPORT_KEY}")
    print(f"Regions: {regions}")
    print(f"Books:   {', '.join(sorted(all_book_keys))}")
    print(f"Polling every {POLL_INTERVAL_SECONDS} seconds.")
    print("=" * 80 + "\n")

    already_alerted: Set[str] = set()

    while True:
        try:
            events = fetch_odds_for_watcher(
                api_key=api_key,
                sport_key=SPORT_KEY,
                regions=regions,
                markets="h2h",
                bookmaker_keys=list(all_book_keys),
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

        # 1) Print a nice snapshot of where everything stands
        print_snapshot(bets, events)

        # 2) Check for alerts
        alerts = find_alerts(bets, events, already_alerted)
        if alerts:
            for alert in alerts:
                notify_console(alert)
        else:
            print("No alerts this cycle.\n")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
