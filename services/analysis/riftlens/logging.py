from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog
from structlog.typing import EventDict, WrappedLogger

_RGAPI_RE = re.compile(
    r"RGAPI-[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
)
_REDACTED = "RGAPI-[REDACTED]"


def _redact_text(value: str) -> str:
    return _RGAPI_RE.sub(_REDACTED, value)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_redact_value(item) for item in value)
    if isinstance(value, BaseException):
        redacted = _redact_text(str(value))
        return type(value)(redacted)
    return value


class RiotKeyRedactor:
    """Strip Riot development keys from every structlog event field.

    Assumes processors that stringify exceptions run before this processor so
    traceback text is visible to the regex.
    """

    def __call__(
        self, _logger: WrappedLogger, _method_name: str, event_dict: EventDict
    ) -> EventDict:
        redacted = _redact_value(dict(event_dict))
        if not isinstance(redacted, dict):
            return event_dict
        return redacted


def configure_logging(*, json_output: bool = False, level: int = logging.INFO) -> None:
    """Configure structlog to stderr with Riot key redaction. Returns None."""
    renderer: structlog.types.Processor
    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            RiotKeyRedactor(),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
