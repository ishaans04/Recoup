"""The orchestrator: drives one work item through the recovery lifecycle.

PRD section 8.2: the orchestrator "never calls external services directly — it
invokes L2/L4/L6 components." This module honours that literally. It imports
nothing from :mod:`recoup.gateways`, :mod:`recoup.channels` or
:mod:`recoup.diagnosis`, and calls no LLM, gateway or channel SDK. Everything it
needs from those layers arrives through :class:`OrchestratorDeps` — three injected
callables the orchestrator treats as opaque. ``test_orchestrator.py`` asserts this
by inspecting the module's own imports, not only by trusting the docstring.

That is also why the callables are dependency injection rather than stubs: this
module is a complete, tested implementation of the routing policy in PRD section
7.4 today, against fakes that stand in for collaborators later phases will supply
for real (diagnosis in Phase 4, the constraint gate and executor in Phase 6). Only
the *implementation* of ``diagnose``/``select_action``/``check_and_execute`` is
deferred; the orchestrator that calls them is not.

**Bridging ``GateOutcome`` across two audited states.** PRD section 7.4 lists the
constraint check (step 5, state ``CONSTRAINT_CHECKED``) and the execution (step 6,
state ``EXECUTED``) as two separate, separately-audited transitions, and
:meth:`Orchestrator.advance` is documented to drive exactly one transition per call
— so a work item genuinely sits in ``CONSTRAINT_CHECKED`` between them, visible to
any other caller. But ``check_and_execute`` is called exactly once per real attempt
(calling it twice would mean gating — or worse, executing — the same action
twice), during the ``ACTION_CHOSEN`` step, and its :class:`GateOutcome` is what both
the immediately-following ``CONSTRAINT_CHECKED`` step *and* the later ``EXECUTED``
step need in order to decide where to go next. Threading that outcome through the
``WorkItem`` itself is not an option — the domain model is closed
(``extra="forbid"``) and deliberately carries no scratch field for it. So the
orchestrator keeps a small, private, in-memory map from ``txn_id`` to the
``GateOutcome`` that produced its current pending decision, alive for exactly the
one or two subsequent :meth:`advance` calls that consume it, then discarded. This is
process-local, not persisted: the durable record of *what the gate decided* is
already the ``constraint_result``/``constraint_reason``/``outcome`` written to the
audit log by each real transition, so nothing about the audit trail's completeness
depends on this cache surviving a restart — only the orchestrator's ability to
resume an item that was left mid-lifecycle when the process stopped does, and this
build's batch-oriented usage (:meth:`Orchestrator.run_to_completion` drives one item
to a terminal state within a single call) never leaves that gap open in practice.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from recoup.clock import Clock
from recoup.domain.enums import State
from recoup.domain.models import Action, Diagnosis, WorkItem
from recoup.fsm.machine import StateMachine, TerminalStateError
from recoup.fsm.states import is_terminal

__all__ = ["GateOutcome", "Orchestrator", "OrchestratorDeps"]

_ConstraintResult = Literal["PASS", "FAIL"]


@dataclass(frozen=True, slots=True)
class GateOutcome:
    """What one call to ``check_and_execute`` decided and, if it ran, what happened.

    Phase 6 constructs this; this phase only defines its shape and routes on it.
    """

    executed: bool
    """Whether the recovery channel actually ran. ``False`` when the gate refused
    the action, or when the action's ``scheduled_for`` is still in the future and
    execution was deliberately deferred rather than attempted."""

    recovered: bool
    """Whether this execution collected the money. Always ``False`` when
    ``executed`` is ``False``."""

    escalate_reason: str | None
    """Set when this outcome means "stop trying and hand this to a human" — a
    constraint breach, or (after an unsuccessful execution) an exhausted retry
    budget. ``None`` when the work item should keep moving through the lifecycle."""

    constraint_result: _ConstraintResult
    """The gate's verdict on this attempt. Recorded on every evaluation, not only
    refusals (PRD section 8.6)."""

    constraint_reason: str
    """Which constraint decided, and against what limit or state."""

    outcome_detail: str | None
    """A human-readable account of what the execution did, for the audit log.
    ``None`` when nothing has executed yet (a refusal, or a deferred action)."""


@dataclass
class OrchestratorDeps:
    """The three collaborators the orchestrator drives without ever importing them.

    ``diagnose`` and ``check_and_execute`` are asynchronous because their real
    implementations do I/O (an LLM call; a gateway or channel call). ``select_action``
    is synchronous because choosing an intervention from an already-known cause is
    a pure policy lookup (Phase 5) with nothing to await.
    """

    diagnose: Callable[[WorkItem], Awaitable[Diagnosis]]
    select_action: Callable[[WorkItem, Diagnosis], Action]
    check_and_execute: Callable[[WorkItem, Action], Awaitable[GateOutcome]]


class Orchestrator:
    """Drives a work item through :mod:`recoup.fsm.states`, one transition at a time."""

    def __init__(self, machine: StateMachine, deps: OrchestratorDeps, clock: Clock) -> None:
        self._machine = machine
        self._deps = deps
        self._clock = clock
        self._pending_outcomes: dict[str, GateOutcome] = {}

    async def advance(self, item: WorkItem) -> WorkItem:
        """Drive exactly one state transition. Returns the updated item.

        The one documented exception is a work item parked in ``SCHEDULED`` whose
        ``action.scheduled_for`` has not yet arrived: no transition is legal yet, so
        ``item`` is returned unchanged. That is the parking behaviour PRD sections
        11.4 and 13.1 require, not an error.

        Raises:
            TerminalStateError: ``item.state`` is ``RESOLVED`` or ``ESCALATED``.
        """
        state = item.state

        if state is State.DETECTED:
            diagnosis = await self._deps.diagnose(item)
            return self._machine.transition(
                item,
                State.DIAGNOSED,
                rationale=(
                    f"diagnosed as {diagnosis.cause.value} via {diagnosis.source} "
                    f"(confidence {diagnosis.confidence:.2f}): {diagnosis.rationale}"
                ),
                diagnosis=diagnosis,
            )

        if state is State.DIAGNOSED:
            existing_diagnosis = item.diagnosis
            if existing_diagnosis is None:
                raise RuntimeError(
                    f"{item.txn_id} is DIAGNOSED but carries no diagnosis; "
                    "this violates the orchestrator's own invariant"
                )
            chosen_action = self._deps.select_action(item, existing_diagnosis)
            return self._machine.transition(
                item,
                State.ACTION_CHOSEN,
                rationale=(
                    f"selected {chosen_action.type.value} via {chosen_action.channel.value}: "
                    f"{chosen_action.reason}"
                ),
                action=chosen_action,
            )

        if state is State.ACTION_CHOSEN:
            existing_action = item.action
            if existing_action is None:
                raise RuntimeError(
                    f"{item.txn_id} is ACTION_CHOSEN but carries no action; "
                    "this violates the orchestrator's own invariant"
                )
            outcome = await self._deps.check_and_execute(item, existing_action)
            self._pending_outcomes[item.txn_id] = outcome
            return self._machine.transition(
                item,
                State.CONSTRAINT_CHECKED,
                rationale=(
                    f"constraint gate: {outcome.constraint_result}: {outcome.constraint_reason}"
                ),
                constraint_result=outcome.constraint_result,
                constraint_reason=outcome.constraint_reason,
            )

        if state is State.CONSTRAINT_CHECKED:
            outcome = self._take_pending_outcome(item.txn_id)
            if outcome.constraint_result == "FAIL":
                return self._machine.transition(
                    item,
                    State.ESCALATED,
                    rationale=self._escalation_rationale(outcome),
                    outcome=outcome.outcome_detail,
                )
            if outcome.escalate_reason is not None and not outcome.executed:
                # The gate passed, but the policy itself chose not to act: a fraud
                # block (NO_ACTION) or an unknown-cause escalation (ESCALATE). There
                # is nothing to execute and nothing to schedule, so this hands the
                # item straight to a human rather than parking a scheduleless action
                # in SCHEDULED. A nudge that *did* execute keeps its escalate_reason
                # too, but is excluded here by ``not outcome.executed`` so its
                # EXECUTED transition is still recorded before it escalates below.
                return self._machine.transition(
                    item,
                    State.ESCALATED,
                    rationale=outcome.escalate_reason,
                    outcome=outcome.outcome_detail,
                )
            if not outcome.executed:
                self._pending_outcomes[item.txn_id] = outcome
                return self._machine.transition(
                    item,
                    State.SCHEDULED,
                    rationale=f"execution deferred: {outcome.constraint_reason}",
                )
            # The EXECUTED step below still needs this outcome to decide recovered vs
            # retry vs escalate, so re-cache it: CONSTRAINT_CHECKED and EXECUTED are two
            # separate audited transitions consuming one check_and_execute result.
            self._pending_outcomes[item.txn_id] = outcome
            return self._machine.transition(
                item,
                State.EXECUTED,
                rationale=f"executed: {outcome.outcome_detail or outcome.constraint_reason}",
                outcome=outcome.outcome_detail,
            )

        if state is State.SCHEDULED:
            scheduled_action = item.action
            if scheduled_action is None or scheduled_action.scheduled_for is None:
                raise RuntimeError(
                    f"{item.txn_id} is SCHEDULED but its action carries no scheduled_for; "
                    "this violates the orchestrator's own invariant"
                )
            if self._clock.now() < scheduled_action.scheduled_for:
                return item
            outcome = await self._deps.check_and_execute(item, scheduled_action)
            if outcome.constraint_result == "FAIL":
                return self._machine.transition(
                    item,
                    State.ESCALATED,
                    rationale=self._escalation_rationale(outcome),
                    constraint_result=outcome.constraint_result,
                    constraint_reason=outcome.constraint_reason,
                    outcome=outcome.outcome_detail,
                )
            self._pending_outcomes[item.txn_id] = outcome
            return self._machine.transition(
                item,
                State.EXECUTED,
                rationale=(
                    f"executed on schedule: {outcome.outcome_detail or outcome.constraint_reason}"
                ),
                constraint_result=outcome.constraint_result,
                constraint_reason=outcome.constraint_reason,
                outcome=outcome.outcome_detail,
            )

        if state is State.EXECUTED:
            outcome = self._take_pending_outcome(item.txn_id)
            if outcome.recovered:
                return self._machine.transition(
                    item,
                    State.RESOLVED,
                    rationale=outcome.outcome_detail or "payment recovered",
                )
            if outcome.escalate_reason is not None:
                return self._machine.transition(
                    item,
                    State.ESCALATED,
                    rationale=outcome.escalate_reason,
                    outcome=outcome.outcome_detail,
                )
            # Failed, but the retry budget is not yet spent: loop back for another
            # attempt. Re-select the action against the *incremented* retry count so
            # the policy's per-attempt decisions actually take effect on a retry — a
            # soft decline is retried at most once and then escalates (PRD §10.3),
            # and a gateway-degradation backoff grows with each attempt (PRD §11.4).
            # Replaying the first-chosen action unchanged until the retry cap would
            # silently bypass both rules, which is what an end-to-end run revealed.
            reselected_action = item.action
            if item.diagnosis is not None:
                next_attempt = item.model_copy(update={"retry_count": item.retry_count + 1})
                reselected_action = self._deps.select_action(next_attempt, item.diagnosis)
            return self._machine.transition(
                item,
                State.ACTION_CHOSEN,
                rationale=outcome.outcome_detail or "attempt failed; retrying",
                action=reselected_action,
                outcome=outcome.outcome_detail,
            )

        if is_terminal(state):
            raise TerminalStateError(
                f"{item.txn_id} is already {state} (terminal); nothing left to advance"
            )

        raise AssertionError(f"unhandled state {state!r}; every State member must be routed above")

    @staticmethod
    def _escalation_rationale(outcome: GateOutcome) -> str:
        """The rationale for an escalation driven by a constraint refusal.

        Prefers the gate's own ``escalate_reason``; falls back to
        ``constraint_reason`` so the transition's rationale is never empty even if
        a caller-supplied :class:`GateOutcome` left ``escalate_reason`` unset on a
        refusal.
        """
        return outcome.escalate_reason or f"constraint breach: {outcome.constraint_reason}"

    def _take_pending_outcome(self, txn_id: str) -> GateOutcome:
        """The :class:`GateOutcome` cached for ``txn_id`` by the step that produced it.

        Raises ``RuntimeError`` rather than ``KeyError`` if none is cached — this
        can only happen if :meth:`advance` is called out of order (e.g. a work item
        reaches ``CONSTRAINT_CHECKED`` by some path other than this orchestrator's
        own ``ACTION_CHOSEN`` handling), which is a programming error, not a
        recoverable condition.
        """
        outcome = self._pending_outcomes.pop(txn_id, None)
        if outcome is None:
            raise RuntimeError(
                f"no pending gate outcome cached for {txn_id}; advance() was called out of order"
            )
        return outcome

    async def run_to_completion(self, item: WorkItem, max_steps: int = 24) -> WorkItem:
        """Advance until terminal or ``max_steps``.

        Raises rather than silently abandoning a work item that will not settle —
        that is a bug (a routing error in this class, or a collaborator that never
        converges), not a state to leave unresolved.
        """
        current = item
        for _ in range(max_steps):
            if is_terminal(current.state):
                return current
            current = await self.advance(current)

        if is_terminal(current.state):
            return current
        raise RuntimeError(
            f"{current.txn_id} did not reach a terminal state within {max_steps} steps "
            f"(currently {current.state}); a work item that will not settle is a bug"
        )
