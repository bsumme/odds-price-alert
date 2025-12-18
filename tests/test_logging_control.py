from utils.logging_control import truncate_for_log


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
