"""Retry timing: when a retryable failure should be tried again (PRD section 11.4).

Every function here is pure. ``next_retry_at`` takes ``now`` as an argument rather
than reading a clock, so a salary-cycle retry a month away is exercised the same
way a test exercises anything else — by passing a value in — and nothing in this
module performs I/O. That is what lets a demo compress a month into a keystroke
(see :mod:`recoup.clock`) and what lets a test sweep a hundred input hours in a
few milliseconds instead of waiting on a scheduler.

Three causes carry timing intelligence, and each embodies a different kind of
patience:

- ``insufficient_funds`` waits for money to plausibly *exist* — the next salary-
  cycle moment, not a fixed delay, because retrying against an unfunded balance at
  2am changes nothing but the failure count (PRD section 11.4, and the
  distinctly India-rooted insight the product leads with).
- ``gateway_degradation`` waits for a struggling *route* to recover, backing off
  exponentially so a retry storm never compounds an outage.
- ``soft_decline`` waits only long enough for a transient issuer hiccup to clear,
  then gives up after one attempt.

All three are then clamped into the retry window: Recoup never dials a customer's
bank, nor re-presents a card, outside 10:00-20:00 IST. A payment retry at 2am is
not merely unhelpful for an unfunded account — it is the kind of thing that makes
a merchant distrust an autonomous system, so the window is enforced structurally
here rather than left to callers to remember.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from recoup.domain.enums import Cause

__all__ = [
    "IST",
    "RETRY_WINDOW_END_HOUR",
    "RETRY_WINDOW_START_HOUR",
    "clamp_to_retry_window",
    "is_within_retry_window",
    "next_retry_at",
]

IST = ZoneInfo("Asia/Kolkata")

RETRY_WINDOW_START_HOUR = 10
"""The retry window opens at 10:00 IST, inclusive."""

RETRY_WINDOW_END_HOUR = 20
"""The retry window closes at 20:00 IST, exclusive — 20:00 itself is outside it."""

_BACKOFF_BASE_SECONDS = 60
"""The delay before the first gateway-degradation retry, before jitter."""

_BACKOFF_CAP_SECONDS = 3600
"""The maximum backoff delay: one hour, however large ``attempt`` grows."""

_BACKOFF_JITTER_MODULUS = 30
"""Deterministic jitter is drawn from ``[0, 30)`` seconds."""

_SOFT_DECLINE_DELAY = timedelta(minutes=5)
"""A soft decline gets one short retry, not an immediate re-presentation."""

_RETRYABLE_CAUSES = (Cause.INSUFFICIENT_FUNDS, Cause.GATEWAY_DEGRADATION, Cause.SOFT_DECLINE)


def _require_aware(value: datetime) -> datetime:
    """Reject a naive datetime rather than silently treating it as local time.

    ``datetime.astimezone`` on a naive value assumes the *host's* local timezone,
    which on a demo laptop is not IST. That would make the retry window's hour
    comparison wrong in a way no exception would ever surface, so it is refused
    explicitly instead.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("must be a timezone-aware datetime")
    return value


def is_within_retry_window(dt: datetime) -> bool:
    """Whether ``dt`` falls inside 10:00-20:00 IST, inclusive of 10:00, exclusive of 20:00.

    ``dt`` is converted to IST before the hour is read, so a caller holding a
    UTC-aware timestamp gets the correct answer without converting it first.
    """
    _require_aware(dt)
    local = dt.astimezone(IST)
    return RETRY_WINDOW_START_HOUR <= local.hour < RETRY_WINDOW_END_HOUR


def clamp_to_retry_window(dt: datetime) -> datetime:
    """The earliest moment at or after ``dt`` that falls inside the retry window.

    A ``dt`` already inside the window is returned unchanged (converted to IST).
    One before 10:00 IST moves to 10:00 the same day; one at or after 20:00 IST
    moves to 10:00 the *next* day — 20:00 itself is already outside the window, so
    it does not clamp back into today.
    """
    _require_aware(dt)
    local = dt.astimezone(IST)
    if local.hour < RETRY_WINDOW_START_HOUR:
        return local.replace(hour=RETRY_WINDOW_START_HOUR, minute=0, second=0, microsecond=0)
    if local.hour >= RETRY_WINDOW_END_HOUR:
        next_day = local + timedelta(days=1)
        return next_day.replace(hour=RETRY_WINDOW_START_HOUR, minute=0, second=0, microsecond=0)
    return local


def _next_salary_cycle_moment(local_now: datetime) -> datetime:
    """The next salary-cycle moment: this month's last day, or next month's 1st.

    "Whichever comes sooner from now" (PRD section 11.4) resolves to a simple
    rule once today's own occurrence is excluded: the last day of the current
    month is the sooner candidate whenever it has not already arrived, because it
    can never be later than next month's 1st. It has "already arrived" exactly
    when today *is* the last day of the month — a payment failing on the 28th of
    a 28-day February must not be rescheduled for later today just because
    today happens to be month-end; it rolls to the 1st of next month instead.

    Handles 28, 29 (including leap-year February), 30 and 31-day months uniformly
    via :func:`calendar.monthrange`, which is the source of truth for how many
    days a given year/month pair has.
    """
    today = local_now.date()
    last_day_num = calendar.monthrange(today.year, today.month)[1]
    last_day_of_month = date(today.year, today.month, last_day_num)

    if last_day_of_month > today:
        target_date = last_day_of_month
    elif today.month == 12:
        target_date = date(today.year + 1, 1, 1)
    else:
        target_date = date(today.year, today.month + 1, 1)

    # Anchored at midnight rather than `local_now`'s own time-of-day: the target
    # *date* must depend only on today's date, not on what hour it currently is.
    # Anchoring to `now`'s time would let a late-evening `now` push the clamp past
    # midnight into a date the salary-cycle rule never chose. Midnight always
    # clamps forward to 10:00 the same calendar day.
    return datetime.combine(target_date, datetime.min.time(), tzinfo=IST)


def _deterministic_jitter_seconds(attempt: int) -> int:
    """A reproducible, non-random spread in ``[0, 30)`` seconds, keyed on ``attempt``.

    Backoff jitter exists to stop synchronized retries from re-colliding, but this
    system's jitter must also be *reproducible*: the same ``(cause, attempt, now)``
    triple has to schedule the same retry time on every call, so the audit log and
    the test suite can both rely on it. A multiplicative hash (Knuth's
    constant, ``2654435761``) spreads consecutive attempts across the range
    without pulling in :mod:`random` or any other non-deterministic source.
    """
    return (attempt * 2_654_435_761) % _BACKOFF_JITTER_MODULUS


def _backoff_delay(attempt: int) -> timedelta:
    """Exponential backoff for a gateway-degradation retry, capped at one hour."""
    if attempt < 0:
        raise ValueError("attempt must not be negative")
    raw_seconds = _BACKOFF_BASE_SECONDS * (2**attempt)
    jittered_seconds = raw_seconds + _deterministic_jitter_seconds(attempt)
    return timedelta(seconds=min(jittered_seconds, _BACKOFF_CAP_SECONDS))


def next_retry_at(cause: Cause, attempt: int, now: datetime) -> datetime:
    """When a retryable ``cause`` should next be attempted, given the ``attempt``-th try.

    Pure and deterministic: no clock is read here, only ``now`` is used, so the
    same inputs always produce the same output. The result is always inside the
    10:00-20:00 IST retry window (see :func:`clamp_to_retry_window`) — Recoup never
    schedules a payment retry, or the wake-up moment for one, outside it.

    Raises :class:`ValueError` for any cause this function does not schedule.
    Only :data:`~recoup.domain.enums.Cause.INSUFFICIENT_FUNDS`,
    :data:`~recoup.domain.enums.Cause.GATEWAY_DEGRADATION` and
    :data:`~recoup.domain.enums.Cause.SOFT_DECLINE` are retryable causes (PRD
    section 10.3); asking this function to schedule anything else — an expired
    instrument, a fraud flag, an unknown cause — is a programming error in the
    caller, not a condition to handle gracefully.
    """
    _require_aware(now)
    local_now = now.astimezone(IST)

    if cause is Cause.INSUFFICIENT_FUNDS:
        target = _next_salary_cycle_moment(local_now)
    elif cause is Cause.GATEWAY_DEGRADATION:
        target = local_now + _backoff_delay(attempt)
    elif cause is Cause.SOFT_DECLINE:
        target = local_now + _SOFT_DECLINE_DELAY
    else:
        raise ValueError(
            f"{cause!r} is not a retryable cause; next_retry_at only schedules "
            f"{[c.value for c in _RETRYABLE_CAUSES]}"
        )

    return clamp_to_retry_window(target)
