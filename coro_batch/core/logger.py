"""The logger of coro-batch: JSON in production, a console line otherwise.

Every module gets its logger from :func:`get_logger`. The loggers go through the
standard library under the ``coro_batch`` name, so a Prefect worker forwards
them to the flow run logs when ``PREFECT_LOGGING_EXTRA_LOGGERS=coro_batch``.
"""

from __future__ import annotations

import functools
import logging
import sys
from typing import TYPE_CHECKING

import structlog

from coro_batch.settings import get_settings

if TYPE_CHECKING:
    from structlog.typing import FilteringBoundLogger, Processor


@functools.cache
def _configure() -> None:
    settings = get_settings()
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    renderers: list[Processor] = (
        [structlog.processors.dict_tracebacks, structlog.processors.JSONRenderer()]
        if settings.env in {"prod", "production"}
        else [structlog.dev.ConsoleRenderer()]
    )
    level = logging.getLevelNamesMapping()[settings.log_level.upper()]
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[*shared, *renderers],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    """Return the logger of `name`, usually `__name__`, configuring structlog on the first call."""
    _configure()
    return structlog.get_logger(name)
