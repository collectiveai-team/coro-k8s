"""run_job: the steps of one job against in-memory adapters."""

from __future__ import annotations

import pytest

from coro_batch.core.errors import PermanentError, TransientError
from coro_batch.core.jobs import CallbackUndeliveredError, run_job
from coro_batch.core.models import TranscriptionJob
from coro_batch.core.retry import RetryPolicy
from tests.support.fakes import (
    FakeClock,
    InMemoryStorage,
    RecordingNotifier,
    ScriptedTranscriber,
    job_ports,
)

AUDIO = b"RIFF fake wav"
BODY = '{"text": "ask not"}'
POLICY = RetryPolicy(max_attempts=3, base_delay_seconds=5.0, max_delay_seconds=60.0)


def _job(**overrides: object) -> TranscriptionJob:
    fields: dict[str, object] = {
        "job_id": "job-1",
        "audio_url": "s3://in/jfk.wav",
        "callback_url": "https://receiver.test/hook",
    }
    fields.update(overrides)
    return TranscriptionJob.model_validate(fields)


async def test_a_stored_transcript_is_reported_by_its_url():
    storage = InMemoryStorage({"s3://in/jfk.wav": AUDIO})
    notifier = RecordingNotifier()
    ports = job_ports(storage=storage, transcriber=ScriptedTranscriber([BODY]), notifier=notifier)

    outcome = await run_job(_job(output_url="s3://out/job-1.json"), ports, policy=POLICY)

    assert storage.objects["s3://out/job-1.json"] == BODY.encode()
    assert outcome.status == "succeeded"
    assert outcome.output_url == "s3://out/job-1.json"
    assert outcome.transcript is None
    assert notifier.delivered == [("https://receiver.test/hook", outcome)]


async def test_without_an_output_url_the_transcript_travels_in_the_callback():
    ports = job_ports(
        storage=InMemoryStorage({"s3://in/jfk.wav": AUDIO}), transcriber=ScriptedTranscriber([BODY])
    )

    outcome = await run_job(_job(), ports, policy=POLICY)

    assert outcome.transcript == BODY
    assert outcome.output_url is None


async def test_the_request_carries_the_audio_and_the_options_of_the_job():
    transcriber = ScriptedTranscriber([BODY])
    ports = job_ports(storage=InMemoryStorage({"s3://in/jfk.wav": AUDIO}), transcriber=transcriber)

    await run_job(
        _job(language="es", prompt="AymurAI", response_format="diarized_json"), ports, policy=POLICY
    )

    assert transcriber.calls == [
        {
            "audio": AUDIO,
            "suffix": ".wav",
            "language": "es",
            "prompt": "AymurAI",
            "response_format": "diarized_json",
        }
    ]


async def test_a_busy_coro_is_retried_after_the_wait_it_asks_for():
    clock = FakeClock()
    busy = TransientError("coro answered 429", retry_after_seconds=7.0)
    ports = job_ports(
        storage=InMemoryStorage({"s3://in/jfk.wav": AUDIO}),
        transcriber=ScriptedTranscriber([busy, busy, BODY]),
        clock=clock,
    )

    outcome = await run_job(_job(), ports, policy=POLICY)

    assert outcome.status == "succeeded"
    assert outcome.attempts == 3
    assert clock.sleeps == [7.0, 7.0]


async def test_a_job_that_stays_busy_fails_after_the_last_attempt():
    clock = FakeClock()
    notifier = RecordingNotifier()
    ports = job_ports(
        storage=InMemoryStorage({"s3://in/jfk.wav": AUDIO}),
        transcriber=ScriptedTranscriber([TransientError("down")] * 3),
        notifier=notifier,
        clock=clock,
    )

    outcome = await run_job(_job(), ports, policy=POLICY)

    assert outcome.status == "failed"
    assert outcome.attempts == 3
    assert outcome.error == "down"
    assert clock.sleeps == [5.0, 10.0]
    assert [delivered.status for _, delivered in notifier.delivered] == ["failed"]


async def test_a_refused_request_is_not_retried():
    clock = FakeClock()
    transcriber = ScriptedTranscriber([PermanentError("coro answered 400: not audio")])
    ports = job_ports(
        storage=InMemoryStorage({"s3://in/jfk.wav": AUDIO}), transcriber=transcriber, clock=clock
    )

    outcome = await run_job(_job(), ports, policy=POLICY)

    assert outcome.status == "failed"
    assert outcome.attempts == 1
    assert clock.sleeps == []


async def test_missing_audio_fails_the_job_before_coro_is_called():
    transcriber = ScriptedTranscriber([BODY])
    ports = job_ports(storage=InMemoryStorage(), transcriber=transcriber)

    outcome = await run_job(_job(), ports, policy=POLICY)

    assert outcome.status == "failed"
    assert outcome.attempts == 0
    assert transcriber.calls == []


async def test_a_flaky_receiver_gets_the_callback_on_a_later_attempt():
    notifier = RecordingNotifier([TransientError("receiver answered 503")])
    ports = job_ports(
        storage=InMemoryStorage({"s3://in/jfk.wav": AUDIO}),
        transcriber=ScriptedTranscriber([BODY]),
        notifier=notifier,
    )

    outcome = await run_job(_job(), ports, policy=POLICY)

    assert notifier.delivered == [("https://receiver.test/hook", outcome)]


async def test_an_undeliverable_callback_raises_with_the_outcome():
    notifier = RecordingNotifier([PermanentError("receiver answered 404")])
    ports = job_ports(
        storage=InMemoryStorage({"s3://in/jfk.wav": AUDIO}),
        transcriber=ScriptedTranscriber([BODY]),
        notifier=notifier,
    )

    with pytest.raises(CallbackUndeliveredError) as raised:
        await run_job(_job(), ports, policy=POLICY)

    assert raised.value.outcome.status == "succeeded"


async def test_a_job_without_a_callback_url_reports_to_nobody():
    notifier = RecordingNotifier()
    ports = job_ports(
        storage=InMemoryStorage({"s3://in/jfk.wav": AUDIO}),
        transcriber=ScriptedTranscriber([BODY]),
        notifier=notifier,
    )

    outcome = await run_job(_job(callback_url=None), ports, policy=POLICY)

    assert outcome.status == "succeeded"
    assert notifier.delivered == []
