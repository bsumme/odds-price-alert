import logging

from utils.logging_control import TraceLevel, apply_trace_level, get_trace_level_from_env, should_log_trace_entries, truncate_for_log


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


def test_human_trace_level_uses_human_file_prefix(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TRACE_LEVEL", "human")
    monkeypatch.setenv("TRACE_LOG_DIR", str(tmp_path))
    logger = logging.getLogger("test.logging_control.human")

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    trace_level = apply_trace_level(logger)
    log_path = getattr(logger, "_trace_log_path", None)
    handler = getattr(logger, "_trace_file_handler", None)

    assert trace_level == TraceLevel.HUMAN
    assert log_path is not None
    assert log_path.parent == tmp_path
    assert log_path.name.startswith("human_")
    assert log_path.suffix == ".log"

    if handler:
        handler.close()


def test_trace_file_formatter_excludes_logger_name(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TRACE_LEVEL", "trace")
    monkeypatch.setenv("TRACE_LOG_DIR", str(tmp_path))
    logger = logging.getLogger("test.logging_control.formatter")

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    apply_trace_level(logger)
    log_path = getattr(logger, "_trace_log_path", None)
    handler = getattr(logger, "_trace_file_handler", None)

    assert log_path is not None
    assert handler is not None

    logger.info("formatted entry")
    handler.flush()
    handler.close()

    log_contents = log_path.read_text()

    assert "formatted entry" in log_contents
    assert logger.name not in log_contents
