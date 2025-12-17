"""Mapping helpers between domain models and transport DTOs."""
from __future__ import annotations

from typing import Iterable, List

from services.domain import models


def map_bet_requests_to_domain(bets: Iterable) -> List[models.Bet]:
    """Convert incoming bet DTOs to domain bet objects."""

    return [
        models.Bet(
            sport_key=bet.sport_key,
            market=bet.market,
            team=bet.team,
            point=bet.point,
            bookmaker_keys=list(bet.bookmaker_keys),
        )
        for bet in bets
    ]


def map_odds_result_to_dto(
    odds_result: models.OddsResult,
    *,
    price_out_model,
    single_bet_odds_model,
    odds_response_model,
):
    """Map an OddsResult domain object to the Pydantic transport layer."""

    bet_dtos = []
    for bet in odds_result.bets:
        prices = [
            price_out_model(
                bookmaker_key=price.bookmaker_key,
                bookmaker_name=price.bookmaker_name,
                price=price.price,
                verified_from_api=price.verified_from_api,
            )
            for price in bet.prices
        ]
        bet_dtos.append(
            single_bet_odds_model(
                sport_key=bet.sport_key,
                market=bet.market,
                team=bet.team,
                point=bet.point,
                prices=prices,
            )
        )

    return odds_response_model(bets=bet_dtos)


def map_value_play_dto_to_domain(play) -> models.ValuePlay:
    """Convert a transport ValuePlay DTO to the domain representation."""

    return models.ValuePlay(
        event_id=play.event_id,
        matchup=play.matchup,
        start_time=play.start_time,
        outcome_name=play.outcome_name,
        point=play.point,
        market=getattr(play, "market", None),
        novig_price=play.novig_price,
        novig_reverse_name=play.novig_reverse_name,
        novig_reverse_price=play.novig_reverse_price,
        book_price=play.book_price,
        ev_percent=play.ev_percent,
        hedge_ev_percent=getattr(play, "hedge_ev_percent", None),
        is_arbitrage=getattr(play, "is_arbitrage", False),
        arb_margin_percent=getattr(play, "arb_margin_percent", None),
    )


def map_value_play_domain_to_dto(play: models.ValuePlay, *, value_play_model):
    """Convert a domain ValuePlay to a transport DTO."""

    return value_play_model(
        event_id=play.event_id,
        matchup=play.matchup,
        start_time=play.start_time,
        outcome_name=play.outcome_name,
        point=play.point,
        market=play.market,
        novig_price=play.novig_price,
        novig_reverse_name=play.novig_reverse_name,
        novig_reverse_price=play.novig_reverse_price,
        book_price=play.book_price,
        ev_percent=play.ev_percent,
        hedge_ev_percent=play.hedge_ev_percent,
        is_arbitrage=play.is_arbitrage,
        arb_margin_percent=play.arb_margin_percent,
    )


def map_value_plays_result_to_dto(
    result: models.ValuePlaysResult,
    *,
    value_play_model,
    response_model,
):
    """Map a ValuePlaysResult domain object to its transport response."""

    plays = [map_value_play_domain_to_dto(play, value_play_model=value_play_model) for play in result.plays]
    return response_model(
        target_book=result.target_book,
        compare_book=result.compare_book,
        market=result.market,
        plays=plays,
    )


def map_best_value_play_domain_to_dto(
    play: models.BestValuePlay, *, best_value_model
):
    """Convert a domain BestValuePlay to a transport DTO."""

    return best_value_model(
        sport_key=play.sport_key,
        market=play.market,
        event_id=play.event_id,
        matchup=play.matchup,
        start_time=play.start_time,
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


def map_best_value_plays_result_to_dto(
    result: models.BestValuePlaysResult,
    *,
    best_value_model,
    response_model,
):
    """Map a BestValuePlaysResult domain object to the transport response."""

    plays = [
        map_best_value_play_domain_to_dto(play, best_value_model=best_value_model)
        for play in result.plays
    ]
    return response_model(
        target_book=result.target_book,
        compare_book=result.compare_book,
        plays=plays,
        used_dummy_data=result.used_dummy_data,
    )


def map_value_play_dtos_to_domain(plays: Iterable) -> List[models.ValuePlay]:
    """Map a sequence of transport plays to domain plays."""

    return [map_value_play_dto_to_domain(play) for play in plays]


def map_value_plays_query(payload) -> models.ValuePlaysQuery:
    """Convert a ValuePlaysRequest DTO to a domain query object."""

    return models.ValuePlaysQuery(
        sport_key=payload.sport_key,
        target_book=payload.target_book,
        compare_book=payload.compare_book,
        market=payload.market,
        max_results=getattr(payload, "max_results", None),
    )


def map_best_value_plays_query(payload) -> models.BestValuePlaysQuery:
    """Convert a BestValuePlaysRequest DTO to a domain query object."""

    return models.BestValuePlaysQuery(
        sport_keys=list(payload.sport_keys),
        markets=list(payload.markets),
        target_book=payload.target_book,
        compare_book=payload.compare_book,
        max_results=getattr(payload, "max_results", None),
    )
