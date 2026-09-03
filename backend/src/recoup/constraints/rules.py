"""The individual constraint rules (PRD §12.2).

Each rule is one pure predicate over a proposed action and its work item, returning
a :class:`RuleVerdict` that carries a stable ``rule_id`` and a human-readable
reason. The gate (:mod:`recoup.constraints.gate`) evaluates all of them; nothing
here mints a pass, executes anything, or short-circuits the others.

A rule that does not apply to a given action type still runs and still returns a
verdict — a *passing* one whose reason says the rule was evaluated and found not to
apply. That is deliberate: PRD §8.6 wants the audit log to record that every
constraint was considered, so "the amount cap did not apply to a nudge" is a
recorded fact, not an absence a reader has to infer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from recoup.constraints.base import BreakerState, NullBreaker
from recoup.domain.enums import ActionType, Channel
from recoup.domain.models import Action, FailureContext, WorkItem
from recoup.money import format_inr_paise

__all__ = [
    "AmountCapRule",
    "ChannelAvailableRule",
    "CircuitOpenRule",
    "ConstraintRule",
    "FraudBlockRule",
    "RuleVerdict",
    "RetryCapRule",
    "TerminalStopRule",
    "default_rules",
]

_RETRY_ACTION_TYPES = frozenset(
    {ActionType.SCHEDULED_RETRY, ActionType.BACKOFF_RETRY, ActionType.IMMEDIATE_RETRY}
)
"""Action types that move money by re-presenting a payment through the gateway."""

_MONEY_ACTION_TYPES = _RETRY_ACTION_TYPES | {ActionType.CUSTOMER_NUDGE}
"""Action types that put the full amount back in play — a retry re-presents it, a
nudge sends a payment link for it — and so are subject to the amount cap."""


@dataclass(frozen=True)
class RuleVerdict:
    """One rule's decision about one proposed action.

    ``reason`` is rendered to a person (the dashboard, the audit log), so it names
    the rule and, on a breach, the exact limit or state that failed.
    """

    passed: bool
    rule_id: str
    reason: str


@runtime_checkable
class ConstraintRule(Protocol):
    """A single, pure constraint check. Never mutates, never executes, never raises."""

    rule_id: str

    def evaluate(self, action: Action, item: WorkItem) -> RuleVerdict: ...


def _route_of(item: WorkItem) -> str:
    """The stable ``method:issuer`` route key for ``item``.

    Built through :class:`FailureContext` so the key is byte-for-byte the one the
    circuit breaker (Phase 7) and the retry channel count against — a route the gate
    computed differently from the breaker would let a barred route slip the check.
    """
    return FailureContext(
        failure_code=item.failure_code,
        failure_message=item.failure_message,
        method=item.method,
        issuer=item.issuer,
        failure_type=item.failure_type,
        amount_paise=item.amount_paise,
    ).route


class RetryCapRule:
    """No more than ``max_retries`` retries (PRD §12.2). Applies to retry actions."""

    rule_id = "retry_cap"

    def __init__(self, max_retries: int) -> None:
        self._max_retries = max_retries

    def evaluate(self, action: Action, item: WorkItem) -> RuleVerdict:
        if action.type not in _RETRY_ACTION_TYPES:
            return RuleVerdict(True, self.rule_id, "retry_cap: not a retry action")
        if item.retry_count <= self._max_retries:
            return RuleVerdict(
                True,
                self.rule_id,
                f"retry_cap: {item.retry_count} of {self._max_retries} retries used",
            )
        return RuleVerdict(
            False,
            self.rule_id,
            f"retry_cap: retry {item.retry_count} exceeds the maximum of {self._max_retries}",
        )


class AmountCapRule:
    """Amount at or below ``max_amount_paise`` (PRD §12.2, §12.4).

    Applies to any action that puts the amount back in play. The breach string is a
    demo artifact — ``amount_cap: Rs 75,000 > Rs 50,000`` appears on stage verbatim
    (PRD §16.5) — so it is formatted deliberately and pinned by a test.
    """

    rule_id = "amount_cap"

    def __init__(self, max_amount_paise: int) -> None:
        self._max_amount_paise = max_amount_paise

    def evaluate(self, action: Action, item: WorkItem) -> RuleVerdict:
        if action.type not in _MONEY_ACTION_TYPES:
            return RuleVerdict(True, self.rule_id, "amount_cap: action moves no money")
        if item.amount_paise <= self._max_amount_paise:
            return RuleVerdict(
                True,
                self.rule_id,
                f"amount_cap: {format_inr_paise(item.amount_paise)} within "
                f"{format_inr_paise(self._max_amount_paise)}",
            )
        return RuleVerdict(
            False,
            self.rule_id,
            f"amount_cap: {format_inr_paise(item.amount_paise)} > "
            f"{format_inr_paise(self._max_amount_paise)}",
        )


class FraudBlockRule:
    """A fraud-flagged transaction is never actioned (PRD §12.2, §14). Always applies."""

    rule_id = "fraud_block"

    def evaluate(self, action: Action, item: WorkItem) -> RuleVerdict:
        if not item.fraud_flag:
            return RuleVerdict(True, self.rule_id, "fraud_block: not fraud-flagged")
        return RuleVerdict(
            False,
            self.rule_id,
            "fraud_block: transaction is fraud-flagged and will not be actioned",
        )


class TerminalStopRule:
    """No action on an item already resolved or escalated (PRD §12.2 stopping rule).

    Defense in depth: the state machine already refuses a transition out of a
    terminal state, but the gate is the money door, so it refuses too — the two
    controls are independent on purpose.
    """

    rule_id = "terminal_stop"

    def evaluate(self, action: Action, item: WorkItem) -> RuleVerdict:
        if not item.is_terminal:
            return RuleVerdict(True, self.rule_id, f"terminal_stop: item is {item.state.value}")
        return RuleVerdict(
            False,
            self.rule_id,
            f"terminal_stop: item is already {item.state.value}; no further action",
        )


class CircuitOpenRule:
    """A retry must not target a route whose breaker is open (PRD §11.4, §13.1).

    Constructed with a :class:`~recoup.constraints.base.BreakerState`; defaults to
    :class:`~recoup.constraints.base.NullBreaker`, so with no breaker configured
    every route passes. Phase 7 injects the real breaker with no other change.
    """

    rule_id = "circuit_open"

    def __init__(self, breaker: BreakerState | None = None) -> None:
        self._breaker: BreakerState = breaker if breaker is not None else NullBreaker()

    def evaluate(self, action: Action, item: WorkItem) -> RuleVerdict:
        if action.type not in _RETRY_ACTION_TYPES:
            return RuleVerdict(True, self.rule_id, "circuit_open: not a retry action")
        route = _route_of(item)
        if not self._breaker.is_open(route):
            return RuleVerdict(True, self.rule_id, f"circuit_open: route {route} is available")
        return RuleVerdict(
            False,
            self.rule_id,
            f"circuit_open: route {route} breaker is open; retries are barred",
        )


class ChannelAvailableRule:
    """A nudge must resolve to at least one usable channel (PRD §13.2).

    Constructed with a predicate ``can_reach(item, channel) -> bool`` so the rule
    does not import the channel registry directly — the registry is wired into the
    gate, and the gate hands this rule only the narrow question it needs answered.
    """

    rule_id = "channel_available"

    def __init__(self, can_reach: ChannelReachability) -> None:
        self._can_reach = can_reach

    def evaluate(self, action: Action, item: WorkItem) -> RuleVerdict:
        if action.type is not ActionType.CUSTOMER_NUDGE:
            return RuleVerdict(True, self.rule_id, "channel_available: not a nudge")
        if self._can_reach(item, action.channel):
            return RuleVerdict(
                True,
                self.rule_id,
                f"channel_available: {action.channel.value} can reach the customer",
            )
        return RuleVerdict(
            False,
            self.rule_id,
            f"channel_available: no usable channel to nudge the customer "
            f"(proposed {action.channel.value})",
        )


class ChannelReachability(Protocol):
    """Whether ``channel`` can currently reach ``item``'s customer."""

    def __call__(self, item: WorkItem, channel: Channel) -> bool: ...


def default_rules(
    *,
    max_retries: int,
    max_amount_paise: int,
    breaker: BreakerState | None = None,
    can_reach: ChannelReachability | None = None,
) -> list[ConstraintRule]:
    """The full ordered rule set the gate enforces.

    ``can_reach`` defaults to "any nudge channel is reachable", which keeps the gate
    constructible before any channel exists (Phase 6) while letting Phase 9 wire the
    real registry-backed check in.
    """
    reach: ChannelReachability = can_reach if can_reach is not None else _always_reachable
    return [
        TerminalStopRule(),
        FraudBlockRule(),
        AmountCapRule(max_amount_paise),
        RetryCapRule(max_retries),
        CircuitOpenRule(breaker),
        ChannelAvailableRule(reach),
    ]


def _always_reachable(item: WorkItem, channel: Channel) -> bool:
    return True
