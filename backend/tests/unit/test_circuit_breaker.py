"""Tests for :class:`recoup.gateways.circuit_breaker.CircuitBreaker` (PRD §11.4, §13.1).

The properties that matter: it trips only after enough *consecutive* failures on one
route, it isolates routes (a degraded issuer never bars a healthy one), it ages on
the injected clock (so the Phase 8 fast-forward works), and half-open recovery
behaves canonically — a trial is allowed through, successes close it, one failure
reopens it.
"""

from datetime import timedelta

import pytest

from recoup.clock import SimulatedClock
from recoup.gateways.circuit_breaker import BreakerStatus, CircuitBreaker
from tests.conftest import CREATED_AT

_ROUTE = "card:hdfc"
_OTHER = "upi:sbi"


def _breaker(**kwargs: int) -> tuple[CircuitBreaker, SimulatedClock]:
    clock = SimulatedClock(start=CREATED_AT)
    defaults = {"failure_threshold": 3, "cooldown_seconds": 300, "half_open_successes": 2}
    defaults.update(kwargs)
    return CircuitBreaker(clock=clock, **defaults), clock  # type: ignore[arg-type]


def test_opens_after_threshold_consecutive_failures() -> None:
    breaker, _ = _breaker(failure_threshold=3)
    breaker.record_failure(_ROUTE)
    breaker.record_failure(_ROUTE)
    assert breaker.is_open(_ROUTE) is False
    breaker.record_failure(_ROUTE)
    assert breaker.is_open(_ROUTE) is True
    assert breaker.status(_ROUTE) is BreakerStatus.OPEN


def test_a_success_resets_the_failure_count() -> None:
    breaker, _ = _breaker(failure_threshold=3)
    breaker.record_failure(_ROUTE)
    breaker.record_failure(_ROUTE)
    breaker.record_success(_ROUTE)  # intermittent failure, now cleared
    breaker.record_failure(_ROUTE)
    breaker.record_failure(_ROUTE)
    assert breaker.is_open(_ROUTE) is False  # only 2 consecutive since the reset


def test_routes_are_isolated() -> None:
    breaker, _ = _breaker(failure_threshold=2)
    breaker.record_failure(_ROUTE)
    breaker.record_failure(_ROUTE)
    assert breaker.is_open(_ROUTE) is True
    assert breaker.is_open(_OTHER) is False  # a different route is untouched


def test_transitions_to_half_open_only_after_cooldown() -> None:
    breaker, clock = _breaker(failure_threshold=1, cooldown_seconds=300)
    breaker.record_failure(_ROUTE)
    assert breaker.is_open(_ROUTE) is True

    clock.advance(timedelta(seconds=299))
    assert breaker.is_open(_ROUTE) is True  # not yet

    clock.advance(timedelta(seconds=1))
    assert breaker.is_open(_ROUTE) is False  # cooldown elapsed -> half-open
    assert breaker.status(_ROUTE) is BreakerStatus.HALF_OPEN


def test_half_open_closes_after_enough_successes() -> None:
    breaker, clock = _breaker(failure_threshold=1, cooldown_seconds=60, half_open_successes=2)
    breaker.record_failure(_ROUTE)
    clock.advance(timedelta(seconds=60))
    assert breaker.status(_ROUTE) is BreakerStatus.HALF_OPEN

    breaker.record_success(_ROUTE)
    assert breaker.status(_ROUTE) is BreakerStatus.HALF_OPEN  # one of two
    breaker.record_success(_ROUTE)
    assert breaker.status(_ROUTE) is BreakerStatus.CLOSED


def test_half_open_reopens_on_a_single_failure() -> None:
    breaker, clock = _breaker(failure_threshold=1, cooldown_seconds=60)
    breaker.record_failure(_ROUTE)
    clock.advance(timedelta(seconds=60))
    assert breaker.status(_ROUTE) is BreakerStatus.HALF_OPEN

    breaker.record_failure(_ROUTE)  # trial failed
    assert breaker.status(_ROUTE) is BreakerStatus.OPEN
    # And the cooldown restarts: still open immediately after.
    assert breaker.is_open(_ROUTE) is True


def test_snapshot_reports_every_known_route() -> None:
    breaker, _ = _breaker(failure_threshold=1)
    breaker.record_failure(_ROUTE)
    breaker.record_success(_OTHER)
    snap = breaker.snapshot()
    assert snap[_ROUTE] is BreakerStatus.OPEN
    assert snap[_OTHER] is BreakerStatus.CLOSED


@pytest.mark.parametrize(
    "bad", [{"failure_threshold": 0}, {"half_open_successes": 0}, {"cooldown_seconds": -1}]
)
def test_invalid_configuration_is_rejected(bad: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        _breaker(**bad)
