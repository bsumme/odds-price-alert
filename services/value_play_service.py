"""Services encapsulating value play calculations."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, List

from services.domain import models
from services.player_props_config import expand_player_prop_markets, is_player_prop_market
from utils.formatting import format_start_time_est

logger = logging.getLogger(__name__)


class ValuePlayService:
    """Handle value play and best-value-play orchestration."""

    def __init__(
        self,
        events_provider,
        data_validator,
        collect_value_plays: Callable[..., List[Any]],
    ) -> None:
        self._events_provider = events_provider
        self._data_validator = data_validator
        self._collect_value_plays = collect_value_plays

    def get_value_plays(
        self, payload: models.ValuePlaysQuery, use_dummy_data: bool, snapshot=None
    ) -> models.ValuePlaysResult:
        bookmaker_keys = [payload.target_book, payload.compare_book]

        events = self._events_provider(
            sport_key=payload.sport_key,
            markets=payload.market,
            bookmaker_keys=bookmaker_keys,
            category="player_props" if is_player_prop_market(payload.market) else "odds",
            snapshot=snapshot,
        )

        self._data_validator(events, allow_dummy=use_dummy_data)

        raw_plays_dto = self._collect_value_plays(
            events, payload.market, payload.target_book, payload.compare_book
        )
        raw_plays = [
            models.ValuePlay(
                event_id=play.event_id,
                matchup=play.matchup,
                start_time=play.start_time,
                outcome_name=play.outcome_name,
                point=play.point,
                market=getattr(play, "market", payload.market),
                novig_price=play.novig_price,
                novig_reverse_name=play.novig_reverse_name,
                novig_reverse_price=play.novig_reverse_price,
                book_price=play.book_price,
                ev_percent=play.ev_percent,
                hedge_ev_percent=getattr(play, "hedge_ev_percent", None),
                is_arbitrage=getattr(play, "is_arbitrage", False),
                arb_margin_percent=getattr(play, "arb_margin_percent", None),
            )
            for play in raw_plays_dto
        ]

        filtered_plays = self._filter_future_events(raw_plays)
        self._format_start_times(filtered_plays)

        top_plays = self._sort_by_hedge(filtered_plays)

        max_results = getattr(payload, "max_results", None)
        if max_results is not None and max_results > 0:
            top_plays = top_plays[:max_results]

        return models.ValuePlaysResult(
            target_book=payload.target_book,
            compare_book=payload.compare_book,
            market=payload.market,
            plays=top_plays,
        )

    def get_best_value_plays(
        self, payload: models.BestValuePlaysQuery, use_dummy_data: bool, snapshot=None
    ) -> models.BestValuePlaysResult:
        all_plays: List[Any] = []

        for sport_key in payload.sport_keys:
            for market_key in payload.markets:
                expanded_markets = self._expand_market_keys_for_sport(sport_key, market_key)
                if not expanded_markets:
                    continue

                try:
                    events = self._events_provider(
                        sport_key=sport_key,
                        markets=expanded_markets,
                        bookmaker_keys=[payload.target_book, payload.compare_book],
                        category="player_props"
                        if any(is_player_prop_market(m) for m in expanded_markets)
                        else "odds",
                        snapshot=snapshot,
                    )

                    self._data_validator(events, allow_dummy=use_dummy_data)

                    for normalized_market in expanded_markets:
                        raw_plays_dto = self._collect_value_plays(
                            events, normalized_market, payload.target_book, payload.compare_book
                        )

                        filtered_plays = self._filter_future_events(
                            [
                                models.ValuePlay(
                                    event_id=play.event_id,
                                    matchup=play.matchup,
                                    start_time=play.start_time,
                                    outcome_name=play.outcome_name,
                                    point=play.point,
                                    market=getattr(play, "market", normalized_market),
                                    novig_price=play.novig_price,
                                    novig_reverse_name=play.novig_reverse_name,
                                    novig_reverse_price=play.novig_reverse_price,
                                    book_price=play.book_price,
                                    ev_percent=play.ev_percent,
                                    hedge_ev_percent=getattr(play, "hedge_ev_percent", None),
                                    is_arbitrage=getattr(play, "is_arbitrage", False),
                                    arb_margin_percent=getattr(play, "arb_margin_percent", None),
                                )
                                for play in raw_plays_dto
                            ]
                        )

                        for play in filtered_plays:
                            formatted_time = play.start_time
                            if formatted_time and formatted_time.strip():
                                try:
                                    formatted_time = format_start_time_est(formatted_time)
                                except Exception:
                                    formatted_time = play.start_time or "—"
                            else:
                                formatted_time = "—"

                            all_plays.append(
                                models.BestValuePlay(
                                    sport_key=sport_key,
                                    market=getattr(play, "market", normalized_market),
                                    event_id=play.event_id,
                                    matchup=play.matchup,
                                    start_time=formatted_time,
                                    outcome_name=play.outcome_name,
                                    point=play.point,
                                    novig_price=play.novig_price,
                                    novig_reverse_name=play.novig_reverse_name,
                                    novig_reverse_price=play.novig_reverse_price,
                                    book_price=play.book_price,
                                    ev_percent=play.ev_percent,
                                    hedge_ev_percent=play.hedge_ev_percent,
                                    is_arbitrage=play.is_arbitrage,
                                    arb_margin_percent=play.arb_margin_percent,
                                )
                            )
                except Exception:
                    logger.exception("Error processing %s/%s", sport_key, market_key)
                    continue

        top_plays = self._sort_by_hedge(all_plays)

        max_results = payload.max_results or 50
        if max_results > 0:
            top_plays = top_plays[:max_results]

        return models.BestValuePlaysResult(
            target_book=payload.target_book,
            compare_book=payload.compare_book,
            plays=top_plays,
            used_dummy_data=use_dummy_data,
        )

    @staticmethod
    def _expand_market_keys_for_sport(sport_key: str, market_key: str) -> List[str]:
        """Normalize a market key and expand player-prop aliases for a sport."""

        if not market_key:
            return []

        if is_player_prop_market(market_key):
            return expand_player_prop_markets(sport_key, [market_key])

        trimmed = market_key.strip()
        return [trimmed] if trimmed else []

    @staticmethod
    def _sort_by_hedge(plays: Iterable[Any]) -> List[Any]:
        def hedge_sort_key(play) -> float:
            if getattr(play, "arb_margin_percent", None) is not None:
                return play.arb_margin_percent
            hedge_ev = getattr(play, "hedge_ev_percent", None)
            ev_percent = getattr(play, "ev_percent", 0)
            if hedge_ev is not None:
                return hedge_ev
            return -1_000_000.0 + ev_percent

        return sorted(plays, key=hedge_sort_key, reverse=True)

    @staticmethod
    def _filter_future_events(plays: Iterable[Any]) -> List[Any]:
        now_utc = datetime.now(timezone.utc)
        filtered: List[Any] = []
        for play in plays:
            start_time = getattr(play, "start_time", None)
            if not start_time:
                continue
            try:
                dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                if dt > now_utc:
                    filtered.append(play)
            except Exception:
                continue
        return filtered

    @staticmethod
    def _format_start_times(plays: Iterable[Any]) -> None:
        for play in plays:
            start_time = getattr(play, "start_time", None)
            if start_time:
                try:
                    play.start_time = format_start_time_est(start_time)
                except Exception:
                    play.start_time = start_time
