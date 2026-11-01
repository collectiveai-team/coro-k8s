"""The steps of one transcription job: fetch, transcribe, store, call back."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from coro_batch.core.errors import PermanentError, TransientError
from coro_batch.core.logger import get_logger
from coro_batch.core.models import JobOutcome, TranscriptionJob
from coro_batch.core.retry import Attempts, RetryPolicy, retry

if TYPE_CHECKING:
    from collections.abc import Iterator

    from coro_batch.core.ports import AudioSource, Clock, Notifier, ResultSink, Transcriber

logger = get_logger(__name__)


class CallbackUndeliveredError(RuntimeError):
    """The job ended, but its callback could not be delivered."""

    def __init__(self, outcome: JobOutcome, cause: Exception) -> None:
        super().__init__(f"callback of job {outcome.job_id} undelivered: {cause}")
        self.outcome = outcome


@dataclass(frozen=True)
class JobPorts:
    """The adapters one job runs against."""

    source: AudioSource
    transcriber: Transcriber
    sink: ResultSink
    notifier: Notifier
    clock: Clock


async def run_job(
    job: TranscriptionJob, ports: JobPorts, *, policy: RetryPolicy, work_dir: str | None = None
) -> JobOutcome:
    """Transcribe one job and report its outcome to its callback URL.

    A failed job is an outcome, not an exception: it is reported like a
    success. Only an undeliverable callback raises, because then nobody
    learns how the job ended.

    Args:
        job: The job.
        ports: The adapters.
        policy: Attempts and waits of the transcription, the storage and the callback.
        work_dir: Directory for the downloaded audio; the system temp dir when None.

    Returns:
        How the job ended.

    Raises:
        CallbackUndeliveredError: The job has a callback URL and every delivery failed.

    """
    log = logger.bind(job_id=job.job_id)
    attempts = Attempts()
    try:
        transcript = await _transcribe(job, ports, policy, work_dir, attempts)
        if job.output_url is not None:
            output_url = job.output_url
            await retry(
                lambda: ports.sink.store(output_url, transcript),
                policy=policy,
                clock=ports.clock,
                name="store",
            )
        outcome = _succeeded(job, transcript, ports.clock, attempts.count)
    except (TransientError, PermanentError) as exc:
        log.error("job_failed", error=str(exc), attempts=attempts.count)
        outcome = _failed(job, exc, ports.clock, attempts.count)
    else:
        log.info("job_succeeded", attempts=attempts.count)
    await _report(job, outcome, ports, policy)
    return outcome


async def _transcribe(
    job: TranscriptionJob,
    ports: JobPorts,
    policy: RetryPolicy,
    work_dir: str | None,
    attempts: Attempts,
) -> str:
    with _scratch_file(work_dir, job.audio_url) as audio:
        await retry(
            lambda: ports.source.fetch(job.audio_url, audio),
            policy=policy,
            clock=ports.clock,
            name="fetch",
        )
        return await retry(
            lambda: ports.transcriber.transcribe(
                audio,
                language=job.language,
                prompt=job.prompt,
                response_format=job.response_format,
            ),
            policy=policy,
            clock=ports.clock,
            name="transcribe",
            attempts=attempts,
        )


async def _report(
    job: TranscriptionJob, outcome: JobOutcome, ports: JobPorts, policy: RetryPolicy
) -> None:
    if job.callback_url is None:
        return
    callback_url = str(job.callback_url)
    try:
        await retry(
            lambda: ports.notifier.notify(callback_url, outcome),
            policy=policy,
            clock=ports.clock,
            name="callback",
        )
    except (TransientError, PermanentError) as exc:
        raise CallbackUndeliveredError(outcome, exc) from exc


@contextmanager
def _scratch_file(work_dir: str | None, audio_url: str) -> Iterator[Path]:
    suffix = PurePosixPath(urlsplit(audio_url).path).suffix
    with tempfile.TemporaryDirectory(prefix="coro-batch-", dir=work_dir) as directory:
        yield Path(directory) / f"audio{suffix}"


def _succeeded(job: TranscriptionJob, transcript: str, clock: Clock, attempts: int) -> JobOutcome:
    stored = job.output_url is not None
    return JobOutcome(
        job_id=job.job_id,
        status="succeeded",
        finished_at=clock.now(),
        output_url=job.output_url,
        transcript=None if stored else transcript,
        attempts=attempts,
    )


def _failed(job: TranscriptionJob, error: Exception, clock: Clock, attempts: int) -> JobOutcome:
    return JobOutcome(
        job_id=job.job_id,
        status="failed",
        finished_at=clock.now(),
        error=str(error),
        attempts=attempts,
    )
