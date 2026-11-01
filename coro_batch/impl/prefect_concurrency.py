"""A Transcriber decorator that holds a Prefect global concurrency slot per transcription.

The limit is shared by every flow run of every worker, so it caps the requests
in flight against the whole coro Deployment, not per worker. Size it near
``replicas x CORO_ASR_MAX_CONCURRENCY`` of coro; more only queues in coro.
The limit must exist (``prefect gcl create``): ``strict=True`` fails the flow run
otherwise, rather than transcribing with no limit. A failed lease renewal does
not stop a transcription that is already running.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prefect.concurrency.asyncio import concurrency

if TYPE_CHECKING:
    from pathlib import Path

    from coro_batch.core.models import ResponseFormat
    from coro_batch.core.ports import Transcriber


class ConcurrencyLimitedTranscriber:
    """Waits for a slot of a Prefect global concurrency limit, then transcribes."""

    def __init__(self, inner: Transcriber, *, limit_name: str) -> None:
        """Wrap ``inner`` with the global concurrency limit ``limit_name``."""
        self._inner = inner
        self._limit_name = limit_name

    async def transcribe(
        self,
        audio: Path,
        *,
        language: str | None,
        prompt: str | None,
        response_format: ResponseFormat,
    ) -> str:
        """Hold one slot of the limit while ``inner`` transcribes ``audio``."""
        async with concurrency(
            self._limit_name, occupy=1, strict=True, raise_on_lease_renewal_failure=False
        ):
            return await self._inner.transcribe(
                audio, language=language, prompt=prompt, response_format=response_format
            )
