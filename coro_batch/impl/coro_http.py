"""The Transcriber adapter that calls coro's OpenAI-compatible endpoint over HTTP."""

from __future__ import annotations

import email.utils
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx

from coro_batch.core.errors import PermanentError, TransientError

if TYPE_CHECKING:
    from pathlib import Path

    from coro_batch.core.models import ResponseFormat

TRANSCRIPTIONS_PATH = "/v1/audio/transcriptions"

# 429: coro's per-client rate limit or its ASR admission queue is full.
# 503: coro is not ready yet, or a model failed to load (ADR 0003).
# 502 and 504: the proxy in front of coro, when the request goes through one.
_RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


def parse_retry_after(value: str | None, *, now: datetime) -> float | None:
    """Return the seconds a ``Retry-After`` header asks to wait, or None.

    Args:
        value: The header: delay seconds or an HTTP date.
        now: The current time, to turn an HTTP date into seconds.

    Returns:
        Seconds to wait, never negative, or None when the header is absent or unreadable.

    """
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max((when - now).total_seconds(), 0.0)


class CoroTranscriber:
    """POSTs the audio as multipart to ``/v1/audio/transcriptions`` and returns the body."""

    def __init__(self, client: httpx.AsyncClient, *, model: str) -> None:
        """Create the adapter.

        Args:
            client: A client whose ``base_url`` is the coro Service and whose
                timeout covers the longest transcription.
            model: The ``model`` form field; coro serves its configured model.

        """
        self._client = client
        self._model = model

    async def transcribe(
        self,
        audio: Path,
        *,
        language: str | None,
        prompt: str | None,
        response_format: ResponseFormat,
    ) -> str:
        """Return the coro response body for ``audio``, streaming the file from disk.

        Raises:
            PermanentError: coro answered with a 4xx other than 429.
            TransientError: coro answered 429, 502, 503 or 504, or did not answer.

        """
        fields = {"model": self._model, "response_format": response_format}
        if language:
            fields["language"] = language
        if prompt:
            fields["prompt"] = prompt
        try:
            with audio.open("rb") as handle:
                response = await self._client.post(
                    TRANSCRIPTIONS_PATH,
                    data=fields,
                    files={"file": (audio.name, handle, "application/octet-stream")},
                )
        except httpx.TransportError as exc:
            msg = f"coro did not answer: {exc!r}"
            raise TransientError(msg) from exc
        return _body_or_raise(response)


def _body_or_raise(response: httpx.Response) -> str:
    if response.is_success:
        return response.text
    detail = f"coro answered {response.status_code}: {response.text[:500]}"
    if response.status_code in _RETRYABLE_STATUS or response.is_server_error:
        retry_after = parse_retry_after(
            response.headers.get("retry-after"), now=datetime.now(tz=UTC)
        )
        raise TransientError(detail, retry_after_seconds=retry_after)
    raise PermanentError(detail)
