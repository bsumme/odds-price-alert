from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PriceQuote:
    bookmaker_key: str
    bookmaker_name: str
    price: Optional[int]
    verified_from_api: bool = False


@dataclass
class Bet:
    sport_key: str
    market: str
    team: str
    point: Optional[float]
    bookmaker_keys: List[str] = field(default_factory=list)


@dataclass
class SingleBetOdds:
    sport_key: str
    market: str
    team: str
    point: Optional[float]
    prices: List[PriceQuote] = field(default_factory=list)


@dataclass
class OddsQuery:
    bets: List[Bet]


@dataclass
class OddsResult:
    bets: List[SingleBetOdds]


@dataclass
class ValuePlay:
    event_id: str
    matchup: str
    start_time: Optional[str]
    outcome_name: str
    point: Optional[float]
    market: Optional[str]
    novig_price: int
    novig_reverse_name: Optional[str]
    novig_reverse_price: Optional[int]
    book_price: int
    ev_percent: float
    hedge_ev_percent: Optional[float]
    is_arbitrage: bool
    arb_margin_percent: Optional[float]


@dataclass
class ValuePlaysQuery:
    sport_key: str
    target_book: str
    compare_book: str
    market: str
    max_results: Optional[int] = None


@dataclass
class ValuePlaysResult:
    target_book: str
    compare_book: str
    market: str
    plays: List[ValuePlay] = field(default_factory=list)


@dataclass
class BestValuePlay(ValuePlay):
    sport_key: str
    market: str


@dataclass
class BestValuePlaysQuery:
    sport_keys: List[str]
    markets: List[str]
    target_book: str
    compare_book: str
    max_results: Optional[int] = 50


@dataclass
class BestValuePlaysResult:
    target_book: str
    compare_book: str
    plays: List[BestValuePlay] = field(default_factory=list)
    used_dummy_data: bool = False
