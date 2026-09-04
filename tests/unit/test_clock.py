"""Tests for the injectable clock.

The behaviour that matters is not "advance adds a timedelta" — it is that a single
shared instance moves time for every holder at once. Salary-cycle retries and
breaker cooldowns are only testable because of that.
"""

from datetime import UTC, datetime, timedelta

import pytest

from recoup.clock import IST, Clock, SimulatedClock, SystemClock

START = datetime(2026, 9, 3, 14, 32, 5, tzinfo=IST)


class Scheduler:
    """A stand-in for any component that is handed the clock and keeps it."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def observed_now(self) -> datetime:
        return self._clock.now()


# --------------------------------------------------------------------------- #
# SystemClock
# --------------------------------------------------------------------------- #


def test_system_clock_is_timezone_aware() -> None:
    """A naive datetime would be rejected by every domain model downstream."""
    now = SystemClock().now()

    assert now.tzinfo is not None
    assert now.tzinfo.utcoffset(now) is not None


def test_system_clock_reports_asia_kolkata() -> None:
    now = SystemClock().now()

    assert now.utcoffset() == timedelta(hours=5, minutes=30)


def test_system_clock_advances_on_its_own() -> None:
    clock = SystemClock()

    assert clock.now() <= clock.now()


# --------------------------------------------------------------------------- #
# SimulatedClock
# --------------------------------------------------------------------------- #


def test_simulated_clock_does_not_move_by_itself() -> None:
    """Determinism is the point: two reads with no advance are the same instant."""
    clock = SimulatedClock(START)

    assert clock.now() == clock.now() == START


def test_simulated_clock_is_timezone_aware_in_ist() -> None:
    clock = SimulatedClock(START)

    assert clock.now().utcoffset() == timedelta(hours=5, minutes=30)


def test_advance_moves_time_forward() -> None:
    clock = SimulatedClock(START)

    returned = clock.advance(timedelta(days=27, hours=2))

    assert clock.now() == datetime(2026, 9, 30, 16, 32, 5, tzinfo=IST)
    assert returned == clock.now()


def test_advance_is_observed_by_another_holder_of_the_same_instance() -> None:
    """The scheduler and the breaker share one clock; one advance moves both."""
    clock = SimulatedClock(START)
    scheduler = Scheduler(clock)
    breaker = Scheduler(clock)

    assert scheduler.observed_now() == START
    assert breaker.observed_now() == START

    clock.advance(timedelta(days=27))

    expected = datetime(2026, 9, 30, 14, 32, 5, tzinfo=IST)
    assert scheduler.observed_now() == expected
    assert breaker.observed_now() == expected
    assert scheduler.observed_now() == breaker.observed_now()


def test_advance_accumulates() -> None:
    clock = SimulatedClock(START)

    clock.advance(timedelta(hours=1))
    clock.advance(timedelta(hours=2))
    clock.advance(timedelta(minutes=30))

    assert clock.now() == datetime(2026, 9, 3, 18, 2, 5, tzinfo=IST)


def test_advance_by_zero_is_allowed_and_is_a_no_op() -> None:
    clock = SimulatedClock(START)

    clock.advance(timedelta(0))

    assert clock.now() == START


def test_advance_refuses_to_run_time_backwards() -> None:
    """A backwards clock lets a scheduled action come due twice and makes the audit
    log's timestamps contradict its own ordering."""
    clock = SimulatedClock(START)

    with pytest.raises(ValueError, match="negative"):
        clock.advance(timedelta(seconds=-1))

    assert clock.now() == START


def test_set_places_the_clock_and_is_observed_by_holders() -> None:
    clock = SimulatedClock(START)
    holder = Scheduler(clock)
    target = datetime(2026, 10, 1, 10, 0, tzinfo=IST)

    returned = clock.set(target)

    assert returned == target
    assert clock.now() == target
    assert holder.observed_now() == target


def test_set_may_move_time_backwards() -> None:
    """Unlike advance, set is for arranging a scenario, not for running one."""
    clock = SimulatedClock(START)

    clock.set(datetime(2026, 1, 1, 0, 0, tzinfo=IST))

    assert clock.now() == datetime(2026, 1, 1, 0, 0, tzinfo=IST)


def test_simulated_clock_normalises_a_foreign_timezone_to_ist() -> None:
    """The audit log is single-zone; a UTC start must not leak a UTC timestamp."""
    clock = SimulatedClock(datetime(2026, 9, 3, 9, 2, 5, tzinfo=UTC))

    assert clock.now() == START
    assert clock.now().utcoffset() == timedelta(hours=5, minutes=30)


def test_simulated_clock_rejects_a_naive_start() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        SimulatedClock(datetime(2026, 9, 3, 14, 32, 5))


def test_set_rejects_a_naive_datetime() -> None:
    clock = SimulatedClock(START)

    with pytest.raises(ValueError, match="timezone-aware"):
        clock.set(datetime(2026, 10, 1, 10, 0))

    assert clock.now() == START


# --------------------------------------------------------------------------- #
# Protocol conformance
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("clock", [SystemClock(), SimulatedClock(START)])
def test_both_implementations_satisfy_the_clock_protocol(clock: Clock) -> None:
    """Every collaborator is typed against Clock, so both must be substitutable."""
    assert isinstance(clock, Clock)
    assert clock.now().tzinfo is not None
