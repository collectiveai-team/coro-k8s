"""transcribe_batch on a temporary Prefect server, over the in-memory adapters.

Integration: the Prefect test harness starts a local API server on a socket.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import pytest
from prefect.testing.utilities import prefect_test_harness

from coro_batch.core.errors import PermanentError
from coro_batch.core.models import ResponseFormat, TranscriptionJob
from coro_batch.entrypoints import flows
from coro_batch.entrypoints.flows import BatchIncompleteError, transcribe_batch
from tests.support.fakes import InMemoryStorage, RecordingNotifier, job_ports

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


@pytest.fixture(scope="module", autouse=True)
def prefect_server():
    with prefect_test_harness(server_startup_timeout=60):
        yield


class GatedTranscriber:
    """Answers every call after a short pause, and keeps the most calls seen at once."""

    def __init__(self) -> None:
        self.running = 0
        self.peak = 0

    async def transcribe(
        self,
        audio: Path,
        *,
        language: str | None,
        prompt: str | None,
        response_format: ResponseFormat,
    ) -> str:
        """Count the call while it runs, and return the audio as text."""
        self.running += 1
        self.peak = max(self.peak, self.running)
        await asyncio.sleep(0.05)
        self.running -= 1
        return await asyncio.to_thread(audio.read_text)


def _use_ports(monkeypatch, ports) -> None:
    @asynccontextmanager
    async def open_ports(_settings):
        yield ports

    monkeypatch.setattr(flows, "open_ports", open_ports)


def _jobs(count: int) -> list[TranscriptionJob]:
    return [
        TranscriptionJob(
            job_id=f"job-{n}",
            audio_url=f"s3://in/{n}.wav",
            callback_url="https://receiver.test/hook",
        )
        for n in range(count)
    ]


async def test_every_job_is_reported_and_parallel_jobs_bounds_the_batch(monkeypatch):
    storage = InMemoryStorage({f"s3://in/{n}.wav": f"text {n}".encode() for n in range(6)})
    transcriber = GatedTranscriber()
    notifier = RecordingNotifier()
    _use_ports(monkeypatch, job_ports(storage=storage, transcriber=transcriber, notifier=notifier))

    outcomes = await transcribe_batch(_jobs(6), parallel_jobs=2)

    assert [outcome.transcript for outcome in outcomes] == [f"text {n}" for n in range(6)]
    assert sorted(outcome.job_id for _, outcome in notifier.delivered) == [
        f"job-{n}" for n in range(6)
    ]
    assert transcriber.peak == 2


async def test_an_undeliverable_callback_fails_the_flow_after_the_other_jobs(monkeypatch):
    storage = InMemoryStorage({f"s3://in/{n}.wav": b"text" for n in range(3)})
    notifier = RecordingNotifier([PermanentError("receiver answered 404")])
    ports = job_ports(storage=storage, transcriber=GatedTranscriber(), notifier=notifier)
    _use_ports(monkeypatch, ports)

    with pytest.raises(BatchIncompleteError, match="1 of 3 jobs ended unreported"):
        await transcribe_batch(_jobs(3), parallel_jobs=1)

    assert len(notifier.delivered) == 2
