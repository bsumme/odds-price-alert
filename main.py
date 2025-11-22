import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Set, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from zoneinfo import ZoneInfo

BASE_URL = "https://api.the-odds-api.com/v4"

# Treat absurdly large American odds as invalid (e.g. -100000 from Novig)
MAX_VALID_AMERICAN_ODDS = 10000

# -------------------------------------------------------------------
# Shared models and utilities
# -------------------------------------------------------------------


class PriceOut(BaseModel):
    bookmaker_key: str
    bookmaker_name: str
    price: Optional[int]  # the best price for that side, if available


class BetRequest(BaseModel):
    """
    Represents a single bet the user cares about in the watcher UI.
    For example: "NBA, spreads, Golden State Warriors -3.5"
    """
    sport_key: str
    market: str  # "h2h", "spreads", "totals", or a prop like "player_points"
    team: str    # for props, this might be a player name instead
    point: Optional[float] = None
    bookmaker_keys: List[str]  # e.g. ["draftkings", "fanduel", "novig"]


class OddsRequest(BaseModel):
    bets: List[BetRequest]


class SingleBetOdds(BaseModel):
    sport_key: str
    market: str
    team: str
    point: Optional[float]
    prices: List[PriceOut]  # one PriceOut per bookmaker we asked for


class OddsResponse(BaseModel):
    bets: List[SingleBetOdds]


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
    ev_percent: float        # estimated edge in percent (vs Novig same side)
    hedge_ev_percent: Optional[float] = None  # legacy: edge vs Novig opposite side (not used for sort)
    is_arbitrage: bool = False
    arb_margin_percent: Optional[float] = None  # % margin of arb if present (book vs Novig opposite)


class ValuePlaysResponse(BaseModel):
    target_book: str
    market: str
    plays: List[ValuePlayOutcome]
    sgp_suggestion: Optional[Dict[str, Any]] = None  # holds 3-leg SGP suggestion if requested


class ValuePlaysRequest(BaseModel):
    """
    Request body for /api/value-plays:
      - sport_key: e.g. "basketball_nba"
      - target_book: e.g. "draftkings"
      - compare_book: e.g. "fanduel" (the book to compare against)
      - market: "h2h", "spreads", "totals", or "player_points"
      - include_sgp: whether to build a naive 3-leg parlay from the top plays
    """
    sport_key: str
    target_book: str
    compare_book: str
    market: str
    include_sgp: bool = False
    max_results: Optional[int] = None


class BestValuePlayOutcome(BaseModel):
    """Extended value play outcome with sport and market info"""
    sport_key: str
    market: str
    event_id: str
    matchup: str
    start_time: Optional[str]
    outcome_name: str
    point: Optional[float]
    novig_price: int
    novig_reverse_name: Optional[str]
    novig_reverse_price: Optional[int]
    book_price: int
    ev_percent: float
    hedge_ev_percent: Optional[float] = None
    is_arbitrage: bool = False
    arb_margin_percent: Optional[float] = None


class BestValuePlaysRequest(BaseModel):
    """
    Request body for /api/best-value-plays:
      - sport_keys: list of sports to search, e.g. ["basketball_nba", "americanfootball_nfl"]
      - markets: list of markets to search, e.g. ["h2h", "spreads", "totals"]
      - target_book: e.g. "draftkings"
      - compare_book: e.g. "novig" (the book to compare against)
      - max_results: maximum number of results to return
    """
    sport_keys: List[str]
    markets: List[str]
    target_book: str
    compare_book: str
    max_results: Optional[int] = 50


class BestValuePlaysResponse(BaseModel):
    target_book: str
    compare_book: str
    plays: List[BestValuePlayOutcome]


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


def fetch_odds(
    api_key: str,
    sport_key: str,
    regions: str,
    markets: str,
    bookmaker_keys: List[str],
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


def find_best_comparison_outcome(
    *,
    outcomes: List[Dict[str, Any]],
    name: str,
    point: Optional[float],
    allow_half_point_flex: bool,
    opposite: bool = False,
) -> Optional[Dict[str, Any]]:
    """Return the comparison book outcome that best matches a target book outcome.

    When ``opposite`` is True, search for an outcome with a different name (the
    other side of the bet). Preference is given to exact point matches, but for
    spreads/totals we will also accept lines that differ by up to 0.5.
    """

    best: Optional[Dict[str, Any]] = None
    best_diff: float = float("inf")

    for comp_outcome in outcomes:
        comp_name = comp_outcome.get("name")
        if opposite:
            if comp_name == name:
                continue
        elif comp_name != name:
            continue

        comp_point = comp_outcome.get("point", None)
        if not points_match(point, comp_point, allow_half_point_flex):
            continue

        diff = abs((point or 0.0) - (comp_point or 0.0))
        if diff < best_diff:
            best = comp_outcome
            best_diff = diff

            # Exact point match is the best we can do
            if diff < 1e-9:
                break

    return best


def collect_value_plays(
    events: List[Dict[str, Any]],
    market_key: str,
    target_book: str,
    compare_book: str,
) -> List[ValuePlayOutcome]:
    """
    Scan all events and outcomes in the given market, comparing target_book vs compare_book.
    Only considers outcomes where:
      - both books have a price,
      - and for spreads/totals/props, the points match (within 0.5 for spreads/totals).

    Also:
      - Finds the *other* comparison book outcome (matching or close point, different name)
        and exposes its true odds + team name as "novig_reverse_*" (hedge side).
      - Detects 2-way arbitrage: back this side at the target book, back the
        opposite side at the comparison book.
    """
    plays: List[ValuePlayOutcome] = []

    # Filter out live events at the event level
    now_utc = datetime.now(timezone.utc)
    
    for event in events:
        home = event.get("home_team")
        away = event.get("away_team")
        start_time = event.get("commence_time")
        event_id = event.get("id", "")

        # Skip events that have already started (live or completed)
        if start_time:
            try:
                event_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                if event_dt <= now_utc:
                    # Event has started or is live, skip it
                    continue
            except Exception:
                # If we can't parse the time, skip to be safe
                continue
        else:
            # No start time, skip to be safe
            continue

        matchup = f"{away} @ {home}" if home and away else ""

        compare_market = None
        book_market = None

        for bookmaker in event.get("bookmakers", []):
            key = bookmaker.get("key")
            market = next(
                (m for m in bookmaker.get("markets", []) if m.get("key") == market_key),
                None,
            )
            if not market:
                continue

            if key == compare_book:
                compare_market = market
            elif key == target_book:
                book_market = market

        if not compare_market or not book_market:
            continue

        # Allow 0.5-point flex for both spreads and totals (Odds API sometimes
        # differs by 0.5 between books).
        allow_half_point_flex = market_key in ("totals", "spreads")

        compare_outcomes: List[Dict[str, Any]] = []
        for o in compare_market.get("outcomes", []):
            name = o.get("name")
            price = o.get("price")
            point = o.get("point", None)
            if name is None or price is None:
                continue
            if abs(price) >= MAX_VALID_AMERICAN_ODDS:
                # Skip absurd values like -100000
                continue
            compare_outcomes.append(
                {"name": name, "price": price, "point": point}
            )

        if not compare_outcomes:
            continue

        for o in book_market.get("outcomes", []):
            name = o.get("name")
            price = o.get("price")
            point = o.get("point", None)
            if name is None or price is None:
                continue
            if abs(price) >= MAX_VALID_AMERICAN_ODDS:
                continue

            matching_compare = find_best_comparison_outcome(
                outcomes=compare_outcomes,
                name=name,
                point=point,
                allow_half_point_flex=allow_half_point_flex,
            )
            if matching_compare is None:
                continue

            compare_price = matching_compare["price"]
            ev_pct = estimate_ev_percent(book_odds=price, sharp_odds=compare_price)

            # Find the *other* comparison book side (hedge side) with matching/close point
            other_compare = find_best_comparison_outcome(
                outcomes=compare_outcomes,
                name=name,
                point=point,
                allow_half_point_flex=allow_half_point_flex,
                opposite=True,
            )

            novig_reverse_name: Optional[str] = None
            novig_reverse_price: Optional[int] = None
            hedge_ev_percent: Optional[float] = None
            is_arb = False
            arb_margin_percent: Optional[float] = None

            if other_compare is not None:
                novig_reverse_name = other_compare.get("name")
                novig_reverse_price = other_compare.get("price")
                hedge_ev_percent = estimate_ev_percent(
                    book_odds=price, sharp_odds=novig_reverse_price
                )

                # 2-way arb math:
                #  - back this side at target_book (book_price)
                #  - back opposite side at comparison book (novig_reverse_price)
                d_book = american_to_decimal(price)
                d_compare_other = american_to_decimal(novig_reverse_price)
                inv_sum = 1.0 / d_book + 1.0 / d_compare_other
                # Hedge margin: 0% ~ fair (e.g. -125 / +125), >0% profitable arb, <0% losing hedge
                arb_margin_percent = (1.0 - inv_sum) * 100.0
                if arb_margin_percent > 0:
                    is_arb = True


            plays.append(
                ValuePlayOutcome(
                    event_id=event_id,
                    matchup=matchup,
                    start_time=start_time,
                    outcome_name=name,
                    point=point,
                    novig_price=compare_price,
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


def format_start_time_est(iso_str: str) -> str:
    """Convert an ISO UTC time string into an easy-to-read EST label.

    Example output: "Thu 11/20 03:30 PM ET".
    If parsing fails, returns the original string.
    """
    try:
        dt_utc = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        dt_et = dt_utc.astimezone(ZoneInfo("America/New_York"))
        return dt_et.strftime("%a %m/%d %I:%M %p ET")
    except Exception:
        return iso_str


def choose_three_leg_parlay(plays: List[ValuePlayOutcome], target_book: str) -> Optional[Dict[str, Any]]:
    """
    Very simple 3-leg high-EV parlay suggestion:
      - take the top +EV plays (ev_percent)
      - ensure all 3 legs come from different events
    """
    if len(plays) < 3:
        return None

    sorted_plays = sorted(plays, key=lambda p: p.ev_percent, reverse=True)

    chosen: List[ValuePlayOutcome] = []
    used_event_ids: Set[str] = set()

    for p in sorted_plays:
        if p.event_id in used_event_ids:
            continue
        chosen.append(p)
        used_event_ids.add(p.event_id)
        if len(chosen) == 3:
            break

    if len(chosen) < 3:
        return None

    decimal_odds_list = [american_to_decimal(p.book_price) for p in chosen]
    combined_decimal = 1.0
    for d in decimal_odds_list:
        combined_decimal *= d

    sharp_probs = [american_to_prob(p.novig_price) for p in chosen]
    combined_sharp_prob = 1.0
    for sp in sharp_probs:
        combined_sharp_prob *= sp

    parlay_ev = combined_decimal * combined_sharp_prob - 1.0
    parlay_ev_percent = parlay_ev * 100.0

    return {
        "target_book": target_book,
        "legs": [
            {
                "event_id": p.event_id,
                "matchup": p.matchup,
                "outcome_name": p.outcome_name,
                "point": p.point,
                "book_price": p.book_price,
                "novig_price": p.novig_price,
                "ev_percent": p.ev_percent,
            }
            for p in chosen
        ],
        "combined_decimal_odds": combined_decimal,
        "combined_sharp_prob": combined_sharp_prob,
        "estimated_parlay_ev_percent": parlay_ev_percent,
        "approx_parlay_decimal_odds": combined_decimal,
        "approx_parlay_ev_percent": parlay_ev_percent,
    }


# -------------------------------------------------------------------
# FastAPI app
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

    all_bets_results: List[SingleBetOdds] = []

    by_sport: Dict[str, List[BetRequest]] = {}
    for bet in payload.bets:
        by_sport.setdefault(bet.sport_key, []).append(bet)

    for sport_key, bets_for_sport in by_sport.items():
        markets = sorted({b.market for b in bets_for_sport})
        bookmaker_keys = sorted({bk for b in bets_for_sport for bk in b.bookmaker_keys})

        events = fetch_odds(
            api_key=api_key,
            sport_key=sport_key,
            regions=regions,
            markets=",".join(markets),
            bookmaker_keys=bookmaker_keys,
        )

        for bet in bets_for_sport:
            prices_per_book: List[PriceOut] = []

            for book_key in bet.bookmaker_keys:
                price_for_team: Optional[int] = None

                for event in events:
                    home = event.get("home_team")
                    away = event.get("away_team")

                    if bet.team not in (home, away):
                        continue

                    book_market = None
                    for bookmaker in event.get("bookmakers", []):
                        if bookmaker.get("key") != book_key:
                            continue
                        book_market = next(
                            (m for m in bookmaker.get("markets", []) if m.get("key") == bet.market),
                            None,
                        )
                        if book_market:
                            break
                    if not book_market:
                        continue

                    for outcome in book_market.get("outcomes", []):
                        name = outcome.get("name")
                        price = outcome.get("price")
                        point = outcome.get("point", None)

                        if name != bet.team:
                            continue

                        if bet.point is not None:
                            if point is None:
                                continue
                            if abs(point - bet.point) > 1e-6:
                                continue

                        if price is None:
                            continue
                        if abs(price) >= MAX_VALID_AMERICAN_ODDS:
                            continue

                        price_for_team = price
                        break

                    if price_for_team is not None:
                        break

                prices_per_book.append(
                    PriceOut(
                        bookmaker_key=book_key,
                        bookmaker_name=pretty_book_label(book_key),
                        price=price_for_team,
                    )
                )

            valid_prices = [
                (bk, p)
                for bk, p in [(po.bookmaker_key, po.price) for po in prices_per_book]
                if p is not None
            ]
            best_price_for_team: Optional[int] = None
            best_book: Optional[str] = None
            if valid_prices:
                best_book, best_price_for_team = max(valid_prices, key=lambda x: american_to_decimal(x[1]))

            for po in prices_per_book:
                if po.price is None and po.bookmaker_key == best_book:
                    po.price = best_price_for_team

            all_bets_results.append(
                SingleBetOdds(
                    sport_key=sport_key,
                    market=bet.market,
                    team=bet.team,
                    point=bet.point,
                    prices=prices_per_book,
                )
            )

    return OddsResponse(bets=all_bets_results)


@app.post("/api/value-plays", response_model=ValuePlaysResponse)
def get_value_plays(payload: ValuePlaysRequest) -> ValuePlaysResponse:
    """
    Compare a target sportsbook to a comparison book for a given sport
    and market, returning the best value plays and an optional 3-leg parlay suggestion.

    Sorting:
      - Primary sort is by hedge opportunity using arb_margin_percent:
          arb_margin_percent = (1 - (1/dec_book + 1/dec_compare_opposite)) * 100
        where dec_book is the decimal odds at the target book, and
        dec_compare_opposite is the decimal odds of the comparison book *opposite* side.
      - A pair like -125 / +125 gives ~0% (fair hedge).
      - Positive values indicate 2-way arbitrage (profitable hedge),
        negative values indicate a losing hedge.
      - Plays with no comparison book opposite side are pushed to the bottom.
    """
    target_book = payload.target_book
    compare_book = payload.compare_book
    market_key = payload.market

    if target_book == compare_book:
        raise HTTPException(
            status_code=400,
            detail="Target book and comparison book cannot be the same.",
        )

    try:
        api_key = get_api_key()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    bookmaker_keys = [target_book, compare_book]
    regions = compute_regions_for_books(bookmaker_keys)

    events = fetch_odds(
        api_key=api_key,
        sport_key=payload.sport_key,
        regions=regions,
        markets=market_key,
        bookmaker_keys=bookmaker_keys,
    )

    raw_plays = collect_value_plays(events, market_key, target_book, compare_book)

    # Filter out live events and games that have already started
    now_utc = datetime.now(timezone.utc)
    filtered_plays: List[ValuePlayOutcome] = []
    for p in raw_plays:
        if not p.start_time:
            # If no start time, exclude it to be safe
            continue
        try:
            dt = datetime.fromisoformat(p.start_time.replace("Z", "+00:00"))
            # Only include games that haven't started yet (start_time is in the future)
            if dt > now_utc:
                filtered_plays.append(p)
        except Exception:
            # If we can't parse the time, exclude it to be safe
            continue

    # Convert start_time into an easy-to-read EST string for display
    for p in filtered_plays:
        if p.start_time:
            p.start_time = format_start_time_est(p.start_time)

    # Sort primarily by hedge opportunity (arb_margin_percent) descending.
    # Plays with no comparison book opposite side get pushed to the bottom.
    def hedge_sort_key(play: ValuePlayOutcome) -> float:
        """
        Sort plays by hedge margin first. Plays without an opposite comparison book side
        get a large negative default so they appear at the bottom.
        """
        if play.arb_margin_percent is not None:
            return play.arb_margin_percent
        # No opposite side: effectively no hedge opportunity.
        return -1_000_000.0 + play.ev_percent

    top_plays = sorted(filtered_plays, key=hedge_sort_key, reverse=True)


    # Respect max_results if provided
    max_results = getattr(payload, "max_results", None)
    if max_results is not None and max_results > 0:
        top_plays = top_plays[:max_results]

    sgp_suggestion = None
    if payload.include_sgp and top_plays:
        # SGP still uses same-side EV ordering internally
        sgp_suggestion = choose_three_leg_parlay(top_plays, target_book)

    return ValuePlaysResponse(
        target_book=target_book,
        market=market_key,
        plays=top_plays,
        sgp_suggestion=sgp_suggestion,
    )


@app.post("/api/best-value-plays", response_model=BestValuePlaysResponse)
def get_best_value_plays(payload: BestValuePlaysRequest) -> BestValuePlaysResponse:
    """
    Search across multiple sports and markets to find the best +EV bets by hedge odds.
    Returns the top value plays sorted by arb_margin_percent (hedge opportunity).
    """
    target_book = payload.target_book
    compare_book = payload.compare_book

    if target_book == compare_book:
        raise HTTPException(
            status_code=400,
            detail="Target book and comparison book cannot be the same.",
        )

    if not payload.sport_keys or not payload.markets:
        raise HTTPException(
            status_code=400,
            detail="At least one sport and one market must be specified.",
        )

    try:
        api_key = get_api_key()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    bookmaker_keys = [target_book, compare_book]
    regions = compute_regions_for_books(bookmaker_keys)

    all_plays: List[BestValuePlayOutcome] = []

    # Search across all sport/market combinations
    for sport_key in payload.sport_keys:
        for market_key in payload.markets:
            try:
                events = fetch_odds(
                    api_key=api_key,
                    sport_key=sport_key,
                    regions=regions,
                    markets=market_key,
                    bookmaker_keys=bookmaker_keys,
                )

                raw_plays = collect_value_plays(events, market_key, target_book, compare_book)

                # Filter out live events and games that have already started
                now_utc = datetime.now(timezone.utc)
                filtered_plays: List[ValuePlayOutcome] = []
                for p in raw_plays:
                    if not p.start_time:
                        # If no start time, exclude it to be safe
                        continue
                    try:
                        dt = datetime.fromisoformat(p.start_time.replace("Z", "+00:00"))
                        # Only include games that haven't started yet (start_time is in the future)
                        if dt > now_utc:
                            filtered_plays.append(p)
                    except Exception:
                        # If we can't parse the time, exclude it to be safe
                        continue

                # Convert to BestValuePlayOutcome with sport and market info
                for p in filtered_plays:
                    formatted_time = p.start_time
                    if formatted_time:
                        formatted_time = format_start_time_est(formatted_time)

                    all_plays.append(
                        BestValuePlayOutcome(
                            sport_key=sport_key,
                            market=market_key,
                            event_id=p.event_id,
                            matchup=p.matchup,
                            start_time=formatted_time,
                            outcome_name=p.outcome_name,
                            point=p.point,
                            novig_price=p.novig_price,
                            novig_reverse_name=p.novig_reverse_name,
                            novig_reverse_price=p.novig_reverse_price,
                            book_price=p.book_price,
                            ev_percent=p.ev_percent,
                            hedge_ev_percent=p.hedge_ev_percent,
                            is_arbitrage=p.is_arbitrage,
                            arb_margin_percent=p.arb_margin_percent,
                        )
                    )
            except Exception as e:
                # Log error but continue with other sports/markets
                print(f"Error processing {sport_key}/{market_key}: {e}")
                continue

    # Sort by hedge opportunity (arb_margin_percent) descending
    def hedge_sort_key(play: BestValuePlayOutcome) -> float:
        if play.arb_margin_percent is not None:
            return play.arb_margin_percent
        # No opposite side: effectively no hedge opportunity.
        return -1_000_000.0 + play.ev_percent

    top_plays = sorted(all_plays, key=hedge_sort_key, reverse=True)

    # Respect max_results if provided
    max_results = payload.max_results or 50
    if max_results > 0:
        top_plays = top_plays[:max_results]

    return BestValuePlaysResponse(
        target_book=target_book,
        compare_book=compare_book,
        plays=top_plays,
    )


# Static frontend (index.html, value.html, etc. under ./frontend)
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
