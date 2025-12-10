"""Helpers to manage request/response logging for the web app."""

import logging
import os
from enum import Enum


class TraceLevel(str, Enum):
    """Supported verbosity levels for API tracing."""

    DEBUG = "debug"
    TRACE = "trace"
    REGULAR = "regular"


def get_trace_level_from_env() -> TraceLevel:
    """Return the configured trace level, defaulting to REGULAR."""

    raw_value = os.getenv("TRACE_LEVEL", TraceLevel.REGULAR.value).lower()
    for level in TraceLevel:
        if raw_value == level.value:
            return level
    return TraceLevel.REGULAR


def apply_trace_level(logger: logging.Logger) -> TraceLevel:
    """Set the logger verbosity based on the TRACE_LEVEL environment variable."""

    trace_level = get_trace_level_from_env()
    level_mapping = {
        TraceLevel.DEBUG: logging.DEBUG,
        TraceLevel.TRACE: logging.INFO,
        TraceLevel.REGULAR: logging.WARNING,
    }
    logger.setLevel(level_mapping[trace_level])
    return trace_level


def should_log_trace_entries(trace_level: TraceLevel | None = None) -> bool:
    """Return True when info-level traces should be emitted or persisted."""

    trace_level = trace_level or get_trace_level_from_env()
    return trace_level in (TraceLevel.TRACE, TraceLevel.DEBUG)


def should_log_api_calls(trace_level: TraceLevel | None = None) -> bool:
    """Return True when detailed API call logging should occur."""

    trace_level = trace_level or get_trace_level_from_env()
    return trace_level == TraceLevel.DEBUG
