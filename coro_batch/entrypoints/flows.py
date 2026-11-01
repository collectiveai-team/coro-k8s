"""The Prefect flow that transcribes a batch of jobs with a coro Service.

Deploy it with ``prefect deploy`` (see ``prefect.yaml``) and start it through
the Prefect API with the parameter ``jobs``; each job reports to its own
callback URL when it ends.
"""

from __future__ import annotations

import asyncio

from prefect import flow, task

from coro_batch.core.jobs import CallbackUndeliveredError, run_job
from coro_batch.core.logger import get_logger
from coro_batch.core.models import JobOutcome, TranscriptionJob
from coro_batch.entrypoints.wiring import open_ports, retry_policy
from coro_batch.settings import get_settings

logger = get_logger(__name__)

DEFAULT_PARALLEL_JOBS = 8


class BatchIncompleteError(RuntimeError):
    """Some jobs of the batch ended without a delivered callback."""


@task(name="transcribe-job", task_run_name="job-{job.job_id}")
async def transcribe_job(job: TranscriptionJob) -> JobOutcome:
    """Run one job: fetch, transcribe, store and call back. Retries are inside the job."""
    settings = get_settings()
    async with open_ports(settings) as ports:
        return await run_job(job, ports, policy=retry_policy(settings), work_dir=settings.work_dir)


@flow(name="transcribe-batch", log_prints=False)
async def transcribe_batch(
    jobs: list[TranscriptionJob], parallel_jobs: int = DEFAULT_PARALLEL_JOBS
) -> list[JobOutcome]:
    """Transcribe every job of the batch, ``parallel_jobs`` at a time.

    ``parallel_jobs`` bounds the downloads and open requests of this flow run.
    The Prefect global concurrency limit bounds the transcriptions of all flow
    runs together.

    Args:
        jobs: The jobs.
        parallel_jobs: Jobs of this batch in progress at once.

    Returns:
        The outcome of each job whose callback was delivered or that had none.

    Raises:
        BatchIncompleteError: At least one job's callback could not be delivered.

    """
    gate = asyncio.Semaphore(max(1, parallel_jobs))

    async def bounded(job: TranscriptionJob) -> JobOutcome:
        async with gate:
            return await transcribe_job(job)

    results = await asyncio.gather(*(bounded(job) for job in jobs), return_exceptions=True)
    outcomes = [result for result in results if isinstance(result, JobOutcome)]
    undelivered = [result for result in results if isinstance(result, BaseException)]
    for error in undelivered:
        logger.error("job_unreported", error=str(error))
    if undelivered:
        unreported = sum(isinstance(error, CallbackUndeliveredError) for error in undelivered)
        msg = (
            f"{len(undelivered)} of {len(jobs)} jobs ended unreported "
            f"({unreported} callbacks undelivered)"
        )
        raise BatchIncompleteError(msg)
    return outcomes
