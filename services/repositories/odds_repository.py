"""Repository layer centralizing odds/event data retrieval."""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from services.odds_api import fetch_odds, fetch_player_props, fetch_sport_events
from utils.regions import compute_regions_for_books


class OddsRepository:
    """Provide a single entry point for odds, props, and event payloads."""

    def __init__(
        self,
        *,
        api_key_provider: Callable[[], str],
        region_resolver: Callable[[List[str]], str] = compute_regions_for_books,
        odds_fetcher: Callable[..., List[Dict[str, Any]]] = fetch_odds,
        player_props_fetcher: Callable[..., List[Dict[str, Any]]] = fetch_player_props,
        events_fetcher: Callable[..., List[Dict[str, Any]]] = fetch_sport_events,
        dummy_odds_generator: Optional[Callable[..., List[Dict[str, Any]]]] = None,
        dummy_player_props_generator: Optional[Callable[..., List[Dict[str, Any]]]] = None,
        enable_cache: bool = True,
    ) -> None:
        self._api_key_provider = api_key_provider
        self._region_resolver = region_resolver
        self._odds_fetcher = odds_fetcher
        self._player_props_fetcher = player_props_fetcher
        self._events_fetcher = events_fetcher
        self._dummy_odds_generator = dummy_odds_generator
        self._dummy_player_props_generator = dummy_player_props_generator
        self._enable_cache = enable_cache
        self._cache: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}

    def resolve_api_key(self, use_dummy_data: bool) -> str:
        """Return an API key unless dummy data is being used."""

        if use_dummy_data:
            return ""
        return self._api_key_provider()

    def compute_regions(self, bookmaker_keys: Iterable[str]) -> str:
        """Return the regions string for the given bookmakers."""

        unique_keys = sorted(set(bookmaker_keys))
        return self._region_resolver(unique_keys)

    def get_odds_events(
        self,
        *,
        api_key: str,
        sport_key: str,
        markets: Sequence[str] | str,
        bookmaker_keys: List[str],
        use_dummy_data: bool,
        team: Optional[str] = None,
        player_name: Optional[str] = None,
        event_id: Optional[str] = None,
        credit_tracker: Optional[Any] = None,
        force_player_props: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch odds or player props events for the requested markets."""

        normalized_markets = self._normalize_markets(markets)
        is_player_request = force_player_props or any(
            market.startswith("player_") for market in normalized_markets
        )
        regions = self.compute_regions(bookmaker_keys)
        cache_key = self._build_cache_key(
            "player_props" if is_player_request else "odds",
            sport_key,
            normalized_markets,
            bookmaker_keys,
            use_dummy_data,
            regions,
            team,
            player_name,
            event_id,
        )

        if self._enable_cache and cache_key in self._cache:
            return self._cache[cache_key]

        markets_param = ",".join(normalized_markets)
        if use_dummy_data:
            events = self._fetch_dummy_events(
                sport_key=sport_key,
                markets=normalized_markets,
                bookmaker_keys=bookmaker_keys,
                is_player_request=is_player_request,
                team=team,
                player_name=player_name,
            )
        else:
            events = self._fetch_live_events(
                api_key=api_key,
                sport_key=sport_key,
                regions=regions,
                markets_param=markets_param,
                bookmaker_keys=bookmaker_keys,
                is_player_request=is_player_request,
                team=team,
                player_name=player_name,
                event_id=event_id,
                credit_tracker=credit_tracker,
            )

        if self._enable_cache:
            self._cache[cache_key] = events
        return events

    def get_sport_events(
        self,
        *,
        api_key: str,
        sport_key: str,
        use_dummy_data: bool,
        discovery_markets: Optional[List[str]] = None,
        bookmaker_keys: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return sport events, using dummy props when dummy mode is enabled."""

        cache_key = None
        if self._enable_cache:
            cache_key = self._build_cache_key(
                "sport_events",
                sport_key,
                discovery_markets or [],
                bookmaker_keys or [],
                use_dummy_data,
                None,
                None,
                None,
                None,
            )
            if cache_key in self._cache:
                return self._cache[cache_key]

        if use_dummy_data:
            events = self._fetch_dummy_events(
                sport_key=sport_key,
                markets=discovery_markets or [],
                bookmaker_keys=bookmaker_keys or [],
                is_player_request=True,
            )
        else:
            events = self._events_fetcher(api_key=api_key, sport_key=sport_key)

        if cache_key is not None:
            self._cache[cache_key] = events
        return events

    @staticmethod
    def _normalize_markets(markets: Sequence[str] | str) -> List[str]:
        if isinstance(markets, str):
            parts = [m.strip() for m in markets.split(",")]
            return [m for m in parts if m]
        return [m for m in markets if m]

    @staticmethod
    def _build_cache_key(
        category: str,
        sport_key: str,
        markets: Sequence[str],
        bookmaker_keys: Sequence[str],
        use_dummy_data: bool,
        regions: Optional[str],
        team: Optional[str],
        player_name: Optional[str],
        event_id: Optional[str],
    ) -> Tuple[Any, ...]:
        return (
            category,
            sport_key,
            tuple(sorted(set(markets))),
            tuple(sorted(set(bookmaker_keys))),
            use_dummy_data,
            regions,
            team,
            player_name,
            event_id,
        )

    def _fetch_dummy_events(
        self,
        *,
        sport_key: str,
        markets: List[str],
        bookmaker_keys: List[str],
        is_player_request: bool,
        team: Optional[str] = None,
        player_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        generator = (
            self._dummy_player_props_generator if is_player_request else self._dummy_odds_generator
        )
        if generator is None:
            raise RuntimeError("Dummy data generator not configured")

        kwargs: Dict[str, Any] = {
            "sport_key": sport_key,
            "bookmaker_keys": bookmaker_keys,
        }
        if is_player_request:
            kwargs.update({"team": team, "player_name": player_name})
            kwargs["markets"] = markets
        else:
            kwargs["markets"] = ",".join(markets)
        return generator(**kwargs)

    def _fetch_live_events(
        self,
        *,
        api_key: str,
        sport_key: str,
        regions: str,
        markets_param: str,
        bookmaker_keys: List[str],
        is_player_request: bool,
        team: Optional[str],
        player_name: Optional[str],
        event_id: Optional[str],
        credit_tracker: Optional[Any],
    ) -> List[Dict[str, Any]]:
        if is_player_request:
            return self._player_props_fetcher(
                api_key=api_key,
                sport_key=sport_key,
                regions=regions,
                markets=markets_param,
                bookmaker_keys=bookmaker_keys,
                team=team,
                event_id=event_id,
                use_dummy_data=False,
                credit_tracker=credit_tracker,
            )

        # Standard odds fetcher does not accept team/player filters.
        return self._odds_fetcher(
            api_key=api_key,
            sport_key=sport_key,
            regions=regions,
            markets=markets_param,
            bookmaker_keys=bookmaker_keys,
            use_dummy_data=False,
            credit_tracker=credit_tracker,
        )

