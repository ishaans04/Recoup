"""The closed vocabulary of the recovery state machine.

These strings are contract, not implementation detail. They are written verbatim
into the append-only audit log (PRD section 10.2), returned verbatim over the REST
and WebSocket APIs, and rendered verbatim on the dashboard. Changing a value
invalidates historical audit rows, so treat every member below as frozen and see
``docs/interface-contract.md`` before adding one.

``StrEnum`` is used throughout so that a member compares equal to, serialises as,
and indexes a dict like its plain string value. That is what lets a value cross the
SQLite, JSON and TypeScript boundaries without a conversion layer at each hop.
"""

from enum import StrEnum

__all__ = [
    "TERMINAL_STATES",
    "ActionType",
    "Cause",
    "Channel",
    "FailureType",
    "State",
]


class State(StrEnum):
    """The lifecycle of a single failed payment (PRD section 4).

    Values are uppercase — deliberately unlike every other enum here — because a
    state is the headline of an audit row and of a dashboard badge. The asymmetry
    is documented in the interface contract and is relied on by the frontend.
    """

    DETECTED = "DETECTED"
    """A failed payment has been normalised into a work item. The entry state."""

    DIAGNOSED = "DIAGNOSED"
    """A cause, confidence and rationale have been attached."""

    ACTION_CHOSEN = "ACTION_CHOSEN"
    """The policy has proposed an intervention. Nothing has been executed."""

    CONSTRAINT_CHECKED = "CONSTRAINT_CHECKED"
    """The constraint gate has evaluated the proposed action. The only door."""

    SCHEDULED = "SCHEDULED"
    """The action passed the gate but is deferred to a future time."""

    EXECUTED = "EXECUTED"
    """A recovery channel has run the action. The outcome is recorded next."""

    RESOLVED = "RESOLVED"
    """Terminal. The payment was recovered."""

    ESCALATED = "ESCALATED"
    """Terminal. Routed to the human queue on a constraint breach or exhausted retries."""


class Cause(StrEnum):
    """Why a payment failed, as decided by the diagnosis engine (PRD section 11).

    This is the closed set the LLM is allowed to return. A Tier-2 response naming a
    cause outside it is rejected rather than coerced, because a cause selects a
    money action and an invented cause would select an unbounded one.
    """

    INSUFFICIENT_FUNDS = "insufficient_funds"
    """The instrument is valid but unfunded. Retryable, with timing intelligence."""

    GATEWAY_DEGRADATION = "gateway_degradation"
    """The route is unhealthy, not the customer. Retryable behind a circuit breaker."""

    SOFT_DECLINE = "soft_decline"
    """A transient issuer decline. Retryable once, with a short backoff."""

    EXPIRED_INSTRUMENT = "expired_instrument"
    """Expired card or lapsed mandate. No retry can succeed; the customer must act."""

    FRAUD_FLAGGED = "fraud_flagged"
    """Blocked. No money action is permitted; escalate to a human."""

    UNKNOWN = "unknown"
    """Neither the rules table nor the LLM could classify the failure confidently."""


class ActionType(StrEnum):
    """The bounded set of interventions the policy may propose (PRD section 10.3).

    There is no open-ended "do something" member, and that is the point: the action
    space is enumerated in code, so the set of things Recoup can ever do to a
    customer's money is readable in one screen.
    """

    SCHEDULED_RETRY = "scheduled_retry"
    """Retry at a chosen future time — the salary-cycle retry for unfunded accounts."""

    BACKOFF_RETRY = "backoff_retry"
    """Retry after an exponentially growing delay, guarded by the circuit breaker."""

    IMMEDIATE_RETRY = "immediate_retry"
    """Retry once, now. Reserved for transient soft declines."""

    CUSTOMER_NUDGE = "customer_nudge"
    """Ask the customer to act. The only action for an instrument that cannot work."""

    NO_ACTION = "no_action"
    """Deliberately do nothing. Recorded explicitly so inaction is auditable."""

    ESCALATE = "escalate"
    """Hand to the human queue."""


class Channel(StrEnum):
    """How an action reaches the world (PRD section 8.7).

    Every channel implements one interface, so adding a delivery mechanism never
    touches the orchestrator or the gate.
    """

    PAYMENT_RETRY = "payment_retry"
    """Re-present the payment through the gateway adapter."""

    VOICE = "voice"
    """An outbound call. Reserved for high-value nudges."""

    SMS = "sms"
    """A text nudge."""

    EMAIL = "email"
    """An email nudge."""

    HUMAN_QUEUE = "human_queue"
    """A person. The terminus for everything the system refuses to act on."""


class FailureType(StrEnum):
    """What kind of payment failed. Shapes the nudge copy and the retry policy."""

    SUBSCRIPTION = "subscription"
    """A recurring charge against a mandate."""

    ONE_TIME = "one_time"
    """A single checkout payment."""

    INVOICE = "invoice"
    """A payment against an issued invoice."""


TERMINAL_STATES: frozenset[State] = frozenset({State.RESOLVED, State.ESCALATED})
"""States from which no transition is ever valid.

This is the stopping rule of PRD section 12.2 in data form. The constraint gate
consults it to refuse action on an already-finished work item, so "no further
action after RESOLVED or ESCALATED" is enforced in one place rather than asserted
in several.
"""
