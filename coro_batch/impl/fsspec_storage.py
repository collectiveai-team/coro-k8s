"""AudioSource and ResultSink adapters over fsspec: S3, GCS, HTTP(S), local files."""

from __future__ import annotations

import asyncio
import shutil
from typing import TYPE_CHECKING, cast

import fsspec

from coro_batch.core.errors import PermanentError, TransientError

if TYPE_CHECKING:
    from pathlib import Path

    from fsspec.core import OpenFile

_COPY_CHUNK_BYTES = 8 * 1024 * 1024


def _classify(url: str, exc: Exception) -> Exception:
    if isinstance(exc, (FileNotFoundError, PermissionError, ValueError, ImportError)):
        return PermanentError(f"{url}: {exc!r}")
    return TransientError(f"{url}: {exc!r}")


def _open(url: str, mode: str, **kwargs: object) -> OpenFile:
    # fsspec.open returns a list of files for a glob URL; these URLs name one object.
    return cast("OpenFile", fsspec.open(url, mode, **kwargs))


def _copy_to_file(url: str, destination: Path) -> None:
    with _open(url, "rb") as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target, _COPY_CHUNK_BYTES)


def _write_text(url: str, text: str) -> None:
    with _open(url, "w", encoding="utf-8", auto_mkdir=True) as target:
        target.write(text)


class FsspecAudioSource:
    """Copies an object at any fsspec URL to a local file, in chunks."""

    async def fetch(self, url: str, destination: Path) -> None:
        """Copy ``url`` to ``destination`` without holding it in memory.

        Raises:
            PermanentError: The object is missing, forbidden, or its protocol is unknown.
            TransientError: Any other failure of the storage.

        """
        try:
            await asyncio.to_thread(_copy_to_file, url, destination)
        # Each fsspec backend raises its own types (aiohttp, botocore), so any failure is
        # classified rather than listed.
        except Exception as exc:
            raise _classify(url, exc) from exc


class FsspecResultSink:
    """Writes a transcript to any fsspec URL as UTF-8 text."""

    async def store(self, url: str, transcript: str) -> None:
        """Write ``transcript`` to ``url``, creating parent folders on local filesystems.

        Raises:
            PermanentError: The location is forbidden or its protocol is unknown.
            TransientError: Any other failure of the storage.

        """
        try:
            await asyncio.to_thread(_write_text, url, transcript)
        # Each fsspec backend raises its own types (aiohttp, botocore), so any failure is
        # classified rather than listed.
        except Exception as exc:
            raise _classify(url, exc) from exc
