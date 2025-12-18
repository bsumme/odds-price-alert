"""Helpers to manage request/response logging for the web app."""

import logging
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class TraceLevel(str, Enum):
    """Supported verbosity levels for API tracing."""

    DEBUG = "debug"
    TRACE = "trace"
    HUMAN = "human"
    REGULAR = "regular"


def get_trace_level_from_env() -> TraceLevel:
    """Return the configured trace level, defaulting to REGULAR."""

    raw_value = os.getenv("TRACE_LEVEL", TraceLevel.REGULAR.value).lower()
    normalized = raw_value.replace("_", "").replace("-", "")

    alias_map = {
        "humanreadable": TraceLevel.HUMAN,
        "human": TraceLevel.HUMAN,
        "h": TraceLevel.HUMAN,
    }

    if normalized in alias_map:
        return alias_map[normalized]

    for level in TraceLevel:
        if normalized == level.value:
            return level
    return TraceLevel.REGULAR


def apply_trace_level(logger: logging.Logger) -> TraceLevel:
    """Set the logger verbosity based on the TRACE_LEVEL environment variable."""

    trace_level = get_trace_level_from_env()
    level_mapping = {
        TraceLevel.DEBUG: logging.DEBUG,
        TraceLevel.TRACE: logging.INFO,
        TraceLevel.HUMAN: logging.INFO,
        TraceLevel.REGULAR: logging.WARNING,
    }
    logger.setLevel(level_mapping[trace_level])

    log_path = None
    if trace_level in (TraceLevel.DEBUG, TraceLevel.TRACE, TraceLevel.HUMAN):
        log_path = _configure_file_logging(logger, trace_level)

    if log_path:
        logger.info(
            "TRACE_LEVEL set to %s and logging to %s",
            trace_level.value,
            log_path,
        )

    return trace_level


def should_log_trace_entries(trace_level: TraceLevel | None = None) -> bool:
    """Return True when info-level traces should be emitted or persisted."""

    trace_level = trace_level or get_trace_level_from_env()
    return trace_level in (TraceLevel.TRACE, TraceLevel.DEBUG, TraceLevel.HUMAN)


def should_log_api_calls(trace_level: TraceLevel | None = None) -> bool:
    """Return True when detailed API call logging should occur."""

    trace_level = trace_level or get_trace_level_from_env()
    return trace_level == TraceLevel.DEBUG


def _configure_file_logging(logger: logging.Logger, trace_level: TraceLevel) -> Path:
    """Attach a timestamped file handler when verbose logging is enabled."""

    log_dir_env = os.getenv("TRACE_LOG_DIR")
    log_dir = Path(log_dir_env) if log_dir_env else Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = "human" if trace_level == TraceLevel.HUMAN else "trace"
    log_path = log_dir / f"{prefix}_{timestamp}.log"

    existing_handler = getattr(logger, "_trace_file_handler", None)
    if existing_handler:
        logger.removeHandler(existing_handler)

    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(logging.DEBUG if trace_level == TraceLevel.DEBUG else logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))

    logger.addHandler(file_handler)
    logger._trace_file_handler = file_handler  # type: ignore[attr-defined]
    logger._trace_log_path = log_path  # type: ignore[attr-defined]

    return log_path


def truncate_for_log(value: Any, max_length: int = 1200) -> str:
    """Return a safely truncated string for log output."""

    if value is None:
        return ""

    text = value if isinstance(value, str) else repr(value)
    if len(text) <= max_length:
        return text

    omitted = len(text) - max_length
    return f"{text[:max_length]}... [truncated {omitted} chars]"
