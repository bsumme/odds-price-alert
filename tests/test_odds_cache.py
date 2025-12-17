import time

from services.odds_cache import cached_odds, clear_odds_cache


def setup_function() -> None:  # type: ignore[override]
    clear_odds_cache()


def test_cached_odds_reuses_result_within_ttl() -> None:
    call_count = 0

    @cached_odds(ttl=2)
    def fetch_data(*, value: int, use_dummy_data: bool = False) -> dict:
        nonlocal call_count
        call_count += 1
        return {"value": value, "call": call_count}

    first = fetch_data(value=1, use_dummy_data=False)
    second = fetch_data(value=1, use_dummy_data=False)

    assert call_count == 1
    assert first == second


def test_cached_odds_expires_after_ttl() -> None:
    call_count = 0

    @cached_odds(ttl=1)
    def fetch_data(*, value: int, use_dummy_data: bool = False) -> dict:
        nonlocal call_count
        call_count += 1
        return {"value": value, "call": call_count}

    first = fetch_data(value=2, use_dummy_data=False)
    time.sleep(1.1)
    second = fetch_data(value=2, use_dummy_data=False)

    assert call_count == 2
    assert first != second


def test_cached_odds_skips_dummy_data_requests() -> None:
    call_count = 0

    @cached_odds(ttl=60)
    def fetch_data(*, value: int, use_dummy_data: bool = False) -> dict:
        nonlocal call_count
        call_count += 1
        return {"value": value, "call": call_count}

    first = fetch_data(value=3, use_dummy_data=True)
    second = fetch_data(value=3, use_dummy_data=True)

    assert call_count == 2
    assert first["call"] == 1
    assert second["call"] == 2

