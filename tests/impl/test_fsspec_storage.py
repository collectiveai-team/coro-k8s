"""The fsspec adapters over the in-memory and the local filesystems."""

from __future__ import annotations

import re

import fsspec
import pytest

from coro_batch.core.errors import PermanentError
from coro_batch.impl.fsspec_storage import FsspecAudioSource, FsspecResultSink


@pytest.fixture
def memory():
    filesystem = fsspec.filesystem("memory")
    yield filesystem
    filesystem.rm("/", recursive=True)


async def test_audio_is_copied_from_its_url(memory, tmp_path):
    memory.pipe("/in/jfk.wav", b"RIFF" + bytes(20_000_000))
    destination = tmp_path / "audio.wav"

    await FsspecAudioSource().fetch("memory://in/jfk.wav", destination)

    assert destination.stat().st_size == 20_000_004


async def test_missing_audio_is_permanent(memory, tmp_path):
    with pytest.raises(PermanentError, match=re.escape("memory://in/none.wav")):
        await FsspecAudioSource().fetch("memory://in/none.wav", tmp_path / "audio.wav")


async def test_an_unknown_protocol_is_permanent(tmp_path):
    with pytest.raises(PermanentError):
        await FsspecAudioSource().fetch("nosuch://bucket/a.wav", tmp_path / "audio.wav")


async def test_a_transcript_is_written_creating_its_folders(tmp_path):
    target = tmp_path / "out" / "2026" / "job-1.json"

    await FsspecResultSink().store(target.as_uri(), '{"text": "ñandú"}')

    assert target.read_text(encoding="utf-8") == '{"text": "ñandú"}'
