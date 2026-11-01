"""The ports of a transcription job. ``coro_batch.impl`` holds their adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from coro_batch.core.models import JobOutcome, ResponseFormat


class AudioSource(Protocol):
    """Copies the audio of a job to a local file."""

    async def fetch(self, url: str, destination: Path) -> None:
        """Copy the object at ``url`` to ``destination``.

        Raises:
            PermanentError: The object does not exist or cannot be read.
            TransientError: The storage did not answer.

        """
        ...


class Transcriber(Protocol):
    """Sends a local audio file to coro and returns the response body."""

    async def transcribe(
        self,
        audio: Path,
        *,
        language: str | None,
        prompt: str | None,
        response_format: ResponseFormat,
    ) -> str:
        """Return the coro response body for ``audio``.

        Raises:
            PermanentError: coro refused the request.
            TransientError: coro is at capacity or did not answer.

        """
        ...


class ResultSink(Protocol):
    """Stores a transcript."""

    async def store(self, url: str, transcript: str) -> None:
        """Write ``transcript`` to ``url``.

        Raises:
            PermanentError: The location cannot be written.
            TransientError: The storage did not answer.

        """
        ...


class Notifier(Protocol):
    """Delivers the outcome of a job to its callback URL."""

    async def notify(self, callback_url: str, outcome: JobOutcome) -> None:
        """POST ``outcome`` to ``callback_url``.

        Raises:
            PermanentError: The receiver refused the callback.
            TransientError: The receiver did not answer or answered 5xx.

        """
        ...


class Clock(Protocol):
    """Tells the time and waits."""

    def now(self) -> datetime:
        """Return the current time, timezone-aware."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Wait ``seconds``."""
        ...
