"""Tests for :mod:`recoup.policy.timing`.

The salary-cycle retry is the product's signature India-rooted insight, so the
month-end arithmetic is pinned across 28/29/30/31-day months, and the "never
retry between 20:00 and 10:00 IST" property is swept across a full day of input
hours rather than sampled once. Everything here is pure, so ``now`` is passed in
directly — no clock, no ``time-machine``.
"""

from datetime import datetime, timedelta

import pytest

from recoup.domain.enums import Cause
from recoup.policy.timing import (
    IST,
    RETRY_WINDOW_END_HOUR,
    RETRY_WINDOW_START_HOUR,
    clamp_to_retry_window,
    is_within_retry_window,
    next_retry_at,
)


def _ist(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=IST)


# --- salary-cycle scheduling (insufficient funds) ---------------------------


def test_insufficient_funds_from_midmonth_lands_on_last_day() -> None:
    # Jan has 31 days; from the 15th the sooner salary moment is the 31st.
    result = next_retry_at(Cause.INSUFFICIENT_FUNDS, attempt=0, now=_ist(2026, 1, 15))
    assert (result.year, result.month, result.day) == (2026, 1, 31)
    assert result.hour == RETRY_WINDOW_START_HOUR  # clamped into the window


def test_insufficient_funds_on_last_day_rolls_to_first_of_next_month() -> None:
    # Today *is* the last day, so this month's month-end has already arrived;
    # the next salary moment is the 1st of next month.
    result = next_retry_at(Cause.INSUFFICIENT_FUNDS, attempt=0, now=_ist(2026, 1, 31))
    assert (result.year, result.month, result.day) == (2026, 2, 1)


def test_insufficient_funds_february_non_leap() -> None:
    # 2026 is not a leap year: Feb has 28 days. From the 28th (last day) -> Mar 1.
    result = next_retry_at(Cause.INSUFFICIENT_FUNDS, attempt=0, now=_ist(2026, 2, 28))
    assert (result.year, result.month, result.day) == (2026, 3, 1)


def test_insufficient_funds_february_leap_year() -> None:
    # 2028 is a leap year: Feb has 29 days. From the 29th (last day) -> Mar 1.
    result = next_retry_at(Cause.INSUFFICIENT_FUNDS, attempt=0, now=_ist(2028, 2, 29))
    assert (result.year, result.month, result.day) == (2028, 3, 1)


def test_insufficient_funds_december_rolls_over_the_year() -> None:
    result = next_retry_at(Cause.INSUFFICIENT_FUNDS, attempt=0, now=_ist(2026, 12, 31))
    assert (result.year, result.month, result.day) == (2027, 1, 1)


@pytest.mark.parametrize("day", [1, 5, 15, 29])
def test_insufficient_funds_before_month_end_targets_this_month_end(day: int) -> None:
    # April has 30 days; any day before the 30th targets the 30th.
    result = next_retry_at(Cause.INSUFFICIENT_FUNDS, attempt=0, now=_ist(2026, 4, day))
    assert (result.month, result.day) == (4, 30)


# --- the retry window -------------------------------------------------------


@pytest.mark.parametrize("hour", list(range(24)))
def test_no_retry_is_ever_scheduled_outside_the_window(hour: int) -> None:
    """Sweep every hour of the day: a gateway-degradation retry (which adds only a
    small backoff to ``now``) must always land inside 10:00-20:00 IST."""
    now = _ist(2026, 6, 10, hour=hour, minute=30)
    result = next_retry_at(Cause.GATEWAY_DEGRADATION, attempt=0, now=now)
    assert RETRY_WINDOW_START_HOUR <= result.hour < RETRY_WINDOW_END_HOUR


def test_pre_dawn_target_moves_to_1000_same_day() -> None:
    assert clamp_to_retry_window(_ist(2026, 6, 10, hour=2)).hour == RETRY_WINDOW_START_HOUR
    assert clamp_to_retry_window(_ist(2026, 6, 10, hour=2)).day == 10


def test_evening_target_moves_to_1000_next_day() -> None:
    clamped = clamp_to_retry_window(_ist(2026, 6, 10, hour=21))
    assert clamped.hour == RETRY_WINDOW_START_HOUR
    assert clamped.day == 11


def test_exactly_2000_is_outside_the_window_and_moves_to_next_day() -> None:
    clamped = clamp_to_retry_window(_ist(2026, 6, 10, hour=20, minute=0))
    assert clamped.day == 11
    assert is_within_retry_window(_ist(2026, 6, 10, hour=20)) is False


def test_1000_is_inside_the_window() -> None:
    assert is_within_retry_window(_ist(2026, 6, 10, hour=10, minute=0)) is True


def test_midwindow_target_is_returned_unchanged() -> None:
    dt = _ist(2026, 6, 10, hour=14, minute=37)
    assert clamp_to_retry_window(dt) == dt


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        is_within_retry_window(datetime(2026, 6, 10, 14, 0))


# --- backoff (gateway degradation) ------------------------------------------


def test_backoff_grows_exponentially_with_attempt() -> None:
    now = _ist(2026, 6, 10, hour=11)
    deltas = [
        (next_retry_at(Cause.GATEWAY_DEGRADATION, attempt=a, now=now) - now).total_seconds()
        for a in range(4)
    ]
    # Strictly increasing while under the cap; each roughly doubles (plus jitter).
    assert deltas[0] < deltas[1] < deltas[2] < deltas[3]
    assert deltas[1] >= deltas[0] * 1.5


def test_backoff_is_deterministic_for_the_same_inputs() -> None:
    now = _ist(2026, 6, 10, hour=11)
    a = next_retry_at(Cause.GATEWAY_DEGRADATION, attempt=3, now=now)
    b = next_retry_at(Cause.GATEWAY_DEGRADATION, attempt=3, now=now)
    assert a == b


def test_backoff_is_capped_at_one_hour() -> None:
    now = _ist(2026, 6, 10, hour=11)
    # attempt=20 -> 60 * 2**20 seconds uncapped; must cap at 3600s (still in window).
    result = next_retry_at(Cause.GATEWAY_DEGRADATION, attempt=20, now=now)
    assert (result - now).total_seconds() <= 3600


# --- soft decline & guards --------------------------------------------------


def test_soft_decline_uses_a_short_fixed_delay() -> None:
    now = _ist(2026, 6, 10, hour=11)
    result = next_retry_at(Cause.SOFT_DECLINE, attempt=0, now=now)
    assert result - now == timedelta(minutes=5)


@pytest.mark.parametrize(
    "cause",
    [Cause.EXPIRED_INSTRUMENT, Cause.FRAUD_FLAGGED, Cause.UNKNOWN],
)
def test_non_retryable_causes_raise(cause: Cause) -> None:
    with pytest.raises(ValueError, match="not a retryable cause"):
        next_retry_at(cause, attempt=0, now=_ist(2026, 6, 10))
