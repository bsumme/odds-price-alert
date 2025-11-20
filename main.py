import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Set, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_URL = "https://api.the-odds-api.com/v4"

# Treat absurdly large American odds as invalid (e.g. -100000 from Novig)
MAX_VALID_AMERICAN_ODDS = 10000

# -------------------------------------------------------------------
# Shared models and utilities
# -------------------------------------------------------------------


class Bet(BaseModel):
    team_name: str
    target_odds: int  # e.g. -290 or +120
    bookmaker_keys: List[str]  # ["draftkings", "fanduel", "fliff"]


class OddsRequest(BaseModel):
    bets: List[Bet]
    sport_key: str = "basketball_nba"  # default to NBA


class PriceOut(BaseModel):
    bookmaker_key: str
    bookmaker_name: str
    price: Optional[int]


class GameOut(BaseModel):
    matchup: str
    start_time: Optional[str]
    prices: List[PriceOut]
    best_bookmaker_key: Optional[str]
    best_bookmaker_name: Optional[str]
    best_price: Optional[int]


class BetOut(BaseModel):
    team_name: str
    target_odds: int
    games: List[GameOut]


class OddsResponse(BaseModel):
    bets: List[BetOut]


# ---- Models for value-plays endpoint ---------------------------------------


class ValuePlaysRequest(BaseModel):
    sport_key: str = "basketball_nba"   # e.g. "basketball_nba", "americanfootball_nfl"
    market: str = "h2h"                 # e.g. "h2h", "spreads", "totals", "player_points"
    target_book: str                    # e.g. "draftkings", "fanduel", "fliff"
    include_sgp: bool = False           # if True, also suggest a 3-leg parlay
    max_results: int = 7               # number of top value plays to return


class ValuePlayOutcome(BaseModel):
    event_id: str
    matchup: str
    start_time: Optional[str]
    outcome_name: str        # e.g. "New York Knicks" or "LeBron James"
    point: Optional[float]   # spread/total/prop line (if applicable)
    novig_price: int
    novig_reverse_name: Optional[str]
    novig_reverse_price: Optional[int]
    book_price: int
    ev_percent: float        # estimated edge in percent (vs Novig)
    hedge_ev_percent: Optional[float] = None  # edge vs Novig opposite side, if available
    is_arbitrage: bool = False
    arb_margin_percent: Optional[float] = None  # % margin of arb if present


class ValuePlaysResponse(BaseModel):
    target_book: str
    market: str
    plays: List[ValuePlayOutcome]
    sgp_suggestion: Optional[Dict[str, Any]] = None  # holds 3-leg parlay suggestion


BOOK_LABELS = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "novig": "Novig",
    "fliff": "Fliff",
    # add more as needed
}


def get_api_key() -> str:
    api_key = os.getenv("THE_ODDS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing THE_ODDS_API_KEY environment variable. "
            "Set it in Windows Environment Variables and restart."
        )
    return api_key


def pretty_book_label(book_key: str) -> str:
    return BOOK_LABELS.get(book_key, book_key)


def compute_regions_for_books(bookmaker_keys: List[str]) -> str:
    """
    Decide which regions to request based on which books you're tracking.

    - DraftKings / FanDuel live in "us"
    - Fliff lives in "us2"
    - Novig lives in "us_ex"
    """
    regions: Set[str] = set()

    if any(b in ("draftkings", "fanduel") for b in bookmaker_keys):
        regions.add("us")
    if "fliff" in bookmaker_keys:
        regions.add("us2")
    if "novig" in bookmaker_keys:
        regions.add("us_ex")

    if not regions:
        regions.add("us")

    return ",".join(sorted(regions))


def fetch_odds(
    api_key: str,
    sport_key: str,
    regions: str,
    markets: str,
    bookmaker_keys: List[str],
    include_player_props: bool = False,
) -> List[Dict[str, Any]]:
    """
    Core call to /v4/sports/{sport_key}/odds.
    """
    url = f"{BASE_URL}/sports/{sport_key}/odds"
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
        "dateFormat": "iso",
        "bookmakers": ",".join(bookmaker_keys),
    }
    if include_player_props:
       # Explicitly opt-in to player prop markets (required by The Odds API).
       params["playerProps"] = "true"
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def is_live_event(event: Dict[str, Any]) -> bool:
    """Return True if the event appears to be in-play/live.

    The Odds API exposes several hints for live games, including:
      - a truthy "scores" array
      - boolean flags such as "inplay" or "live"
      - a "completed" flag once the game has finished
      - a start time that has already passed
    """

    if event.get("completed"):
        return True

    if event.get("scores"):
        return True

    if event.get("inplay") or event.get("live"):
        return True

    commence_time = event.get("commence_time")
    if commence_time:
        try:
            start_dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
            now_utc = datetime.now(timezone.utc)

            # Treat games as effectively live if their scheduled start time has passed
            # or is within a 15-minute buffer window. This helps catch cases where the
            # Odds API lags behind the real game state.
            buffer = timedelta(minutes=15)
            if start_dt <= now_utc + buffer:
                return True
        except ValueError:
            # If the time is malformed, assume not started rather than failing.
            pass

    return False


# -------------------------------------------------------------------
# Helper logic for watcher (/api/odds)
# -------------------------------------------------------------------


def extract_team_games(
    events: List[Dict[str, Any]],
    team_name: str,
    bookmaker_keys: List[str],
    market_key: str = "h2h",
) -> List[GameOut]:
    """
    For each event involving `team_name`, collect that team's prices at
    the selected books and compute the best price.
    """
    games: List[GameOut] = []

    for event in events:
        home = event.get("home_team")
        away = event.get("away_team")
        start_time = event.get("commence_time")

        if team_name not in (home, away):
            continue

        prices_for_game: List[PriceOut] = []
        raw_price_map: Dict[str, Optional[int]] = {}

        for bookmaker in event.get("bookmakers", []):
            book_key = bookmaker.get("key")
            if book_key not in bookmaker_keys:
                continue

            market = next(
                (m for m in bookmaker.get("markets", []) if m.get("key") == market_key),
                None,
            )
            if not market:
                raw_price_map[book_key] = None
                prices_for_game.append(
                    PriceOut(
                        bookmaker_key=book_key,
                        bookmaker_name=pretty_book_label(book_key),
                        price=None,
                    )
                )
                continue

            price_for_team: Optional[int] = None
            for outcome in market.get("outcomes", []):
                if outcome.get("name") == team_name:
                    price_for_team = outcome.get("price")
                    break

            raw_price_map[book_key] = price_for_team
            prices_for_game.append(
                PriceOut(
                    bookmaker_key=book_key,
                    bookmaker_name=pretty_book_label(book_key),
                    price=price_for_team,
                )
            )

        # Compute best price
        valid_prices = [
            (bk, p)
            for bk, p in raw_price_map.items()
            if p is not None
        ]
        if valid_prices:
            best_book_key, best_price = max(valid_prices, key=lambda x: x[1])
            best_book_name = pretty_book_label(best_book_key)
        else:
            best_book_key = best_book_name = None
            best_price = None

        matchup = f"{away} @ {home}" if home and away else ""

        games.append(
            GameOut(
                matchup=matchup,
                start_time=start_time,
                prices=prices_for_game,
                best_bookmaker_key=best_book_key,
                best_bookmaker_name=best_book_name,
                best_price=best_price,
            )
        )

    return games


# -------------------------------------------------------------------
# Helper logic for value plays vs Novig
# -------------------------------------------------------------------


def american_to_decimal(odds: int) -> float:
    """
    Convert American odds to decimal odds.
    """
    if odds > 0:
        return 1.0 + odds / 100.0
    else:
        return 1.0 + 100.0 / abs(odds)


def american_to_prob(odds: int) -> float:
    """
    Convert American odds to implied probability.
    """
    if odds > 0:
        return 100.0 / (odds + 100.0)
    else:
        return abs(odds) / (abs(odds) + 100.0)


def estimate_ev_percent(book_odds: int, sharp_odds: int) -> float:
    """
    Approximate EV% using:
      EV% ~ (decimal_book * sharp_prob - 1) * 100
    where sharp_prob is implied probability from Novig, treated as "true".
    """
    book_dec = american_to_decimal(book_odds)
    sharp_prob = american_to_prob(sharp_odds)
    ev = book_dec * sharp_prob - 1.0
    return ev * 100.0


def collect_value_plays(
    events: List[Dict[str, Any]],
    market_key: str,
    target_book: str,
) -> List[ValuePlayOutcome]:
    """
    Scan all events and outcomes in the given market, comparing target_book vs Novig.
    Only considers outcomes where:
      - both books have a price,
      - and for spreads/totals/props, the points match.

    Also:
      - Finds the *other* Novig outcome (same point, different name) and exposes
        its true odds + team name as "novig_reverse_*" (hedge side).
      - Detects 2-way arbitrage: back this side at the target book, back the
        opposite side at Novig.
    """
    plays: List[ValuePlayOutcome] = []

    for event in events:
        home = event.get("home_team")
        away = event.get("away_team")
        start_time = event.get("commence_time")
        event_id = event.get("id", "")

        matchup = f"{away} @ {home}" if home and away else ""

        novig_market = None
        book_market = None

        for bookmaker in event.get("bookmakers", []):
            key = bookmaker.get("key")
            market = next(
                (m for m in bookmaker.get("markets", []) if m.get("key") == market_key),
                None,
            )
            if not market:
                continue

            if key == "novig":
                novig_market = market
            elif key == target_book:
                book_market = market

        if not novig_market or not book_market:
            continue

        # Build Novig outcome collection and map
        novig_map: Dict[tuple, int] = {}
        novig_outcomes: List[Dict[str, Any]] = []
        for o in novig_market.get("outcomes", []):
            name = o.get("name")
            price = o.get("price")
            point = o.get("point", None)
            if name is None or price is None:
                continue
            if abs(price) >= MAX_VALID_AMERICAN_ODDS:
                # Skip absurd values like -100000
                continue
            key = (name, point)
            novig_map[key] = price
            novig_outcomes.append(
                {"name": name, "price": price, "point": point}
            )

        if not novig_map:
            continue

        for o in book_market.get("outcomes", []):
            name = o.get("name")
            price = o.get("price")
            point = o.get("point", None)
            if name is None or price is None:
                continue
            if abs(price) >= MAX_VALID_AMERICAN_ODDS:
                continue

            key = (name, point)
            if key not in novig_map:
                continue
            novig_price = novig_map[key]
            ev_pct = estimate_ev_percent(book_odds=price, sharp_odds=novig_price)

            # Find the *other* Novig side (hedge side) with same point but different name
            other_novig = None
            for o2 in novig_outcomes:
                if o2["point"] == point and o2["name"] != name:
                    other_novig = o2
                    break

            novig_reverse_name: Optional[str] = None
            novig_reverse_price: Optional[int] = None
            hedge_ev_percent: Optional[float] = None
            is_arb = False
            arb_margin_percent: Optional[float] = None

            if other_novig is not None:
                novig_reverse_name = other_novig["name"]
                novig_reverse_price = other_novig["price"]
                hedge_ev_percent = estimate_ev_percent(
                    book_odds=price, sharp_odds=novig_reverse_price
                )

                # Detect 2-way arbitrage:
                #  - back this side at target_book (book_price)
                #  - back opposite side at Novig (novig_reverse_price)
                d_book = american_to_decimal(price)
                d_novig_other = american_to_decimal(other_novig["price"])
                inv_sum = 1.0 / d_book + 1.0 / d_novig_other
                if inv_sum < 1.0:
                    is_arb = True
                    arb_margin_percent = (1.0 - inv_sum) * 100.0

            plays.append(
                ValuePlayOutcome(
                    event_id=event_id,
                    matchup=matchup,
                    start_time=start_time,
                    outcome_name=name,
                    point=point,
                    novig_price=novig_price,
                    novig_reverse_name=novig_reverse_name,
                    novig_reverse_price=novig_reverse_price,
                    book_price=price,
                    ev_percent=ev_pct,
                    hedge_ev_percent=hedge_ev_percent,
                    is_arbitrage=is_arb,
                    arb_margin_percent=arb_margin_percent,
                )
            )

    return plays


def choose_three_leg_parlay(plays: List[ValuePlayOutcome], target_book: str) -> Optional[Dict[str, Any]]:
    """
    Very simple 3-leg high-EV parlay suggestion:
      - take the top +EV plays (ev_percent > 0),
      - pick the first 3 distinct plays,
      - estimate parlay EV assuming independence.

    This is cross-game by default (not a true "same-game parlay" engine).
    """
    positive_plays = [p for p in plays if p.ev_percent > 0]
    if len(positive_plays) < 3:
        return None

    # Take top 3 by EV%
    positive_plays.sort(key=lambda p: p.ev_percent, reverse=True)
    legs = positive_plays[:3]
    probs = [american_to_prob(leg.book_price) for leg in legs]
    fair_probs = [american_to_prob(leg.novig_price) for leg in legs]

    parlay_prob = 1.0
    fair_parlay_prob = 1.0
    parlay_decimal = 1.0

    for p_book, p_sharp, leg in zip(probs, fair_probs, legs):
        parlay_prob *= p_book
        fair_parlay_prob *= p_sharp
        parlay_decimal *= american_to_decimal(leg.book_price)

    parlay_ev = parlay_decimal * fair_parlay_prob - 1.0  # EV in units of stake
    parlay_ev_percent = parlay_ev * 100.0

    sgp_info = {
        "target_book": target_book,
        "legs": [
            {
                "matchup": leg.matchup,
                "outcome_name": leg.outcome_name,
                "point": leg.point,
                "book_price": leg.book_price,
                "novig_price": leg.novig_price,
                "ev_percent": round(leg.ev_percent, 2),
            }
            for leg in legs
        ],
        "approx_parlay_decimal_odds": round(parlay_decimal, 3),
        "approx_parlay_ev_percent": round(parlay_ev_percent, 2),
    }
    return sgp_info


# -------------------------------------------------------------------
# FastAPI app & endpoints
# -------------------------------------------------------------------

app = FastAPI()


@app.post("/api/odds", response_model=OddsResponse)
def get_odds(payload: OddsRequest) -> OddsResponse:
    """
    Odds endpoint used by the watcher UI: returns current prices and best line
    for specific teams/bets the user is tracking.
    """
    if not payload.bets:
        raise HTTPException(status_code=400, detail="No bets provided")

    try:
        api_key = get_api_key()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    all_book_keys: Set[str] = set()
    for bet in payload.bets:
        all_book_keys.update(bet.bookmaker_keys)

    if not all_book_keys:
        raise HTTPException(status_code=400, detail="No bookmakers specified")

    regions = compute_regions_for_books(list(all_book_keys))

    try:
        events = fetch_odds(
            api_key=api_key,
            sport_key=payload.sport_key,
            regions=regions,
            markets="h2h",
            bookmaker_keys=list(all_book_keys),
        )
    except requests.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Odds API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error fetching odds: {e}")

    events = [event for event in events if not is_live_event(event)]

    bet_outputs: List[BetOut] = []

    for bet in payload.bets:
        games = extract_team_games(events, bet.team_name, bet.bookmaker_keys)
        bet_outputs.append(
            BetOut(
                team_name=bet.team_name,
                target_odds=bet.target_odds,
                games=games,
            )
        )

    return OddsResponse(bets=bet_outputs)


@app.post("/api/value-plays", response_model=ValuePlaysResponse)
def get_value_plays(payload: ValuePlaysRequest) -> ValuePlaysResponse:
    """
    Compare a target sportsbook to Novig (treated as "sharp") for a given sport
    and market, returning the best value plays and an optional 3-leg parlay suggestion.
    """
    target_book = payload.target_book
    market_key = payload.market

    if target_book == "novig":
        raise HTTPException(
            status_code=400,
            detail="Target book cannot be Novig (Novig is the sharp reference).",
        )

    try:
        api_key = get_api_key()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    bookmaker_keys = [target_book, "novig"]
    regions = compute_regions_for_books(bookmaker_keys)

    try:
        events = fetch_odds(
            api_key=api_key,
            sport_key=payload.sport_key,
            regions=regions,
            markets=market_key,
            bookmaker_keys=bookmaker_keys,
            include_player_props=market_key.startswith("player_"),
        )
    except requests.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Odds API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error fetching odds: {e}")

    events = [event for event in events if not is_live_event(event)]

    plays = collect_value_plays(events, market_key, target_book)

    # Sort by EV descending and cap results
    plays.sort(key=lambda p: p.ev_percent, reverse=True)
    top_plays = plays[: payload.max_results]

    sgp_suggestion = None
    if payload.include_sgp and top_plays:
        sgp_suggestion = choose_three_leg_parlay(top_plays, target_book)

    return ValuePlaysResponse(
        target_book=target_book,
        market=market_key,
        plays=top_plays,
        sgp_suggestion=sgp_suggestion,
    )


# Static frontend (index.html, value.html, etc. under ./frontend)
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
