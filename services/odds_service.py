"""Services for odds fetching and transformation logic."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from utils.formatting import pretty_book_label
from utils.regions import compute_regions_for_books
from services.odds_utils import american_to_decimal, MAX_VALID_AMERICAN_ODDS


class OddsService:
    """Encapsulates odds retrieval and transformation for watcher bets."""

    def __init__(
        self,
        odds_fetcher,
        data_validator,
        price_out_model,
        single_bet_odds_model,
        odds_response_model,
    ) -> None:
        self._odds_fetcher = odds_fetcher
        self._data_validator = data_validator
        self._price_out_model = price_out_model
        self._single_bet_odds_model = single_bet_odds_model
        self._odds_response_model = odds_response_model

    def get_odds(self, payload, api_key: str, use_dummy_data: bool):
        """Build an OddsResponse for the provided request payload."""

        all_book_keys = self._collect_bookmaker_keys(payload.bets)
        regions = compute_regions_for_books(list(all_book_keys))

        all_bets_results: List[Any] = []
        bets_by_sport = self._group_bets_by_sport(payload.bets)

        for sport_key, bets_for_sport in bets_by_sport.items():
            markets = sorted({b.market for b in bets_for_sport})
            bookmaker_keys = sorted({bk for b in bets_for_sport for bk in b.bookmaker_keys})

            events = self._odds_fetcher(
                api_key=api_key,
                sport_key=sport_key,
                regions=regions,
                markets=",".join(markets),
                bookmaker_keys=bookmaker_keys,
                use_dummy_data=use_dummy_data,
            )

            self._data_validator(events, allow_dummy=use_dummy_data)

            for bet in bets_for_sport:
                prices_per_book: List[Any] = []

                for book_key in bet.bookmaker_keys:
                    price_for_team: Optional[int] = None
                    verified_from_api = False

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
                            verified_from_api = not use_dummy_data
                            break

                    if price_for_team is not None:
                        break

                    prices_per_book.append(
                        self._price_out_model(
                            bookmaker_key=book_key,
                            bookmaker_name=pretty_book_label(book_key),
                            price=price_for_team,
                            verified_from_api=verified_from_api,
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
                    self._single_bet_odds_model(
                        sport_key=sport_key,
                        market=bet.market,
                        team=bet.team,
                        point=bet.point,
                        prices=prices_per_book,
                    )
                )

        return self._odds_response_model(bets=all_bets_results)

    @staticmethod
    def _collect_bookmaker_keys(bets: Sequence[Any]) -> set[str]:
        all_book_keys: set[str] = set()
        for bet in bets:
            all_book_keys.update(bet.bookmaker_keys)
        return all_book_keys

    @staticmethod
    def _group_bets_by_sport(bets: Iterable[Any]) -> Dict[str, List[Any]]:
        grouped: Dict[str, List[Any]] = {}
        for bet in bets:
            grouped.setdefault(bet.sport_key, []).append(bet)
        return grouped
