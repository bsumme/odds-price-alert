#!/usr/bin/env python3
"""Minimal CLI helper to fetch odds and print raw API responses for debugging.

This intentionally avoids FastAPI so you can quickly spot issues with totals odds
using plain print statements or a debugger.
"""

import argparse
import json
from typing import List, Dict, Any

from fastapi import HTTPException

from services.odds_api import fetch_odds, get_api_key


DEFAULT_BOOKMAKERS = ["draftkings", "fanduel", "novig", "fliff"]


def print_pretty(events: List[Dict[str, Any]], limit: int) -> None:
    """Print a condensed view of odds to keep debugging output readable."""
    for idx, event in enumerate(events[:limit]):
        home = event.get("home_team", "?")
        away = event.get("away_team", "?")
        start = event.get("commence_time", "?")
        print(f"\n🎯 {away} at {home} — {start}")

        for bookmaker in event.get("bookmakers", []):
            print(f"  🏦 {bookmaker.get('title', bookmaker.get('key', '?'))} ({bookmaker.get('key', '?')})")
            for market in bookmaker.get("markets", []):
                market_key = market.get("key", "?")
                print(f"    • market: {market_key}")
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "?")
                    price = outcome.get("price")
                    point = outcome.get("point")
                    if point is None:
                        print(f"      - {name}: {price}")
                    else:
                        print(f"      - {name} @ {point}: {price}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch odds directly from The Odds API for quick debugging.")
    parser.add_argument("--sport", default="basketball_nba", help="Sport key (e.g. basketball_nba)")
    parser.add_argument(
        "--markets",
        default="totals",
        help="Comma-separated markets to request (default: totals)",
    )
    parser.add_argument(
        "--regions",
        default="us,us2,us_ex",
        help="Comma-separated regions to include (default: us,us2,us_ex)",
    )
    parser.add_argument(
        "--bookmakers",
        default=",".join(DEFAULT_BOOKMAKERS),
        help="Comma-separated bookmaker keys to include",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Limit the number of events to print (default: 5)",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the full JSON response instead of the condensed view",
    )
    parser.add_argument(
        "--use-dummy-data",
        action="store_true",
        help="Use the built-in dummy generator instead of hitting the real API",
    )

    args = parser.parse_args()

    api_key = get_api_key()
    bookmaker_keys = [b.strip() for b in args.bookmakers.split(",") if b.strip()]

    try:
        events = fetch_odds(
            api_key=api_key,
            sport_key=args.sport,
            regions=args.regions,
            markets=args.markets,
            bookmaker_keys=bookmaker_keys,
            use_dummy_data=args.use_dummy_data,
        )
    except HTTPException as exc:  # pragma: no cover - simple CLI helper
        print(f"❌ API returned an error: {exc.detail}")
        return

    if args.raw:
        print(json.dumps(events, indent=2))
    else:
        print_pretty(events, args.limit)

    print("\n✅ Done. Raw response also logged under logs/real_odds_api_responses.jsonl when using real API calls.")


if __name__ == "__main__":
    main()
