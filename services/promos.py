"""Promo aggregation helpers for DraftKings and FanDuel.

This module tries to fetch live promotions from public sportsbook feeds. When
the network blocks those requests (common in CI) it falls back to a predictable
schedule-based set of promos so the UI always has something useful to show.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests
from requests import RequestException

from utils.formatting import format_start_time_est

PromoDict = Dict[str, Optional[str]]


PROMO_SOURCES: List[Dict[str, str]] = [
    {
        "sportsbook": "DraftKings",
        "url": "https://sportsbook.draftkings.com/sites/US-SB/api/v1/promotions?format=json",
        "source_label": "DraftKings promotions API",
    },
    {
        "sportsbook": "FanDuel",
        "url": "https://sportsbook.fanduel.com/cache/promotions/all/all-promos.json",
        "source_label": "FanDuel promotions feed",
    },
]


def _flatten_promos_from_json(data: object, sportsbook: str) -> List[PromoDict]:
    """Extract promo-like dictionaries from unknown JSON shapes.

    Sportsbooks do not publish a consistent schema for promotions. This helper
    walks the JSON payload and pulls out any objects that have a title-like and
    description-like field so we can at least surface something to the UI.
    """

    promos: List[PromoDict] = []

    if isinstance(data, list):
        for item in data:
            promos.extend(_flatten_promos_from_json(item, sportsbook))
        return promos

    if isinstance(data, dict):
        lowered_keys = {k.lower(): k for k in data}
        title_key = lowered_keys.get("title") or lowered_keys.get("name")
        description_key = lowered_keys.get("description") or lowered_keys.get("shortdescription")

        if title_key and description_key:
            promos.append(
                {
                    "sportsbook": sportsbook,
                    "title": str(data.get(title_key) or "").strip() or f"Promo from {sportsbook}",
                    "description": str(data.get(description_key) or "").strip() or "Details unavailable",
                    "link": data.get("link") or data.get("url"),
                    "source": "live",
                }
            )

        for value in data.values():
            promos.extend(_flatten_promos_from_json(value, sportsbook))

    return promos


def fetch_live_promos() -> Dict[str, List[PromoDict]]:
    """Attempt to pull live promos from sportsbook feeds.

    Returns a dictionary with keys `promos` and `errors`. Each promo dict has a
    `source` value of "live" when it came from an online feed.
    """

    promos: List[PromoDict] = []
    errors: List[str] = []

    for source in PROMO_SOURCES:
        try:
            response = requests.get(source["url"], timeout=5)
            response.raise_for_status()
            data = response.json()
            promos.extend(_flatten_promos_from_json(data, source["sportsbook"]))
        except (RequestException, ValueError) as exc:  # ValueError for JSON decoding
            errors.append(f"{source['sportsbook']}: {exc}")

    # Deduplicate by sportsbook/title
    seen_keys = set()
    unique_promos: List[PromoDict] = []
    for promo in promos:
        key = (promo.get("sportsbook"), promo.get("title"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_promos.append(promo)

    return {"promos": unique_promos, "errors": errors}


def _format_date_range(start: datetime, duration_hours: int = 24) -> Dict[str, str]:
    end = start + timedelta(hours=duration_hours)
    return {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "window": f"{format_start_time_est(start.isoformat())} – {format_start_time_est(end.isoformat())}",
    }


def build_schedule_based_promos(today: Optional[date] = None) -> List[PromoDict]:
    """Generate schedule-driven promos when live feeds fail.

    Uses common promo patterns: football same-game parlay boosts on NFL game
    days and NBA profit boosts mid-week.
    """

    now = datetime.now(timezone.utc)
    resolved_day = today or now.date()
    weekday = resolved_day.weekday()  # Monday == 0

    promos: List[PromoDict] = []

    football_days = {0, 3, 6}  # Monday, Thursday, Sunday
    if weekday in football_days:
        range_info = _format_date_range(now, duration_hours=18)
        promos.append(
            {
                "sportsbook": "DraftKings",
                "title": "NFL 3-Leg SGP Token",
                "description": "Build a 3+ leg same-game parlay for tonight's NFL slate and receive a 20% boost token.",
                "start_time": range_info["start_time"],
                "end_time": range_info["end_time"],
                "source": "schedule",
                "link": "https://sportsbook.draftkings.com/",
            }
        )
        promos.append(
            {
                "sportsbook": "FanDuel",
                "title": "No Sweat NFL SGP",
                "description": "Place a 3-leg+ SGP on tonight's football game and get a bonus bet back on a loss (opt-in required).",
                "start_time": range_info["start_time"],
                "end_time": range_info["end_time"],
                "source": "schedule",
                "link": "https://sportsbook.fanduel.com/promotions",
            }
        )

    if weekday in {1, 2}:  # Tuesday or Wednesday
        range_info = _format_date_range(now, duration_hours=20)
        promos.append(
            {
                "sportsbook": "DraftKings",
                "title": "NBA Profit Boost",
                "description": "20-25% boost token for any NBA bet, commonly active mid-week.",
                "start_time": range_info["start_time"],
                "end_time": range_info["end_time"],
                "source": "schedule",
                "link": "https://sportsbook.draftkings.com/promotions",
            }
        )
        promos.append(
            {
                "sportsbook": "FanDuel",
                "title": "NBA Same-Game Profit Boost",
                "description": "Stack NBA legs with a mid-week 20% boost token; often capped at +4000 odds.",
                "start_time": range_info["start_time"],
                "end_time": range_info["end_time"],
                "source": "schedule",
                "link": "https://sportsbook.fanduel.com/promotions",
            }
        )

    # Weekend catch-all boost
    if weekday == 5:  # Saturday
        range_info = _format_date_range(now, duration_hours=24)
        promos.append(
            {
                "sportsbook": "DraftKings",
                "title": "Weekend Parlay Surge",
                "description": "Opt-in parlay profit boost for any 3+ leg ticket across college and pro games.",
                "start_time": range_info["start_time"],
                "end_time": range_info["end_time"],
                "source": "schedule",
                "link": "https://sportsbook.draftkings.com/",
            }
        )

    return promos


def get_promotions(today: Optional[date] = None) -> Dict[str, object]:
    """Return promotions from live feeds when possible, otherwise a schedule.

    The response mirrors what the API returns so callers can expose whether
    fallback data was needed.
    """

    live_result = fetch_live_promos()
    promos = live_result["promos"]
    used_fallback = False

    if not promos:
        promos = build_schedule_based_promos(today=today)
        used_fallback = True

    return {
        "promos": promos,
        "errors": live_result["errors"],
        "used_fallback": used_fallback,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

