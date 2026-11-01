"""Trying a step again after a transient failure, honouring coro's Retry-After."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from coro_batch.core.errors import TransientError
from coro_batch.core.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from coro_batch.core.ports import Clock

logger = get_logger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    """How many attempts a step gets and how long to wait between them."""

    max_attempts: int = 6
    base_delay_seconds: float = 5.0
    max_delay_seconds: float = 600.0

    def delay(self, attempt: int, retry_after_seconds: float | None) -> float:
        """Return the wait before the attempt after ``attempt`` (1-based).

        The server's hint wins when it gave one; otherwise the wait doubles
        from ``base_delay_seconds``. Both are capped at ``max_delay_seconds``.
        """
        if retry_after_seconds is not None:
            return min(max(retry_after_seconds, 0.0), self.max_delay_seconds)
        return min(self.base_delay_seconds * 2 ** (attempt - 1), self.max_delay_seconds)


@dataclass
class Attempts:
    """The attempts a retried step made, readable after it returns or raises."""

    count: int = 0


async def retry[T](
    step: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    clock: Clock,
    name: str,
    attempts: Attempts | None = None,
) -> T:
    """Run ``step`` until it succeeds, raises a non-transient error, or runs out of attempts.

    Args:
        step: The step, called once per attempt.
        policy: Attempts and waits.
        clock: Waits between attempts.
        name: Name of the step in the logs.
        attempts: Counts the attempts made, when the caller needs the number.

    Returns:
        What ``step`` returned.

    Raises:
        TransientError: The last attempt failed transiently.

    """
    counter = attempts if attempts is not None else Attempts()
    while True:
        counter.count += 1
        try:
            return await step()
        except TransientError as exc:
            if counter.count >= policy.max_attempts:
                raise
            wait = policy.delay(counter.count, exc.retry_after_seconds)
            logger.warning(
                "step_retry", step=name, attempt=counter.count, wait_seconds=wait, error=str(exc)
            )
            await clock.sleep(wait)
