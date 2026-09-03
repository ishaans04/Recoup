"""Injectable time.

Recoup schedules work into the future: an unfunded account is retried near the
salary cycle rather than at 2am (PRD section 11.4), and a tripped circuit breaker
stays open for a cooldown before it half-opens (PRD section 13.1). Neither
behaviour can be tested, nor demonstrated on stage, if the code reads the wall
clock directly — a salary-cycle test would have to wait until the end of the
month.

So nothing in ``recoup`` calls :func:`datetime.datetime.now`. Everything takes a
:class:`Clock` and calls ``clock.now()``. In production that is a
:class:`SystemClock`; in tests and in the demo it is a :class:`SimulatedClock`
that can be moved forward on command.

All times are Asia/Kolkata. The merchants are Indian, the salary-cycle logic is
about Indian pay dates, and an audit log that mixes zones is not evidence of
anything. India observes no daylight saving, so the offset is a constant +05:30,
but the named zone is used anyway rather than a hardcoded offset: the name is
self-documenting in a traceback, and it keeps the choice in one place.
"""

from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

__all__ = ["IST", "Clock", "SimulatedClock", "SystemClock"]

IST = ZoneInfo("Asia/Kolkata")
"""The single timezone of the system. Every datetime Recoup produces carries it."""


@runtime_checkable
class Clock(Protocol):
    """A source of the current time.

    Implementations must return a timezone-aware datetime in :data:`IST`. A naive
    datetime would be rejected by the domain models, which is the intended failure
    mode: a clock that loses its timezone is a broken clock.
    """

    def now(self) -> datetime:
        """The current time, timezone-aware, in Asia/Kolkata."""
        ...


class SystemClock:
    """The real clock. Reads the host time and expresses it in :data:`IST`."""

    def now(self) -> datetime:
        """The current wall-clock time in Asia/Kolkata."""
        return datetime.now(tz=IST)


class SimulatedClock:
    """A clock whose time only changes when it is told to.

    Two properties make this useful beyond ordinary test convenience.

    It is **mutable and shared**. One instance is injected into every collaborator
    — scheduler, breaker, orchestrator, audit writer — so a single
    :meth:`advance` moves time for all of them at once. That is what lets a test
    fast-forward a month and watch a salary-cycle retry fire, and what lets the
    demo compress a cooldown into a keystroke. Holders keep a reference to the
    clock, never a copy of ``now()``.

    It is **monotonic under advance**. :meth:`advance` refuses a negative delta,
    because time running backwards would let a scheduled action come due twice and
    would produce an audit log whose timestamps contradict its own ordering.
    :meth:`set` exists for the one legitimate case — placing the clock at a fixed
    starting point — and is explicit about it.
    """

    def __init__(self, start: datetime) -> None:
        """Start the clock at ``start``, which must be timezone-aware.

        A naive start would silently produce naive times everywhere downstream and
        the failure would surface far from here, so it is refused now.
        """
        self._now = self._normalise(start)

    @staticmethod
    def _normalise(value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("SimulatedClock requires a timezone-aware datetime")
        return value.astimezone(IST)

    def now(self) -> datetime:
        """The simulated current time, timezone-aware, in Asia/Kolkata."""
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        """Move time forward by ``delta`` and return the new time.

        Every holder of this instance observes the change immediately, which is the
        whole point of sharing one clock rather than passing timestamps around.
        """
        if delta < timedelta(0):
            raise ValueError("SimulatedClock cannot advance by a negative timedelta")
        self._now = self._now + delta
        return self._now

    def set(self, dt: datetime) -> datetime:
        """Place the clock at ``dt`` and return it.

        Unlike :meth:`advance` this may move time backwards, so it is for setting
        up a scenario, not for running one.
        """
        self._now = self._normalise(dt)
        return self._now
