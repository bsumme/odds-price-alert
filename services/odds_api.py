"""The Odds API client wrapper."""

import os
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
    return response.json()



