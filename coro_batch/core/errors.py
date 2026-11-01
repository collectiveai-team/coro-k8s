"""The failures of a step, split by whether trying again can help."""

from __future__ import annotations


class TransientError(RuntimeError):
    """A failure that another attempt may not repeat: a busy server, a dropped connection.

    ``retry_after_seconds`` carries the server's ``Retry-After`` hint when it sent one.
    """

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class PermanentError(RuntimeError):
    """A failure that every attempt repeats: a missing file, audio coro refuses."""
