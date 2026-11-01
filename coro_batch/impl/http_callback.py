"""The Notifier adapter: a signed JSON POST to the callback URL of a job.

The body is the :class:`~coro_batch.core.models.JobOutcome` as JSON. With a key,
two headers let the receiver check it came from this worker and is fresh:

- ``X-Coro-Batch-Timestamp``: Unix seconds when it was signed.
- ``X-Coro-Batch-Signature``: ``sha256=`` and the hex HMAC-SHA256 of
  ``"<timestamp>.<body>"`` under the key.

A job can be delivered more than once (a retried delivery whose first answer
was lost), so a receiver deduplicates on ``job_id``.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import TYPE_CHECKING

import httpx

from coro_batch.core.errors import PermanentError, TransientError

if TYPE_CHECKING:
    from coro_batch.core.models import JobOutcome
    from coro_batch.core.ports import Clock

SIGNATURE_HEADER = "X-Coro-Batch-Signature"
TIMESTAMP_HEADER = "X-Coro-Batch-Timestamp"


def sign(body: bytes, *, timestamp: str, key: bytes) -> str:
    """Return the signature header value of ``body`` signed at ``timestamp``."""
    digest = hmac.new(key, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class HttpCallbackNotifier:
    """POSTs the outcome of a job as JSON, signed when a key is configured."""

    def __init__(self, client: httpx.AsyncClient, *, clock: Clock, key: bytes | None) -> None:
        """Create the adapter.

        Args:
            client: The HTTP client.
            clock: Stamps the signature.
            key: HMAC key; None sends unsigned callbacks.

        """
        self._client = client
        self._clock = clock
        self._key = key

    async def notify(self, callback_url: str, outcome: JobOutcome) -> None:
        """POST ``outcome`` to ``callback_url``.

        Raises:
            PermanentError: The receiver answered 4xx other than 408 and 429.
            TransientError: The receiver did not answer, or answered 408, 429 or 5xx.

        """
        body = outcome.model_dump_json().encode()
        headers = {"Content-Type": "application/json"}
        if self._key is not None:
            timestamp = str(int(self._clock.now().timestamp()))
            headers[TIMESTAMP_HEADER] = timestamp
            headers[SIGNATURE_HEADER] = sign(body, timestamp=timestamp, key=self._key)
        try:
            response = await self._client.post(callback_url, content=body, headers=headers)
        except httpx.TransportError as exc:
            msg = f"callback receiver did not answer: {exc!r}"
            raise TransientError(msg) from exc
        if response.is_success:
            return
        detail = f"callback receiver answered {response.status_code}"
        if response.status_code in {408, 429} or response.is_server_error:
            raise TransientError(detail)
        raise PermanentError(detail)
