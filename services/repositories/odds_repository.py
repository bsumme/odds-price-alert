"""Repository layer centralizing odds/event data retrieval."""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from services.api_gateway import ApiGateway
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
        api_gateway: Optional[ApiGateway] = None,
    ) -> None:
        self._api_key_provider = api_key_provider
        self._region_resolver = region_resolver
        self._odds_fetcher = odds_fetcher
        self._player_props_fetcher = player_props_fetcher
        self._events_fetcher = events_fetcher
        self._dummy_odds_generator = dummy_odds_generator
        self._dummy_player_props_generator = dummy_player_props_generator
        self._enable_cache = enable_cache
        self._api_gateway = api_gateway
        self._cache: Dict[Tuple[Any, ...], Tuple[float, List[Dict[str, Any]]]] = {}
        self._cache_ttls: Dict[str, int] = {
            "odds": 5,
            "player_props": 10,
            "sport_events": 300,
        }

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
        gateway_caller: str = "snapshot_loader",
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
        cache_ttl = self._resolve_ttl(cache_key[0]) if self._enable_cache else None
        cached_value = self._get_cached_value(cache_key) if cache_ttl else None
        if cached_value is not None:
            return cached_value

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
                gateway_caller=gateway_caller,
            )

        if cache_ttl is not None and not use_dummy_data:
            self._store_cache_value(cache_key, events, cache_ttl)
        return events

    def get_sport_events(
        self,
        *,
        api_key: str,
        sport_key: str,
        use_dummy_data: bool,
        discovery_markets: Optional[List[str]] = None,
        bookmaker_keys: Optional[List[str]] = None,
        gateway_caller: str = "snapshot_loader",
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
            cache_ttl = self._resolve_ttl(cache_key[0])
            cached_value = self._get_cached_value(cache_key) if cache_ttl else None
            if cached_value is not None:
                return cached_value

        if use_dummy_data:
            events = self._fetch_dummy_events(
                sport_key=sport_key,
                markets=discovery_markets or [],
                bookmaker_keys=bookmaker_keys or [],
                is_player_request=True,
            )
        else:
            events = self._events_fetcher(
                api_key=api_key,
                sport_key=sport_key,
                gateway=self._api_gateway,
                gateway_caller=gateway_caller,
            )

        if cache_key is not None and not use_dummy_data:
            cache_ttl = self._resolve_ttl(cache_key[0])
            if cache_ttl is not None:
                self._store_cache_value(cache_key, events, cache_ttl)
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

    def _resolve_ttl(self, category: str) -> Optional[int]:
        return self._cache_ttls.get(category)

    def _get_cached_value(self, cache_key: Tuple[Any, ...]) -> Optional[List[Dict[str, Any]]]:
        cached = self._cache.get(cache_key)
        if not cached:
            return None

        expires_at, value = cached
        if time.monotonic() < expires_at:
            return value

        self._cache.pop(cache_key, None)
        return None

    def _store_cache_value(
        self, cache_key: Tuple[Any, ...], payload: List[Dict[str, Any]], ttl: int
    ) -> None:
        self._cache[cache_key] = (time.monotonic() + ttl, payload)

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
        gateway_caller: str,
    ) -> List[Dict[str, Any]]:
        fetcher = (
            self._player_props_fetcher if is_player_request else self._odds_fetcher
        )
        if is_player_request:
            return fetcher(
                api_key=api_key,
                sport_key=sport_key,
                regions=regions,
                markets=markets_param,
                bookmaker_keys=bookmaker_keys,
                team=team,
                player_name=player_name,
                event_id=event_id,
                use_dummy_data=False,
                credit_tracker=credit_tracker,
                gateway=self._api_gateway,
                gateway_caller=gateway_caller,
            )

        odds_kwargs: Dict[str, Any] = {
            "api_key": api_key,
            "sport_key": sport_key,
            "regions": regions,
            "markets": markets_param,
            "bookmaker_keys": bookmaker_keys,
            "use_dummy_data": False,
            "credit_tracker": credit_tracker,
            "gateway": self._api_gateway,
            "gateway_caller": gateway_caller,
        }
        return fetcher(**odds_kwargs)
