"""HttpCallbackNotifier against an in-process HTTP receiver."""

from __future__ import annotations

import hashlib
import hmac

import httpx
import pytest

from coro_batch.core.errors import PermanentError, TransientError
from coro_batch.core.models import JobOutcome
from coro_batch.impl.http_callback import SIGNATURE_HEADER, TIMESTAMP_HEADER, HttpCallbackNotifier
from tests.support.fakes import START, FakeClock

OUTCOME = JobOutcome(
    job_id="job-1", status="succeeded", finished_at=START, transcript="{}", attempts=1
)
URL = "https://receiver.test/hook"


def _notifier(handler, key: bytes | None) -> HttpCallbackNotifier:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HttpCallbackNotifier(client, clock=FakeClock(), key=key)


async def test_a_receiver_can_verify_the_signature_with_the_shared_key():
    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(204)

    await _notifier(handler, b"s3cret").notify(URL, OUTCOME)

    (request,) = received
    body = request.read()
    timestamp = request.headers[TIMESTAMP_HEADER]
    expected = hmac.new(b"s3cret", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert request.headers[SIGNATURE_HEADER] == f"sha256={expected}"
    assert timestamp == str(int(START.timestamp()))
    assert JobOutcome.model_validate_json(body) == OUTCOME


async def test_without_a_key_the_callback_is_unsigned():
    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200)

    await _notifier(handler, None).notify(URL, OUTCOME)

    assert SIGNATURE_HEADER not in received[0].headers


@pytest.mark.parametrize("status", [408, 429, 500, 503])
async def test_a_receiver_that_cannot_take_it_now_is_transient(status):
    with pytest.raises(TransientError):
        await _notifier(lambda _: httpx.Response(status), None).notify(URL, OUTCOME)


@pytest.mark.parametrize("status", [400, 401, 404, 410])
async def test_a_receiver_that_refuses_it_is_permanent(status):
    with pytest.raises(PermanentError):
        await _notifier(lambda _: httpx.Response(status), None).notify(URL, OUTCOME)
