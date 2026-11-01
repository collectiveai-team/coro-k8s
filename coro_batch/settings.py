"""The settings of coro-batch, read from ``CORO_BATCH_*`` environment variables.

This is the only module that reads the environment.
"""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BatchSettings(BaseSettings):
    """Where coro is, how long to wait for it, and how to sign callbacks."""

    model_config = SettingsConfigDict(env_prefix="CORO_BATCH_", extra="ignore")

    coro_url: str = Field(
        default="http://coro:8000",
        description="Base URL of the coro Service, inside the cluster.",
    )
    coro_model: str = Field(
        default="whisper-1",
        description="The `model` form field sent to coro; coro serves its configured model.",
    )
    coro_timeout_seconds: float = Field(
        default=3600.0,
        gt=0,
        description="Seconds to wait for one transcription response.",
    )
    max_attempts: int = Field(
        default=6,
        ge=1,
        description="Attempts of a step before the job fails: transcription and callback.",
    )
    max_retry_wait_seconds: float = Field(
        default=600.0,
        gt=0,
        description="Longest wait between two attempts, Retry-After included.",
    )
    callback_secret: SecretStr | None = Field(
        default=None,
        description="Key that signs callbacks with HMAC-SHA256. Unset sends them unsigned.",
    )
    callback_secret_block: str | None = Field(
        default=None,
        description="Name of a Prefect Secret block holding the callback key, when "
        "callback_secret is unset.",
    )
    concurrency_limit: str | None = Field(
        default="coro-transcriptions",
        description="Prefect global concurrency limit held around each transcription. "
        "Empty disables it.",
    )
    work_dir: str | None = Field(
        default=None,
        description="Directory for downloaded audio. Unset uses the system temp dir.",
    )
    log_level: str = Field(default="INFO", description="Log level.")
    env: Literal["dev", "prod", "production"] = Field(
        default="dev",
        description="`prod` writes JSON logs; anything else writes console lines.",
    )


@functools.cache
def get_settings() -> BatchSettings:
    """Return the settings, reading the environment once."""
    return BatchSettings()
