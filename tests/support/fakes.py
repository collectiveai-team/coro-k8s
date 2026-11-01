"""In-memory adapters of the ports of coro_batch.core, for tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from coro_batch.core.errors import PermanentError
from coro_batch.core.jobs import JobPorts

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from coro_batch.core.models import JobOutcome, ResponseFormat
    from coro_batch.core.ports import Transcriber

START = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


class FakeClock:
    """A clock that advances only when something sleeps, and keeps every sleep."""

    def __init__(self, start: datetime = START) -> None:
        self.current = start
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        """Return the fake time."""
        return self.current

    async def sleep(self, seconds: float) -> None:
        """Keep the wait and advance the fake time by it."""
        self.sleeps.append(seconds)
        self.current += timedelta(seconds=seconds)


class InMemoryStorage:
    """An object store in a dict: an AudioSource and a ResultSink."""

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = dict(objects or {})

    async def fetch(self, url: str, destination: Path) -> None:
        """Write the object at ``url`` to ``destination``."""
        if url not in self.objects:
            msg = f"{url}: not found"
            raise PermanentError(msg)
        await asyncio.to_thread(destination.write_bytes, self.objects[url])

    async def store(self, url: str, transcript: str) -> None:
        """Keep ``transcript`` at ``url``."""
        self.objects[url] = transcript.encode()


class ScriptedTranscriber:
    """Answers each call with the next item of a script: a body, or an exception to raise."""

    def __init__(self, script: Iterable[str | Exception]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, object]] = []

    async def transcribe(
        self,
        audio: Path,
        *,
        language: str | None,
        prompt: str | None,
        response_format: ResponseFormat,
    ) -> str:
        """Keep what was asked, then play the next item of the script."""
        content = await asyncio.to_thread(audio.read_bytes)
        self.calls.append(
            {
                "audio": content,
                "suffix": audio.suffix,
                "language": language,
                "prompt": prompt,
                "response_format": response_format,
            }
        )
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class RecordingNotifier:
    """Keeps every delivered callback; raises the scripted failures first."""

    def __init__(self, failures: Iterable[Exception] = ()) -> None:
        self.failures = list(failures)
        self.delivered: list[tuple[str, JobOutcome]] = []

    async def notify(self, callback_url: str, outcome: JobOutcome) -> None:
        """Raise the next scripted failure, or keep the callback."""
        if self.failures:
            raise self.failures.pop(0)
        self.delivered.append((callback_url, outcome))


def job_ports(
    *,
    storage: InMemoryStorage,
    transcriber: Transcriber,
    notifier: RecordingNotifier | None = None,
    clock: FakeClock | None = None,
) -> JobPorts:
    """Return ports over the in-memory adapters."""
    return JobPorts(
        source=storage,
        transcriber=transcriber,
        sink=storage,
        notifier=notifier or RecordingNotifier(),
        clock=clock or FakeClock(),
    )
