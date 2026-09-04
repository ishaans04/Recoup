"""The real circuit breaker (PRD sections 11.4 and 13.1).

Phase 0 declared the question the constraint gate asks — :class:`BreakerState`,
answered by :class:`~recoup.constraints.base.NullBreaker` when nothing is counting
failures. This module supplies the implementation that actually counts them.

Hammering a degraded bank endpoint makes the outage worse for every merchant behind
it. When many transactions on the same route are failing, the correct response is
to stop sending that route traffic for a while, not to retry into a wall. That is a
breaker in the literal, electrical sense: an open circuit conducts nothing. Three
states make the recovery half of that story possible as well as the tripping half:

- ``CLOSED`` — normal operation. Failures are counted; a success resets the count.
- ``OPEN`` — tripped. :meth:`CircuitBreaker.is_open` reports ``True`` and the gate
  refuses further attempts on this route until the cooldown elapses.
- ``HALF_OPEN`` — the cooldown elapsed and a trial is allowed. ``is_open`` reports
  ``False`` here on purpose: a half-open breaker exists to let exactly one kind of
  call through and see whether the route has recovered, not to stay barred forever.

Counters are **kept per route**, where a route is the ``method:issuer`` key from
:attr:`~recoup.domain.models.FailureContext.route`. One degraded issuer must never
block retries to every other bank, so a single shared counter would be wrong even
though it would pass a test that only exercised one route.

The breaker ages **on the injected clock**, never on wall time. Phase 8 fast-forwards
a :class:`~recoup.clock.SimulatedClock` to resolve scheduled retries in the demo, and
a cooldown timer that read ``datetime.now()`` directly would never observe that
advance — the breaker would still look open on stage after the clock said otherwise.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from recoup.clock import Clock

__all__ = ["BreakerStatus", "CircuitBreaker"]


class BreakerStatus(StrEnum):
    """The three canonical circuit-breaker states.

    Lowercase, like every non-``State`` enum in this codebase — this is dashboard
    and log vocabulary, not the audit-row ``State`` machine, so it does not follow
    that enum's uppercase convention.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _RouteCounters:
    """Mutable per-route state. Private: callers only ever see it through the
    breaker's methods, never the object itself."""

    status: BreakerStatus = BreakerStatus.CLOSED
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    opened_at: datetime | None = None
    """When this route most recently tripped to ``OPEN``, on the injected clock.
    ``None`` whenever the route is not ``OPEN`` — there is nothing to cool down
    from."""


class CircuitBreaker:
    """A route-keyed circuit breaker with half-open recovery.

    One instance is shared by the constraint gate (which only ever calls
    :meth:`is_open`, satisfying :class:`~recoup.constraints.base.BreakerState`) and
    by :class:`~recoup.channels.retry.PaymentRetryChannel` (which calls
    :meth:`record_success` and :meth:`record_failure` after every attempt). Sharing
    one instance both ways is what makes the breaker a closed loop: attempts feed
    counters, counters gate future attempts.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        failure_threshold: int = 5,
        cooldown_seconds: int = 300,
        half_open_successes: int = 2,
    ) -> None:
        """Configure the breaker.

        ``failure_threshold`` and ``half_open_successes`` must be at least 1 and
        ``cooldown_seconds`` at least 0 — a breaker that can trip on zero failures
        or never cool down is a misconfiguration worth failing fast on, rather than
        a route that is silently barred forever or never protected at all.
        """
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if half_open_successes < 1:
            raise ValueError("half_open_successes must be at least 1")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must not be negative")

        self._clock = clock
        self._failure_threshold = failure_threshold
        self._cooldown = timedelta(seconds=cooldown_seconds)
        self._half_open_successes = half_open_successes
        self._routes: dict[str, _RouteCounters] = {}

    def _age(self, counters: _RouteCounters) -> None:
        """Move ``OPEN`` to ``HALF_OPEN`` if the cooldown has elapsed on the clock.

        Called at the start of every public method before it reads or writes
        ``counters.status``, so every observer — the gate, the retry channel, the
        dashboard snapshot — sees a status that is current as of *this* tick of the
        injected clock, never a stale ``OPEN`` past its cooldown.
        """
        if (
            counters.status is BreakerStatus.OPEN
            and counters.opened_at is not None
            and self._clock.now() - counters.opened_at >= self._cooldown
        ):
            counters.status = BreakerStatus.HALF_OPEN
            counters.consecutive_successes = 0

    def is_open(self, route: str) -> bool:
        """``True`` only while ``route`` is tripped and cooling down.

        Satisfies :class:`~recoup.constraints.base.BreakerState`, so this class
        drops into the constraint gate exactly where ``NullBreaker`` did. A route
        never seen before is ``CLOSED`` by definition — no failures recorded is no
        evidence of degradation — so this never creates an entry for an unknown
        route; only :meth:`record_success` and :meth:`record_failure` do that.
        """
        counters = self._routes.get(route)
        if counters is None:
            return False
        self._age(counters)
        return counters.status is BreakerStatus.OPEN

    def record_success(self, route: str) -> None:
        """Report that an attempt on ``route`` recovered the money.

        In ``CLOSED``, this resets the consecutive-failure count — an intermittent
        failure surrounded by successes must never accumulate toward tripping. In
        ``HALF_OPEN``, this counts toward ``half_open_successes``; reaching it
        closes the breaker and clears every counter, so a recovered route starts
        clean rather than carrying scar tissue from the outage. A success recorded
        while genuinely ``OPEN`` (the cooldown has not yet elapsed) is a caller
        error — the gate should have refused the attempt — and is treated as a
        no-op rather than as evidence, since an ``OPEN`` breaker issued no trial to
        succeed.
        """
        counters = self._routes.setdefault(route, _RouteCounters())
        self._age(counters)

        if counters.status is BreakerStatus.HALF_OPEN:
            counters.consecutive_successes += 1
            if counters.consecutive_successes >= self._half_open_successes:
                counters.status = BreakerStatus.CLOSED
                counters.consecutive_failures = 0
                counters.consecutive_successes = 0
                counters.opened_at = None
        elif counters.status is BreakerStatus.CLOSED:
            counters.consecutive_failures = 0

    def record_failure(self, route: str) -> None:
        """Report that an attempt on ``route`` failed.

        In ``CLOSED``, this increments the consecutive-failure count and trips the
        breaker to ``OPEN`` once it reaches ``failure_threshold``, starting the
        cooldown from the current clock time. In ``HALF_OPEN``, a single failure is
        conclusive — the trial call did not recover, so the route is not healthy —
        and immediately reopens the breaker with the cooldown restarted from now,
        discarding whatever partial progress toward ``half_open_successes`` had
        been made.
        """
        counters = self._routes.setdefault(route, _RouteCounters())
        self._age(counters)

        if counters.status is BreakerStatus.HALF_OPEN:
            counters.status = BreakerStatus.OPEN
            counters.opened_at = self._clock.now()
            counters.consecutive_successes = 0
        elif counters.status is BreakerStatus.CLOSED:
            counters.consecutive_failures += 1
            if counters.consecutive_failures >= self._failure_threshold:
                counters.status = BreakerStatus.OPEN
                counters.opened_at = self._clock.now()
        # Already OPEN and still cooling down: nothing changes. The cooldown is not
        # restarted by more failures piling up while barred, only by a failed trial
        # in HALF_OPEN — otherwise a hammered-but-barred route could never age out.

    def status(self, route: str) -> BreakerStatus:
        """The current status of ``route``, aged against the clock first.

        Unlike :meth:`is_open`, this distinguishes ``HALF_OPEN`` from ``CLOSED`` —
        the dashboard needs the real state, not just the gate's yes/no question.
        A route never seen before reports ``CLOSED`` without being recorded.
        """
        counters = self._routes.get(route)
        if counters is None:
            return BreakerStatus.CLOSED
        self._age(counters)
        return counters.status

    def snapshot(self) -> dict[str, BreakerStatus]:
        """Every route this breaker has ever recorded an outcome for, and its
        current status.

        This is what the dashboard renders as the breaker panel. Each route is
        aged against the clock before being reported, so a snapshot taken after the
        demo fast-forwards the clock reflects routes that have since recovered
        rather than the status at the moment they tripped.
        """
        for counters in self._routes.values():
            self._age(counters)
        return {route: counters.status for route, counters in self._routes.items()}
