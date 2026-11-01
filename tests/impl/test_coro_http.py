"""CoroTranscriber against an in-process HTTP transport that answers as coro does."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from coro_batch.core.errors import PermanentError, TransientError
from coro_batch.impl.coro_http import TRANSCRIPTIONS_PATH, CoroTranscriber, parse_retry_after

BODY = '{"text": "ask not"}'


def _transcriber(handler) -> CoroTranscriber:
    client = httpx.AsyncClient(base_url="http://coro:8000", transport=httpx.MockTransport(handler))
    return CoroTranscriber(client, model="whisper-1")


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "audio.wav"
    path.write_bytes(b"RIFF fake wav")
    return path


async def test_the_audio_and_the_form_fields_are_posted_as_multipart(audio):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=BODY)

    body = await _transcriber(handler).transcribe(
        audio, language="es", prompt=None, response_format="verbose_json"
    )

    assert body == BODY
    (request,) = seen
    assert request.url.path == TRANSCRIPTIONS_PATH
    content = request.read()
    assert b'name="response_format"\r\n\r\nverbose_json' in content
    assert b'name="language"\r\n\r\nes' in content
    assert b'name="model"\r\n\r\nwhisper-1' in content
    assert b'name="prompt"' not in content
    assert b"RIFF fake wav" in content


@pytest.mark.parametrize("status", [429, 502, 503, 504, 500])
async def test_capacity_and_server_errors_are_transient_and_carry_retry_after(audio, status):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"Retry-After": "5"}, text="busy")

    with pytest.raises(TransientError) as raised:
        await _transcriber(handler).transcribe(
            audio, language=None, prompt=None, response_format="json"
        )

    assert raised.value.retry_after_seconds == 5.0


@pytest.mark.parametrize("status", [400, 413, 415, 422])
async def test_a_refused_request_is_permanent(audio, status):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="not audio")

    with pytest.raises(PermanentError, match=f"coro answered {status}"):
        await _transcriber(handler).transcribe(
            audio, language=None, prompt=None, response_format="json"
        )


async def test_a_dropped_connection_is_transient(audio):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(TransientError) as raised:
        await _transcriber(handler).transcribe(
            audio, language=None, prompt=None, response_format="json"
        )

    assert raised.value.retry_after_seconds is None


NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("header", "seconds"),
    [
        ("5", 5.0),
        ("0", 0.0),
        ("Sun, 01 Nov 2026 12:00:30 GMT", 30.0),
        ("Sun, 01 Nov 2026 11:00:00 GMT", 0.0),
        (None, None),
        ("soon", None),
    ],
)
def test_retry_after_is_read_as_seconds_or_as_a_date(header, seconds):
    assert parse_retry_after(header, now=NOW) == seconds
