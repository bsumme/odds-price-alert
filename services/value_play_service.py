"""Services encapsulating value play calculations."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, List
from utils.formatting import format_start_time_est
from utils.regions import compute_regions_for_books

logger = logging.getLogger(__name__)


class ValuePlayService:
    """Handle value play and best-value-play orchestration."""

    def __init__(
        self,
        odds_fetcher,
        data_validator,
        collect_value_plays: Callable[..., List[Any]],
        value_response_model,
        best_value_response_model,
        best_value_outcome_model,
    ) -> None:
        self._odds_fetcher = odds_fetcher
        self._data_validator = data_validator
        self._collect_value_plays = collect_value_plays
        self._value_response_model = value_response_model
        self._best_value_response_model = best_value_response_model
        self._best_value_outcome_model = best_value_outcome_model

    def get_value_plays(self, payload, api_key: str, use_dummy_data: bool):
        bookmaker_keys = [payload.target_book, payload.compare_book]
        regions = compute_regions_for_books(bookmaker_keys)

        events = self._odds_fetcher(
            api_key=api_key,
            sport_key=payload.sport_key,
            regions=regions,
            markets=payload.market,
            bookmaker_keys=bookmaker_keys,
            use_dummy_data=use_dummy_data,
        )

        self._data_validator(events, allow_dummy=use_dummy_data)

        raw_plays = self._collect_value_plays(
            events, payload.market, payload.target_book, payload.compare_book
        )

        filtered_plays = self._filter_future_events(raw_plays)
        self._format_start_times(filtered_plays)

        top_plays = self._sort_by_hedge(filtered_plays)

        max_results = getattr(payload, "max_results", None)
        if max_results is not None and max_results > 0:
            top_plays = top_plays[:max_results]

        return self._value_response_model(
            target_book=payload.target_book,
            compare_book=payload.compare_book,
            market=payload.market,
            plays=top_plays,
        )

    def get_best_value_plays(self, payload, api_key: str, use_dummy_data: bool):
        bookmaker_keys = [payload.target_book, payload.compare_book]
        regions = compute_regions_for_books(bookmaker_keys)

        all_plays: List[Any] = []

        for sport_key in payload.sport_keys:
            for market_key in payload.markets:
                try:
                    events = self._odds_fetcher(
                        api_key=api_key,
                        sport_key=sport_key,
                        regions=regions,
                        markets=market_key,
                        bookmaker_keys=bookmaker_keys,
                        use_dummy_data=use_dummy_data,
                    )

                    self._data_validator(events, allow_dummy=use_dummy_data)

                    raw_plays = self._collect_value_plays(
                        events, market_key, payload.target_book, payload.compare_book
                    )

                    filtered_plays = self._filter_future_events(raw_plays)

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
                            self._best_value_outcome_model(
                                sport_key=sport_key,
                                market=market_key,
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

        return self._best_value_response_model(
            target_book=payload.target_book,
            compare_book=payload.compare_book,
            plays=top_plays,
            used_dummy_data=use_dummy_data,
        )

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
