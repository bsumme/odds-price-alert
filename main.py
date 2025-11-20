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
    sport: str
    events_count: int
    plays: List[ValuePlayOutcome]


class ThreeLegParlayLeg(BaseModel):
    event_id: str
    matchup: str
    outcome_name: str
    point: Optional[float]
    book_price: int
    novig_price: int
    ev_percent: float


class ThreeLegParlayResponse(BaseModel):
    target_book: str
    sport: str
    legs: List[ThreeLegParlayLeg]
    combined_decimal_odds: float
    combined_implied_prob: float
    combined_sharp_prob: float
    estimated_parlay_ev_percent: float


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
            "THE_ODDS_API_KEY environment variable is not set. "
            "Set it in Windows Environment Variables or a .env file."
        )
    return api_key


def get_novig_region_for_sport(sport_key: str) -> str:
    """
    Pick the region to use for 'novig' based on sport.

    - NBA: "us" (they're US-facing)
    - NFL: "us"
    - default: "us"
    """
    # You could customize if Novig ever expands to other regions per sport.
    return "us"


def get_regions_for_target_book(
    target_book: str,
    include_novig: bool,
    sport_key: str,
) -> str:
    """
    Returns a comma-separated 'regions' string for The Odds API call.
    We rely on region selection to decide where each bookmaker shows up.

    For example:
      - For DraftKings: "us"
      - For FanDuel: "us"
      - For Novig: "us"
    """
    regions: Set[str] = set()

    # We'll assume the user is in the US for these books; adjust if needed.
    # The Odds API docs describe valid regions: "us", "us2", "eu", "uk", "au", etc.
    regions.add("us")

    if include_novig:
        novig_region = get_novig_region_for_sport(sport_key)
        regions.add(novig_region)

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
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
        "bookmakers": ",".join(bookmaker_keys),
    }
    if include_player_props:
        # Some sports might let you add "player_props" flags or additional markets.
        # For now, we rely on the 'markets' param, e.g. "player_points".
        pass

    url = f"{BASE_URL}/sports/{sport_key}/odds"
    response = requests.get(url, params=params, timeout=15)
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Error from The Odds API: {response.status_code}, {response.text}",
        )
    return response.json()


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


def points_match(
    book_point: Optional[float],
    novig_point: Optional[float],
    allow_half_point_flex: bool,
) -> bool:
    """Determine if two points should be treated as matching.

    For most markets we require an exact match (including both being ``None``).
    For spreads/totals, The Odds API occasionally publishes a 0.5-point
    difference between Novig and the target book; when ``allow_half_point_flex``
    is True we still consider those to be a match.
    """

    if book_point is None or novig_point is None:
        return book_point == novig_point

    diff = abs(book_point - novig_point)
    if diff < 1e-9:
        return True

    if allow_half_point_flex and diff <= 0.5 + 1e-9:
        return True

    return False


def find_best_novig_outcome(
    *,
    outcomes: List[Dict[str, Any]],
    name: str,
    point: Optional[float],
    allow_half_point_flex: bool,
    opposite: bool = False,
) -> Optional[Dict[str, Any]]:
    """Return the Novig outcome that best matches a book outcome.

    When ``opposite`` is True, search for an outcome with a different name (the
    other side of the bet). Preference is given to exact point matches, but for
    spreads/totals we will also accept lines that differ by up to 0.5.
    """

    best: Optional[Dict[str, Any]] = None
    best_diff: float = float("inf")

    for novig_outcome in outcomes:
        novig_name = novig_outcome.get("name")
        if opposite:
            if novig_name == name:
                continue
        elif novig_name != name:
            continue

        novig_point = novig_outcome.get("point", None)
        if not points_match(point, novig_point, allow_half_point_flex):
            continue

        diff = abs((point or 0.0) - (novig_point or 0.0))
        if diff < best_diff:
            best = novig_outcome
            best_diff = diff

            # Exact point match is the best we can do
            if diff < 1e-9:
                break

    return best


def collect_value_plays(
    events: List[Dict[str, Any]],
    market_key: str,
    target_book: str,
) -> List[ValuePlayOutcome]:
    """
    Scan all events and outcomes in the given market, comparing target_book vs Novig.
    Only considers outcomes where:
      - both books have a price,
      - and for spreads/totals/props, the points match (within 0.5 for spreads/totals).

    Also:
      - Finds the *other* Novig outcome (matching or close point, different name)
        and exposes its true odds + team name as "novig_reverse_*" (hedge side).
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

        # Allow 0.5-point flex for both spreads and totals (Odds API sometimes
        # differs by 0.5 between books).
        allow_half_point_flex = market_key in ("totals", "spreads")

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
            novig_outcomes.append(
                {"name": name, "price": price, "point": point}
            )

        if not novig_outcomes:
            continue

        for o in book_market.get("outcomes", []):
            name = o.get("name")
            price = o.get("price")
            point = o.get("point", None)
            if name is None or price is None:
                continue
            if abs(price) >= MAX_VALID_AMERICAN_ODDS:
                continue

            matching_novig = find_best_novig_outcome(
                outcomes=novig_outcomes,
                name=name,
                point=point,
                allow_half_point_flex=allow_half_point_flex,
            )
            if matching_novig is None:
                continue

            novig_price = matching_novig["price"]
            ev_pct = estimate_ev_percent(book_odds=price, sharp_odds=novig_price)

            # Find the *other* Novig side (hedge side) with matching/close point
            other_novig = find_best_novig_outcome(
                outcomes=novig_outcomes,
                name=name,
                point=point,
                allow_half_point_flex=allow_half_point_flex,
                opposite=True,
            )

            novig_reverse_name: Optional[str] = None
            novig_reverse_price: Optional[int] = None
            hedge_ev_percent: Optional[float] = None
            is_arbitrage = False
            arb_margin_percent: Optional[float] = None

            if other_novig is not None:
                novig_reverse_name = other_novig.get("name")
                novig_reverse_price = other_novig.get("price")
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
                    is_arbitrage = True
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
                    is_arbitrage=is_arbitrage,
                    arb_margin_percent=arb_margin_percent,
                )
            )

    return plays


def choose_three_leg_parlay(
    plays: List[ValuePlayOutcome],
    target_book: str,
    sport_key: str,
) -> ThreeLegParlayResponse:
    """
    Very simple heuristic:
      - sort by EV descending
      - pick the top 3 that don't share the same event_id
    Then approximate parlay EV using Novig's implied probabilities.
    """
    # Sort by single-leg EV
    sorted_plays = sorted(plays, key=lambda p: p.ev_percent, reverse=True)

    chosen: List[ValuePlayOutcome] = []
    used_events: Set[str] = set()

    for p in sorted_plays:
        if len(chosen) >= 3:
            break
        if p.event_id in used_events:
            continue
        chosen.append(p)
        used_events.add(p.event_id)

    if len(chosen) < 3:
        # Not enough distinct events to form a 3-leg parlay
        return ThreeLegParlayResponse(
            target_book=target_book,
            sport=sport_key,
            legs=[],
            combined_decimal_odds=0.0,
            combined_implied_prob=0.0,
            combined_sharp_prob=0.0,
            estimated_parlay_ev_percent=0.0,
        )

    # Build leg details
    legs: List[ThreeLegParlayLeg] = []
    combined_decimal = 1.0
    combined_implied_prob = 1.0
    combined_sharp_prob = 1.0

    for leg in chosen:
        # Book decimal odds
        d_book = american_to_decimal(leg.book_price)
        combined_decimal *= d_book

        # Book implied probability
        p_book = american_to_prob(leg.book_price)
        combined_implied_prob *= p_book

        # "Sharp" probability from Novig
        p_sharp = american_to_prob(leg.novig_price)
        combined_sharp_prob *= p_sharp

        legs.append(
            ThreeLegParlayLeg(
                event_id=leg.event_id,
                matchup=leg.matchup,
                outcome_name=leg.outcome_name,
                point=leg.point,
                book_price=leg.book_price,
                novig_price=leg.novig_price,
                ev_percent=leg.ev_percent,
            )
        )

    # Approximate EV% of the parlay:
    #
    #   EV_parlay% ≈ (combined_decimal * combined_sharp_prob - 1) * 100
    #
    parlay_ev = combined_decimal * combined_sharp_prob - 1.0
    parlay_ev_percent = parlay_ev * 100.0

    return ThreeLegParlayResponse(
        target_book=target_book,
        sport=sport_key,
        legs=legs,
        combined_decimal_odds=combined_decimal,
        combined_implied_prob=combined_implied_prob,
        combined_sharp_prob=combined_sharp_prob,
        estimated_parlay_ev_percent=parlay_ev_percent,
    )


# -------------------------------------------------------------------
# FastAPI app
# -------------------------------------------------------------------

app = FastAPI()


@app.get("/health")
def health_check():
    return {"status": "ok"}


def parse_start_time(start_time: Optional[str]) -> Optional[str]:
    """
    Normalize start_time to a readable ISO8601 or None.
    The Odds API typically returns a string like "2025-11-20T20:00:00Z".
    """
    if not start_time:
        return None
    try:
        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        # Optionally convert to local timezone; for now we'll leave it in UTC.
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return start_time


def collect_all_markets(
    api_key: str,
    sport_key: str,
    target_book: str,
    include_player_props: bool = False,
) -> List[Dict[str, Any]]:
    """
    Fetch both base markets (h2h, spreads, totals) and optionally some props
    in one unified structure.

    Right now we use a single call with multiple markets; if The Odds API
    requires separate calls for props, you could extend this logic.
    """
    include_novig = True
    regions = get_regions_for_target_book(target_book, include_novig, sport_key)

    # We'll request multiple markets at once; The Odds API supports comma-separated.
    # E.g. "h2h,spreads,totals,player_points" for NBA.
    base_markets = ["h2h", "spreads", "totals"]
    all_markets = list(base_markets)
    if include_player_props:
        all_markets.append("player_points")

    markets_str = ",".join(all_markets)

    bookmaker_keys = [target_book, "novig"]

    events = fetch_odds(
        api_key=api_key,
        sport_key=sport_key,
        regions=regions,
        markets=markets_str,
        bookmaker_keys=bookmaker_keys,
        include_player_props=include_player_props,
    )
    return events


def collect_value_plays_for_sport(
    sport_key: str,
    target_book: str,
    include_player_props: bool = False,
) -> Dict[str, List[ValuePlayOutcome]]:
    """
    Fetches all relevant markets for the given sport and target book, then
    collects value plays per market.
    """
    api_key = get_api_key()
    events = collect_all_markets(
        api_key=api_key,
        sport_key=sport_key,
        target_book=target_book,
        include_player_props=include_player_props,
    )

    # Partition markets
    market_to_plays: Dict[str, List[ValuePlayOutcome]] = {
        "h2h": [],
        "spreads": [],
        "totals": [],
        "player_points": [],
    }

    # Because events from The Odds API come with multiple markets per event,
    # we reuse the same event list; each call to collect_value_plays filters
    # out just the market we care about.
    base_markets = ["h2h", "spreads", "totals"]
    for mk in base_markets:
        mk_plays = collect_value_plays(events, mk, target_book)
        # Normalize start_time
        for p in mk_plays:
            p.start_time = parse_start_time(p.start_time)
        market_to_plays[mk] = mk_plays

    if include_player_props:
        # If the provider's sports list uses "player_points" as the market key:
        props_plays = collect_value_plays(events, "player_points", target_book)
        for p in props_plays:
            p.start_time = parse_start_time(p.start_time)
        market_to_plays["player_points"] = props_plays

    return market_to_plays


@app.get("/value-plays/{sport_key}/{target_book}", response_model=ValuePlaysResponse)
def get_value_plays(
    sport_key: str,
    target_book: str,
    market: str = "h2h",  # e.g. "h2h", "spreads", "totals", "player_points"
    include_player_props: bool = False,
):
    """
    Return a list of value plays for a single market + book.
    """
    if target_book not in BOOK_LABELS:
        raise HTTPException(status_code=400, detail="Unsupported target_book")

    market_to_plays = collect_value_plays_for_sport(
        sport_key=sport_key,
        target_book=target_book,
        include_player_props=include_player_props,
    )

    if market not in market_to_plays:
        raise HTTPException(status_code=400, detail="Unsupported market")

    plays = market_to_plays[market]

    return ValuePlaysResponse(
        target_book=target_book,
        market=market,
        sport=sport_key,
        events_count=len(plays),
        plays=plays,
    )


@app.get(
    "/best-3-leg-parlay/{sport_key}/{target_book}",
    response_model=ThreeLegParlayResponse,
)
def get_best_three_leg_parlay(
    sport_key: str,
    target_book: str,
    include_player_props: bool = False,
):
    """
    Build a naive 3-leg parlay suggestion based on highest single-leg EVs
    (one leg per event), then approximate parlay EV vs Novig.
    """
    if target_book not in BOOK_LABELS:
        raise HTTPException(status_code=400, detail="Unsupported target_book")

    market_to_plays = collect_value_plays_for_sport(
        sport_key=sport_key,
        target_book=target_book,
        include_player_props=include_player_props,
    )

    # Flatten all markets into a single list for parlay selection.
    all_plays: List[ValuePlayOutcome] = []
    for mk_plays in market_to_plays.values():
        all_plays.extend(mk_plays)

    parlay = choose_three_leg_parlay(
        plays=all_plays,
        target_book=target_book,
        sport_key=sport_key,
    )
    return parlay


# -------------------------------------------------------------------
# Simple endpoint for date filtering and examples
# -------------------------------------------------------------------


class ExampleValuePlay(BaseModel):
    matchup: str
    outcome_name: str
    price: int
    start_time: Optional[str]


class ExampleValuePlaysResponse(BaseModel):
    plays: List[ExampleValuePlay]


def extract_team_games(
    events: List[Dict[str, Any]],
    team_name: str,
    market_key: str,
    target_book: str,
) -> List[ExampleValuePlay]:
    """
    Example utility that filters events for a given team in a given market
    and returns simplified data. Not used by the main value-plays endpoints,
    but shows how you could build custom filters.
    """
    results: List[ExampleValuePlay] = []

    for event in events:
        home = event.get("home_team")
        away = event.get("away_team")
        start_time = event.get("commence_time")
        event_id = event.get("id", "")

        matchup = f"{away} @ {home}" if home and away else ""

        book_market = None
        for bookmaker in event.get("bookmakers", []):
            key = bookmaker.get("key")
            market = next(
                (m for m in bookmaker.get("markets", []) if m.get("key") == market_key),
                None,
            )
            if not market:
                continue
            if key == target_book:
                book_market = market

        if not book_market:
            continue

        for o in book_market.get("outcomes", []):
            name = o.get("name")
            price = o.get("price")
            if not name or price is None:
                continue
            if team_name.lower() in name.lower():
                results.append(
                    ExampleValuePlay(
                        matchup=matchup,
                        outcome_name=name,
                        price=price,
                        start_time=parse_start_time(start_time),
                    )
                )
    return results


@app.get(
    "/examples/team-games/{sport_key}/{target_book}",
    response_model=ExampleValuePlaysResponse,
)
def get_team_games_example(
    sport_key: str,
    target_book: str,
    team_name: str,
    market: str = "h2h",
    include_player_props: bool = False,
):
    """
    Example endpoint: list all games for a given team and market.
    """
    if target_book not in BOOK_LABELS:
        raise HTTPException(status_code=400, detail="Unsupported target_book")

    api_key = get_api_key()
    include_novig = False
    regions = get_regions_for_target_book(target_book, include_novig, sport_key)
    bookmaker_keys = [target_book]

    events = fetch_odds(
        api_key=api_key,
        sport_key=sport_key,
        regions=regions,
        markets=market,
        bookmaker_keys=bookmaker_keys,
        include_player_props=include_player_props,
    )

    plays = extract_team_games(events, team_name, market, target_book)
    return ExampleValuePlaysResponse(plays=plays)


# -------------------------------------------------------------------
# Static file serving for frontend
# -------------------------------------------------------------------

# Static frontend (index.html, value.html, etc. under ./frontend)
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
