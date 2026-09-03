"""The circuit breaker interface, and the always-closed implementation.

PRD section 11.4 requires that when many transactions fail on the same route,
Recoup stops retrying that route rather than hammering a degraded endpoint. The
constraint gate needs to ask "is this route currently barred?" from the moment it
exists, which is phase 6 — but the breaker that can actually answer with counters
and cooldowns is phase 7.

:class:`BreakerState` is that question, and :class:`NullBreaker` is the honest
answer when no breaker is configured: nothing is barred. It is a complete
implementation of a real configuration, not a placeholder standing in for one. A
deployment with no breaker behaves exactly as it did before breakers existed, and
the gate's code path is identical either way — which means phase 7 changes what is
injected and nothing else.
"""

from typing import Protocol, runtime_checkable

__all__ = ["BreakerState", "NullBreaker"]


@runtime_checkable
class BreakerState(Protocol):
    """Whether a payment route is currently barred from further attempts."""

    def is_open(self, route: str) -> bool:
        """``True`` when ``route`` is tripped and must not be retried.

        ``route`` is the stable ``method:issuer`` key produced by
        :attr:`~recoup.domain.models.FailureContext.route`, so both sides of this
        question agree on what a route is without either one constructing the key
        by hand.

        "Open" is the electrical sense, kept because it is the sense the term
        carries in every other payments system: an open circuit conducts nothing.
        An open breaker means stop.

        Must not perform I/O and must not raise. The gate calls this while deciding
        whether money may move, and a breaker that can fail would become a way for
        an action to slip past the check.
        """
        ...


class NullBreaker:
    """A breaker that is never open. The behaviour of "no breaker configured".

    Every route is permitted, which is precisely correct: without failure counters
    there is no evidence that any route is degraded, and barring a route on no
    evidence would stop recoveries that would have succeeded.

    This is not a weakening of the safety story. The breaker is an *availability*
    control — it protects a struggling endpoint from being hammered — while the
    money-safety controls are the retry cap, the amount cap and the fraud block in
    the constraint gate. Those are always enforced, whatever breaker is installed.
    """

    def is_open(self, route: str) -> bool:
        """``False``, always. No route is barred when nothing is counting failures."""
        return False
