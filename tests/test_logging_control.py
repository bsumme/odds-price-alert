from utils.logging_control import TraceLevel, get_trace_level_from_env, should_log_trace_entries, truncate_for_log


def test_truncate_for_log_returns_unchanged_when_short() -> None:
    assert truncate_for_log("short", max_length=10) == "short"


def test_truncate_for_log_truncates_and_notes_omitted_length() -> None:
    long_text = "a" * 15
    result = truncate_for_log(long_text, max_length=10)

    assert result.startswith("a" * 10)
    assert "truncated 5 chars" in result


def test_truncate_for_log_handles_non_string_values() -> None:
    payload = {"key": "value"}

    truncated = truncate_for_log(payload, max_length=12)

    assert truncated.startswith("{'key': 'val")
    assert "truncated" in truncated


def test_get_trace_level_accepts_human_alias(monkeypatch) -> None:
    monkeypatch.setenv("TRACE_LEVEL", "human")

    assert get_trace_level_from_env() == TraceLevel.HUMAN


def test_human_trace_level_triggers_trace_entries(monkeypatch) -> None:
    monkeypatch.setenv("TRACE_LEVEL", "human_readable")

    assert should_log_trace_entries() is True
