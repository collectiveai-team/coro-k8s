"""Builds the adapters of a job from the settings, for the flows."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
from prefect.blocks.system import Secret

from coro_batch.core.jobs import JobPorts
from coro_batch.core.retry import RetryPolicy
from coro_batch.impl.clock import SystemClock
from coro_batch.impl.coro_http import CoroTranscriber
from coro_batch.impl.fsspec_storage import FsspecAudioSource, FsspecResultSink
from coro_batch.impl.http_callback import HttpCallbackNotifier
from coro_batch.impl.prefect_concurrency import ConcurrencyLimitedTranscriber

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from coro_batch.core.ports import Transcriber
    from coro_batch.settings import BatchSettings

CALLBACK_TIMEOUT_SECONDS = 30.0
CONNECT_TIMEOUT_SECONDS = 10.0


def retry_policy(settings: BatchSettings) -> RetryPolicy:
    """Return the retry policy the settings describe."""
    return RetryPolicy(
        max_attempts=settings.max_attempts, max_delay_seconds=settings.max_retry_wait_seconds
    )


async def callback_key(settings: BatchSettings) -> bytes | None:
    """Return the callback signing key: the setting, else the Prefect Secret block, else None."""
    if settings.callback_secret is not None:
        return settings.callback_secret.get_secret_value().encode()
    if settings.callback_secret_block:
        block = await Secret.aload(settings.callback_secret_block)
        return str(block.get()).encode()
    return None


@asynccontextmanager
async def open_ports(settings: BatchSettings) -> AsyncIterator[JobPorts]:
    """Yield the production adapters, closing their HTTP clients afterwards."""
    clock = SystemClock()
    coro_timeout = httpx.Timeout(settings.coro_timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS)
    callback_timeout = httpx.Timeout(CALLBACK_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS)
    async with (
        httpx.AsyncClient(base_url=settings.coro_url, timeout=coro_timeout) as coro_client,
        httpx.AsyncClient(timeout=callback_timeout) as callback_client,
    ):
        transcriber: Transcriber = CoroTranscriber(coro_client, model=settings.coro_model)
        if settings.concurrency_limit:
            transcriber = ConcurrencyLimitedTranscriber(
                transcriber, limit_name=settings.concurrency_limit
            )
        yield JobPorts(
            source=FsspecAudioSource(),
            transcriber=transcriber,
            sink=FsspecResultSink(),
            notifier=HttpCallbackNotifier(
                callback_client, clock=clock, key=await callback_key(settings)
            ),
            clock=clock,
        )
