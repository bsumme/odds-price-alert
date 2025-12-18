"""Load a complete odds snapshot in a single pass."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from services.odds_api import ApiCreditTracker
from services.repositories.odds_repository import OddsRepository
from services.snapshot import OddsSnapshot
from services.snapshot_config import (
    DEFAULT_BOOKMAKERS,
    DEFAULT_MARKETS_BY_SPORT,
    DEFAULT_PLAYER_PROP_MARKETS_BY_SPORT,
    DEFAULT_SNAPSHOT_SPORTS,
)

logger = logging.getLogger(__name__)


class SnapshotLoader:
    """Coordinate fetching all required odds/player-prop payloads."""

    def __init__(
        self,
        repository: OddsRepository,
        *,
        sports: Optional[Iterable[str]] = None,
        markets_by_sport: Optional[Dict[str, List[str]]] = None,
        player_prop_markets: Optional[Dict[str, List[str]]] = None,
        bookmakers: Optional[Iterable[str]] = None,
        gateway_caller: str = "snapshot_loader",
    ) -> None:
        self._repository = repository
        self._sports = list(sports or DEFAULT_SNAPSHOT_SPORTS)
        self._markets_by_sport = markets_by_sport or DEFAULT_MARKETS_BY_SPORT
        self._player_prop_markets = player_prop_markets or DEFAULT_PLAYER_PROP_MARKETS_BY_SPORT
        self._bookmakers = list(bookmakers or DEFAULT_BOOKMAKERS)
        self._gateway_caller = gateway_caller

    def load_snapshot(self, *, use_dummy_data: bool) -> OddsSnapshot:
        tracker = ApiCreditTracker() if not use_dummy_data else None
        snapshot = OddsSnapshot(
            use_dummy_data=use_dummy_data,
            fetched_at=datetime.now(timezone.utc),
        )

        for sport_key in self._sports:
            markets = self._markets_by_sport.get(sport_key, [])
            if markets:
                logger.info(
                    "Fetching snapshot odds: sport=%s markets=%s books=%s dummy=%s",
                    sport_key,
                    ",".join(markets),
                    ",".join(self._bookmakers),
                    use_dummy_data,
                )
                credit_before = tracker.total_credits_used if tracker else 0
                try:
                    events = self._repository.get_odds_events(
                        api_key=self._repository.resolve_api_key(use_dummy_data),
                        sport_key=sport_key,
                        markets=markets,
                        bookmaker_keys=self._bookmakers,
                        use_dummy_data=use_dummy_data,
                        credit_tracker=tracker,
                        gateway_caller=self._gateway_caller,
                    )
                except Exception:
                    logger.exception("Snapshot odds fetch failed for sport=%s", sport_key)
                    events = []
                credit_delta = (
                    (tracker.total_credits_used - credit_before) if tracker else 0
                )
                if events:
                    snapshot.add_entry(
                        category="odds",
                        sport_key=sport_key,
                        markets=markets,
                        bookmaker_keys=self._bookmakers,
                        events=events,
                        fetched_at=datetime.now(timezone.utc),
                        credit_usage=credit_delta,
                    )

            prop_markets = self._player_prop_markets.get(sport_key)
            if prop_markets:
                logger.info(
                    "Fetching snapshot player props: sport=%s markets=%s books=%s dummy=%s",
                    sport_key,
                    ",".join(prop_markets),
                    ",".join(self._bookmakers),
                    use_dummy_data,
                )
                credit_before = tracker.total_credits_used if tracker else 0
                try:
                    props_events = self._repository.get_odds_events(
                        api_key=self._repository.resolve_api_key(use_dummy_data),
                        sport_key=sport_key,
                        markets=prop_markets,
                        bookmaker_keys=self._bookmakers,
                        use_dummy_data=use_dummy_data,
                        credit_tracker=tracker,
                        force_player_props=True,
                        gateway_caller=self._gateway_caller,
                    )
                except Exception:
                    logger.exception("Snapshot player props fetch failed for sport=%s", sport_key)
                    props_events = []
                credit_delta = (
                    (tracker.total_credits_used - credit_before) if tracker else 0
                )
                if props_events:
                    snapshot.add_entry(
                        category="player_props",
                        sport_key=sport_key,
                        markets=prop_markets,
                        bookmaker_keys=self._bookmakers,
                        events=props_events,
                        fetched_at=datetime.now(timezone.utc),
                        credit_usage=credit_delta,
                    )

                    discovery_markets = prop_markets
                    try:
                        events_list = self._repository.get_sport_events(
                            api_key=self._repository.resolve_api_key(use_dummy_data),
                            sport_key=sport_key,
                            use_dummy_data=use_dummy_data,
                            discovery_markets=discovery_markets,
                            bookmaker_keys=self._bookmakers,
                            gateway_caller=self._gateway_caller,
                        )
                    except Exception:
                        logger.exception("Snapshot events fetch failed for sport=%s", sport_key)
                        events_list = []

                    if events_list:
                        snapshot.add_entry(
                            category="sport_events",
                            sport_key=sport_key,
                            markets=discovery_markets,
                            bookmaker_keys=self._bookmakers,
                            events=events_list,
                            fetched_at=datetime.now(timezone.utc),
                        )

        if tracker:
            snapshot.total_credit_usage = tracker.total_credits_used

        return snapshot
