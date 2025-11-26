import sys
import time
from typing import Any, Dict, List, Set

import requests

# Import shared utilities
from services.odds_api import get_api_key, BASE_URL
from utils.regions import compute_regions_for_books

# === CONFIG: change these to whatever you want ============================
SPORT_KEY = "basketball_nba"          # e.g. "basketball_nba", "americanfootball_nfl"
TARGET_TEAM = "New York Knicks"        # team name as in the API
TARGET_MARKET = "h2h"                 # "h2h" (moneyline), "spreads", "totals", etc.
TARGET_MIN_PRICE = -290                # want +120 or better (American odds)

# Books you care about (keys from The Odds API)
TARGET_BOOKMAKER_KEYS = [
    "draftkings",
    "fanduel",
    "fliff",
]

# Regions needed to see these books:
#   - US main books (DK/FD): "us"
#   - Fliff: "us2"
#   - Novig: "us_ex"
REGIONS = "us,us2,us_ex"

CHECK_INTERVAL_SECONDS = 60           # how often to poll the API (seconds)
SHOW_CURRENT_ODDS = True              # print current odds every loop for comparison
# ==========================================================================


def fetch_odds_for_sport(
    api_key: str,
    sport_key: str,
    markets: str,
    regions: str,
    bookmaker_keys: List[str],
) -> List[Dict[str, Any]]:
    """
    Wrapper for fetch_odds that matches nba_price_alert's interface.
    """
    from services.odds_api import fetch_odds
    return fetch_odds(api_key, sport_key, regions, markets, bookmaker_keys, use_dummy_data=False)


def extract_team_prices_per_game(
    events: List[Dict[str, Any]],
    team_name: str,
    bookmaker_keys: List[str],
    market_key: str,
) -> List[Dict[str, Any]]:
    """
    For each game where `team_name` appears, collect prices for that team
    across the given bookmakers for the specified market.
    Returns a list of:
      {
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

        # Quick check: skip events where team isn't playing
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
                    "home": home,
                    "away": away,
                    "start_time": start_time,
                    "prices": prices_for_game,
                }
            )

    return games


def print_current_team_prices(
    events: List[Dict[str, Any]],
    team_name: str,
    bookmaker_keys: List[str],
    market_key: str,
) -> None:
    """
    Print a snapshot of current odds for the target team across target books.
    """
    games = extract_team_prices_per_game(events, team_name, bookmaker_keys, market_key)

    if not games:
        print(f"[INFO] No upcoming games found for {team_name}.")
        return

    print("\n=== CURRENT ODDS SNAPSHOT =============================================")
    for game in games:
        home = game["home"]
        away = game["away"]
        start_time = game["start_time"]
        prices = game["prices"]

        print(f"{away} @ {home}")
        print(f"Start: {start_time}")
        for book_key in bookmaker_keys:
            price = prices.get(book_key)
            label = book_key
            if price is None:
                print(f"  {label}: (no line / not available)")
            else:
                print(f"  {label}: {price}")
        print("-" * 70)
    print("======================================================================\n")


def find_alerts_for_team(
    events: List[Dict[str, Any]],
    team_name: str,
    min_price: int,
    bookmaker_keys: List[str],
    market_key: str,
    already_alerted: Set[str] | None = None,
) -> List[Dict[str, Any]]:
    """
    Return a list of alert-worthy outcomes:
    entries where `team_name` has odds >= `min_price` at any target bookmaker.
    """
    if already_alerted is None:
        already_alerted = set()

    alerts: List[Dict[str, Any]] = []

    for event in events:
        event_id = event.get("id", "")
        home = event.get("home_team")
        away = event.get("away_team")
        start_time = event.get("commence_time")

        for bookmaker in event.get("bookmakers", []):
            book_key = bookmaker.get("key")
            book_name = bookmaker.get("title")

            if book_key not in bookmaker_keys:
                continue

            market = next(
                (m for m in bookmaker.get("markets", []) if m.get("key") == market_key),
                None,
            )
            if not market:
                continue

            for outcome in market.get("outcomes", []):
                name = outcome.get("name")
                price = outcome.get("price")

                if name != team_name:
                    continue
                if price is None:
                    continue

                # For plus odds, "better" means larger number (e.g. +140 >= +120)
                if price >= min_price:
                    alert_key = f"{event_id}:{book_key}:{team_name}:{price}"
                    if alert_key in already_alerted:
                        continue

                    alerts.append(
                        {
                            "event_id": event_id,
                            "home": home,
                            "away": away,
                            "start_time": start_time,
                            "book_key": book_key,
                            "book_name": book_name,
                            "team": name,
                            "price": price,
                        }
                    )
                    already_alerted.add(alert_key)

    return alerts


def notify_console(alert: Dict[str, Any]) -> None:
    """
    Simple notification: print to console (and beep).
    You can later extend this to Telegram/email/etc.
    """
    home = alert["home"]
    away = alert["away"]
    start_time = alert["start_time"]
    book_name = alert["book_name"]
    team = alert["team"]
    price = alert["price"]

    # Basic Windows beep
    try:
        print("\a", end="")  # bell character
    except Exception:
        pass

    print("=" * 70)
    print("PRICE ALERT HIT!")
    print(f"Game: {away} @ {home}")
    print(f"Start: {start_time}")
    print(f"Book:  {book_name}")
    print(f"Team:  {team}")
    print(f"Price: {price} (target >= {TARGET_MIN_PRICE})")
    print("=" * 70)
    print()


def main() -> None:
    try:
        api_key = get_api_key()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    print(f"Running price watcher for {SPORT_KEY}...")
    print(f"Team:   {TARGET_TEAM}")
    print(f"Market: {TARGET_MARKET}")
    print(f"Books:  {', '.join(TARGET_BOOKMAKER_KEYS)}")
    print(f"Target: price >= {TARGET_MIN_PRICE}")
    print(f"Regions: {REGIONS}")
    print(f"Polling every {CHECK_INTERVAL_SECONDS} seconds.\n")

    already_alerted: Set[str] = set()

    while True:
        try:
            events = fetch_odds_for_sport(
                api_key=api_key,
                sport_key=SPORT_KEY,
                markets=TARGET_MARKET,
                regions=REGIONS,
                bookmaker_keys=TARGET_BOOKMAKER_KEYS,
            )
        except requests.HTTPError as http_err:
            print(
                f"[ERROR] HTTP error: {http_err} "
                f"(status {http_err.response.status_code})",
                file=sys.stderr,
            )
            time.sleep(CHECK_INTERVAL_SECONDS * 2)
            continue
        except Exception as e:
            print(f"[ERROR] Fetching odds failed: {e}", file=sys.stderr)
            time.sleep(CHECK_INTERVAL_SECONDS * 2)
            continue

        # 1) Always show current prices snapshot (if enabled)
        if SHOW_CURRENT_ODDS:
            print_current_team_prices(
                events,
                team_name=TARGET_TEAM,
                bookmaker_keys=TARGET_BOOKMAKER_KEYS,
                market_key=TARGET_MARKET,
            )

        # 2) Check for alert conditions
        alerts = find_alerts_for_team(
            events,
            team_name=TARGET_TEAM,
            min_price=TARGET_MIN_PRICE,
            bookmaker_keys=TARGET_BOOKMAKER_KEYS,
            market_key=TARGET_MARKET,
            already_alerted=already_alerted,
        )

        if alerts:
            for alert in alerts:
                notify_console(alert)
        else:
            # If we're already printing snapshots, no need to spam extra lines.
            if not SHOW_CURRENT_ODDS:
                print(
                    f"No qualifying prices yet for {TARGET_TEAM} "
                    f"(checking again soon)."
                )

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
