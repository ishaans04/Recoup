"""The shared data model (PRD sections 10.1 and 10.2).

Every layer speaks in these types: ingestion produces a :class:`WorkItem`, the
diagnosis engine attaches a :class:`Diagnosis`, the policy proposes an
:class:`Action`, the constraint gate approves or refuses it, a recovery channel
returns a :class:`ChannelResult`, and every one of those steps appends an
:class:`AuditEvent`.

Two invariants are enforced here rather than trusted to callers, because both are
the kind of bug that is invisible until it costs money:

**Money is integer paise.** The PRD models an ``amount`` in rupees; this codebase
stores ``amount_paise`` instead. :data:`PaiseInt` is strict, so a float is rejected
outright rather than silently truncated — ``249.99`` becoming ``249`` would be a
one-rupee loss per transaction that no test would notice.

**Timestamps are timezone-aware.** Retry scheduling compares a stored
``scheduled_for`` against the clock's ``now()``. Python raises ``TypeError`` when
those two disagree about awareness, so a naive datetime entering the model would
surface as a crash deep inside the scheduler. It is rejected at the boundary.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
)

from recoup.domain.enums import (
    TERMINAL_STATES,
    ActionType,
    Cause,
    Channel,
    FailureType,
    State,
)

__all__ = [
    "Action",
    "AuditEvent",
    "AwareDatetime",
    "ChannelResult",
    "Confidence",
    "Customer",
    "Diagnosis",
    "ExecutionResult",
    "FailureContext",
    "NonEmptyStr",
    "PaiseInt",
    "RecoupModel",
    "WorkItem",
]

_MISSING_ROUTE_PART = "unknown"
"""Substituted into :attr:`FailureContext.route` when a part is absent."""

_PAISE_PER_RUPEE = 100


def _require_non_empty(value: str) -> str:
    """Reject a blank string.

    PRD section 11.1 requires every diagnosis to carry a rationale into the audit
    log. A rationale of ``""`` or ``"   "`` satisfies the type but defeats the
    purpose: an audit row nobody can read does not prove anything.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be empty or whitespace only")
    return stripped


def _require_aware(value: datetime) -> datetime:
    """Reject a naive datetime.

    Recoup schedules work into the future and compares those times against an
    injected clock that always returns an Asia/Kolkata-aware datetime. Mixing a
    naive value in raises ``TypeError`` at comparison time, far from the cause.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("must be timezone-aware")
    return value


NonEmptyStr = Annotated[str, AfterValidator(_require_non_empty)]
"""A string that is stripped and must retain at least one character."""

AwareDatetime = Annotated[datetime, AfterValidator(_require_aware)]
"""A datetime that must carry a usable timezone offset."""

PaiseInt = Annotated[StrictInt, Field(ge=0)]
"""Money, as a non-negative integer number of paise.

Strict on purpose: pydantic would otherwise coerce ``249.99`` to ``249`` and lose a
rupee without complaint. A float amount is a bug in the caller, so it raises.
"""

CountInt = Annotated[StrictInt, Field(ge=0)]
"""A non-negative counter. Strict for the same reason as :data:`PaiseInt`."""

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
"""A probability. The one place a float is correct — it is not money."""


class RecoupModel(BaseModel):
    """Base for every domain model.

    ``extra="forbid"`` turns a mistyped field name into an error at construction
    instead of a silently dropped value, which matters most when normalising a
    third-party webhook payload. ``validate_assignment`` re-runs validation on
    mutation, so the orchestrator incrementing ``retry_count`` cannot push it
    negative or make it a float.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Customer(RecoupModel):
    """Who to reach, and how (PRD section 10.1).

    Both contact fields are optional because a merchant's records are frequently
    incomplete. That is exactly why :attr:`has_contact` exists: the nudge channels
    must be able to ask, rather than discover it by failing to send.
    """

    name: str
    phone: str | None = None
    email: str | None = None

    @property
    def has_contact(self) -> bool:
        """Whether any nudge channel could reach this customer at all.

        A customer with no phone and no email cannot be nudged, so an
        ``expired_instrument`` failure for them has no recovery path but the human
        queue. The policy needs to know that before it proposes a nudge.
        """
        return bool((self.phone or "").strip() or (self.email or "").strip())


class Diagnosis(RecoupModel):
    """Why a payment failed, and how sure we are (PRD sections 10.1 and 11).

    Produced by the Tier-1 rules table or the Tier-2 LLM, consumed by the policy
    and the gate, and rendered on the dashboard. ``source`` records which tier
    decided, which is what lets the audit trail distinguish a deterministic
    classification from a model's judgement.
    """

    cause: Cause
    confidence: Confidence
    rationale: NonEmptyStr
    source: Literal["rules", "llm", "fallback"]
    """``rules`` for a deterministic table match, ``llm`` for a Tier-2
    classification, ``fallback`` when neither could decide and the safe default
    was taken."""


class Action(RecoupModel):
    """A proposed intervention (PRD section 10.3).

    An ``Action`` is a *proposal* until the constraint gate approves it. Nothing in
    this model asserts that it may be executed; that authority belongs to the gate
    alone.
    """

    type: ActionType
    channel: Channel
    scheduled_for: AwareDatetime | None = None
    """When to execute. ``None`` means now; a value defers to the scheduler."""

    attempt: CountInt = 0
    """Which attempt this is, counting from zero. Checked against the retry cap."""

    reason: NonEmptyStr
    """Human-readable justification, carried into the audit log."""


class FailureContext(RecoupModel):
    """What is known about a failure, as handed to the diagnosis engine.

    This is deliberately narrower than a :class:`WorkItem`: it carries no customer,
    no merchant and no identifiers. The Tier-2 prompt is built from this object, so
    keeping personal data out of it keeps personal data out of the LLM call.
    """

    failure_code: str
    failure_message: str
    method: str | None = None
    issuer: str | None = None
    failure_type: FailureType
    amount_paise: PaiseInt

    @property
    def route(self) -> str:
        """The stable ``method:issuer`` key this failure travelled over.

        The circuit breaker counts failures per route, so the key must be stable
        across payloads that describe the same route differently. Missing parts
        become ``unknown`` — a route half-identified is still a route, and folding
        every partial payload into one key would let one unknown issuer trip the
        breaker for another. Case and surrounding whitespace are normalised so
        ``HDFC`` and ``hdfc`` are not counted as two separate routes.
        """
        method = (self.method or "").strip().lower() or _MISSING_ROUTE_PART
        issuer = (self.issuer or "").strip().lower() or _MISSING_ROUTE_PART
        return f"{method}:{issuer}"


class ChannelResult(RecoupModel):
    """What a recovery channel reports back.

    Distinct from :class:`ExecutionResult` on purpose. A channel knows two separate
    things and must be able to say both: whether it *delivered* — the SMS was sent,
    the call connected, the retry reached the gateway — and whether that delivery
    *recovered the money*. A nudge that is delivered perfectly recovers nothing at
    the moment it is sent, and reporting that as a failure would understate the
    channel while overstating the loss.
    """

    delivered: bool
    """Whether the channel completed its own job."""

    recovered: bool
    """Whether the payment was actually collected. Only a retry can set this true
    at execution time; a nudge recovers money later, or never."""

    detail: NonEmptyStr
    """What happened, in words, for the audit log."""

    provider_ref: str | None = None
    """The upstream identifier — message SID, call SID, payment id — that makes the
    claim checkable against the provider's own records."""

    channel: Channel | None = None
    """The channel that actually acted, set when a router tried several and one
    delivered. ``None`` when the caller already knows which channel ran (the executor
    then uses the resolved channel's own name)."""


class ExecutionResult(RecoupModel):
    """What the executor reports after gating, running and recording an action.

    Deliberately not the same type as :class:`ChannelResult`. This is the executor's
    verdict on a whole attempt, after the gate has passed it and the audit row has
    been written, and it is the value the orchestrator uses to decide the next
    state. It carries the channel that was ultimately used, which the executor
    chooses and the channel itself does not know.
    """

    recovered: bool
    """Whether the money was collected by this attempt."""

    channel: Channel
    """The channel the executor actually used, which may differ from the one the
    policy first proposed if the registry resolved a fallback."""

    detail: NonEmptyStr
    """What happened, in words, for the audit log."""

    provider_ref: str | None = None
    """The upstream identifier, carried through from the channel."""


class WorkItem(RecoupModel):
    """One failed payment, as it moves through the state machine (PRD section 10.1).

    This is the unit of work the whole system is organised around. It is created by
    ingestion in :attr:`State.DETECTED` and is finished only when it reaches
    :attr:`State.RESOLVED` or :attr:`State.ESCALATED`.
    """

    txn_id: str
    """The PSP's payment identifier. Unique."""

    event_id: str
    """The webhook event identifier. The idempotency key: a delivery seen twice
    never starts a second recovery."""

    merchant_id: str
    amount_paise: PaiseInt
    currency: Literal["INR"] = "INR"
    failure_code: str
    """The raw failure code from the PSP, unmodified."""

    failure_message: str
    """The raw failure description from the PSP, unmodified."""

    failure_type: FailureType
    method: str | None = None
    """The instrument used — ``card``, ``upi``, ``netbanking``. Part of the breaker route."""

    issuer: str | None = None
    """The issuing bank or network. Part of the breaker route."""

    customer: Customer
    fraud_flag: bool = False
    """Set by the PSP or the merchant. A hard block: no money action is permitted."""

    created_at: AwareDatetime
    state: State = State.DETECTED
    retry_count: CountInt = 0
    diagnosis: Diagnosis | None = None
    action: Action | None = None

    @property
    def amount_rupees(self) -> Decimal:
        """The amount in rupees, for display only.

        Returns a :class:`~decimal.Decimal` rather than a float so that dividing by
        100 stays exact. Nothing in the system should compute with this value; the
        integer :attr:`amount_paise` is the number of record.
        """
        return Decimal(self.amount_paise) / _PAISE_PER_RUPEE

    @property
    def is_terminal(self) -> bool:
        """Whether this work item is finished and must not be acted on again.

        This is PRD section 12.2's stopping rule. The gate consults it, so
        "no further action after RESOLVED or ESCALATED" holds for every caller
        rather than for the ones that remembered to check.
        """
        return self.state in TERMINAL_STATES


class AuditEvent(RecoupModel):
    """One append-only record of a state transition (PRD section 10.2).

    Rows are inserted and never updated or deleted. Together they are the proof
    that every money action passed the gate, so the fields that describe *why*
    something happened are as load-bearing as the ones that describe *what*.
    """

    id: int | None = None
    """Assigned by the store on insert; ``None`` before the row exists. Also the
    cursor for ``GET /api/audit?since_id=`` and for WebSocket backfill."""

    timestamp: AwareDatetime
    txn_id: str
    from_state: State | None = None
    """``None`` only on a work item's first event, where there is no prior state."""

    to_state: State
    diagnosis_cause: Cause | None = None
    diagnosis_confidence: Confidence | None = None
    action_chosen: ActionType | None = None
    constraint_result: Literal["PASS", "FAIL"] | None = None
    """``None`` when the transition did not involve the gate."""

    constraint_reason: str | None = None
    """Which constraint decided, and against what limit. Populated on every gate
    evaluation, including the passes — a gate that only explains its refusals
    cannot prove it evaluated anything else."""

    outcome: str | None = None
    """The result of an execution, when this transition recorded one."""

    rationale: NonEmptyStr
    """Why this transition happened. Never empty: an audit row without a reason
    records that something occurred but not that it was justified, which is the
    only thing the log exists to show."""
