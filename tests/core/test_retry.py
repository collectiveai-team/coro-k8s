"""RetryPolicy.delay: the wait between two attempts."""

from __future__ import annotations

import pytest

from coro_batch.core.retry import RetryPolicy

POLICY = RetryPolicy(max_attempts=6, base_delay_seconds=5.0, max_delay_seconds=60.0)


@pytest.mark.parametrize(
    ("attempt", "wait"), [(1, 5.0), (2, 10.0), (3, 20.0), (4, 40.0), (5, 60.0)]
)
def test_without_a_hint_the_wait_doubles_up_to_the_cap(attempt, wait):
    assert POLICY.delay(attempt, None) == wait


@pytest.mark.parametrize(("hint", "wait"), [(3.0, 3.0), (0.0, 0.0), (-2.0, 0.0), (3600.0, 60.0)])
def test_the_server_hint_wins_within_the_cap(hint, wait):
    assert POLICY.delay(4, hint) == wait
