"""The data of a transcription job: what is asked, and what the callback reports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

ResponseFormat = Literal["json", "verbose_json", "diarized_json"]


class TranscriptionJob(BaseModel):
    """One audio file to transcribe, where to put the transcript, and whom to tell.

    ``audio_url`` and ``output_url`` are fsspec URLs (``s3://``, ``gs://``,
    ``https://``, ``file://``). Without ``output_url`` the transcript travels in
    the callback body instead of being stored.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str = Field(min_length=1, max_length=200)
    audio_url: str = Field(min_length=1)
    output_url: str | None = None
    callback_url: HttpUrl | None = None
    language: str | None = None
    prompt: str | None = None
    response_format: ResponseFormat = "verbose_json"


class JobOutcome(BaseModel):
    """How a job ended. It is also the body of the callback."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str
    status: Literal["succeeded", "failed"]
    finished_at: datetime
    output_url: str | None = None
    transcript: str | None = Field(
        default=None,
        description="The coro response body, when the job has no output_url.",
    )
    error: str | None = None
    attempts: int = Field(ge=0, description="Transcription attempts made.")
