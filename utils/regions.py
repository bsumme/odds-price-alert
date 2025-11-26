"""Region computation utilities for The Odds API."""

from typing import List, Set


def compute_regions_for_books(bookmaker_keys: List[str]) -> str:
    """
    Decide which regions to request based on which books you're tracking.

    - DraftKings / FanDuel live in "us"
    - Fliff lives in "us2"
    - Novig lives in "us_ex"
    """
    regions: Set[str] = set()
    for bk in bookmaker_keys:
        if bk in ("draftkings", "fanduel"):
            regions.add("us")
        elif bk == "fliff":
            regions.add("us2")
        elif bk == "novig":
            regions.add("us_ex")
        else:
            regions.add("us")

    return ",".join(sorted(regions))



