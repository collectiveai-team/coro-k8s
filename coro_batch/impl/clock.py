"""The Clock adapter of the running worker: the system time and asyncio.sleep."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime


class SystemClock:
    """Reads the system clock in UTC and waits with ``asyncio.sleep``."""

    def now(self) -> datetime:
        """Return the current UTC time."""
        return datetime.now(tz=UTC)

    async def sleep(self, seconds: float) -> None:
        """Wait ``seconds`` without blocking the event loop."""
        await asyncio.sleep(seconds)
