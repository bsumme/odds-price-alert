"""The Odds API client wrapper."""

import json
import os
from datetime import datetime
from typing import List, Dict, Any

import requests
from fastapi import HTTPException

BASE_URL = "https://api.the-odds-api.com/v4"


def get_api_key() -> str:
    """Get The Odds API key from environment variable."""
    api_key = os.getenv("THE_ODDS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing THE_ODDS_API_KEY environment variable. "
            "Set it in Windows Environment Variables and restart."
        )
    return api_key


def _log_real_api_response(
    sport_key: str,
    regions: str,
    markets: str,
    bookmaker_keys: List[str],
    payload: List[Dict[str, Any]],
    endpoint: str = "odds",
) -> None:
    """
    Append the real API response to a local text file so it can be
    compared to dummy data later. Failures here should never break
    the main request flow.
    """
    try:
        # Store under project_root/logs so it's easy to find.
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logs_dir = os.path.join(base_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)

        log_path = os.path.join(logs_dir, "real_odds_api_responses.jsonl")

        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "sport_key": sport_key,
            "regions": regions,
            "markets": markets,
            "bookmaker_keys": bookmaker_keys,
            "endpoint": endpoint,
            "response": payload,
        }

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record))
            f.write("\n")
    except Exception:
        # Silent failure – logging should not impact live behavior.
        pass


def fetch_odds(
    api_key: str,
    sport_key: str,
    regions: str,
    markets: str,
    bookmaker_keys: List[str],
    use_dummy_data: bool = False,
    dummy_data_generator=None,
) -> List[Dict[str, Any]]:
    """
    Core call to /v4/sports/{sport_key}/odds.
    If use_dummy_data is True, uses dummy_data_generator if provided.
    """
    if use_dummy_data and dummy_data_generator:
        return dummy_data_generator(sport_key, markets, bookmaker_keys)

    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
        "bookmakers": ",".join(bookmaker_keys),
    }

    url = f"{BASE_URL}/sports/{sport_key}/odds"
    response = requests.get(url, params=params, timeout=15)
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Error from The Odds API: {response.status_code}, {response.text}",
        )

    data: List[Dict[str, Any]] = response.json()

    # Persist real API output to a text file for later comparison to dummy data.
    _log_real_api_response(
        sport_key=sport_key,
        regions=regions,
        markets=markets,
        bookmaker_keys=bookmaker_keys,
        payload=data,
    )

    return data


def fetch_player_props(
    api_key: str,
    sport_key: str,
    regions: str,
    markets: str,
    bookmaker_keys: List[str],
    use_dummy_data: bool = False,
    dummy_data_generator=None,
) -> List[Dict[str, Any]]:
    """
    Call the dedicated player props endpoint (/v4/sports/{sport_key}/player_props).

    Player prop markets (e.g., player_points, player_assists) are not supported by the
    standard odds endpoint and must use this route instead.
    """
    if use_dummy_data and dummy_data_generator:
        return dummy_data_generator(sport_key, markets, bookmaker_keys)

    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
        "bookmakers": ",".join(bookmaker_keys),
    }

    url = f"{BASE_URL}/sports/{sport_key}/player_props"
    response = requests.get(url, params=params, timeout=15)
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Error from The Odds API: {response.status_code}, {response.text}",
        )

    data: List[Dict[str, Any]] = response.json()

    _log_real_api_response(
        sport_key=sport_key,
        regions=regions,
        markets=markets,
        bookmaker_keys=bookmaker_keys,
        payload=data,
        endpoint="player_props",
    )

    return data






