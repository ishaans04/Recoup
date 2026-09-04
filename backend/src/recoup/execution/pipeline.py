"""The gate pipeline: the ``check_and_execute`` the orchestrator drives (PRD §7.4).

Phase 2 left a hole shaped exactly like this — a
``Callable[[WorkItem, Action], Awaitable[GateOutcome]]`` — and drove the lifecycle
against a fake of it. This module fills it for real by composing the constraint
gate and the executor, and it is the single place the gate's verdict is turned into
the ``GateOutcome`` the orchestrator routes on.

Four outcomes, decided here so the orchestrator stays a pure router:

- **Refused.** Any rule failed → escalate, carrying the gate's joined reason.
- **Escalate by policy.** The action itself is a block or an escalation
  (``NO_ACTION``/``ESCALATE`` from the selector) → escalate with the selector's
  reason, without running a channel. The gate still evaluated (its verdict is
  recorded), but a fraud block or an unknown-cause escalation is a decision the
  policy already made, not something to execute.
- **Deferred.** A retry scheduled for later → report "not executed" so the
  orchestrator parks it in ``SCHEDULED`` until the clock reaches its time.
- **Executed.** Otherwise → verify the freshly minted pass and run the channel.
"""

from __future__ import annotations

from recoup.clock import Clock
from recoup.constraints.gate import ConstraintGate
from recoup.domain.enums import ActionType
from recoup.domain.models import Action, WorkItem
from recoup.execution.executor import ActionExecutor
from recoup.fsm.orchestrator import GateOutcome

__all__ = ["GatePipeline"]

_ESCALATE_BY_POLICY = frozenset({ActionType.NO_ACTION, ActionType.ESCALATE})


class GatePipeline:
    """Composes the gate and executor into one ``check_and_execute`` callable."""

    def __init__(self, gate: ConstraintGate, executor: ActionExecutor, clock: Clock) -> None:
        self._gate = gate
        self._executor = executor
        self._clock = clock

    async def check_and_execute(self, item: WorkItem, action: Action) -> GateOutcome:
        """Gate ``action`` for ``item`` and, if allowed and due, execute it."""
        # Keep the action's attempt in step with the work item's retry count, so the
        # gate fingerprint and the executor's idempotency both reflect the real
        # attempt even when the retry loop re-uses an action selected earlier.
        effective = (
            action
            if action.attempt == item.retry_count
            else action.model_copy(update={"attempt": item.retry_count})
        )

        verdict = self._gate.check(effective, item)

        if verdict.result == "FAIL":
            return GateOutcome(
                executed=False,
                recovered=False,
                escalate_reason=verdict.reason,
                constraint_result="FAIL",
                constraint_reason=verdict.reason,
                outcome_detail=None,
            )

        if effective.type in _ESCALATE_BY_POLICY:
            return GateOutcome(
                executed=False,
                recovered=False,
                escalate_reason=effective.reason,
                constraint_result="PASS",
                constraint_reason=verdict.reason,
                outcome_detail=None,
            )

        if effective.scheduled_for is not None and self._clock.now() < effective.scheduled_for:
            return GateOutcome(
                executed=False,
                recovered=False,
                escalate_reason=None,
                constraint_result="PASS",
                constraint_reason=verdict.reason,
                outcome_detail=f"deferred until {effective.scheduled_for.isoformat()}",
            )

        assert verdict.gate_pass is not None  # PASS always carries a pass
        result = await self._executor.execute(verdict.gate_pass, item, effective)

        # A customer nudge never collects the money at the moment it is sent — a
        # delivered SMS or call only *asks* the customer to act. Unlike a retry, a
        # nudge is not bounded by the retry cap, so returning it to ACTION_CHOSEN
        # would re-select the same nudge and loop forever. It settles here instead:
        # the outcome carries an escalate reason, so after this one attempt the item
        # is handed to a human as an honest, unrecovered exception (PRD §13.4) rather
        # than being retried into an infinite loop.
        escalate_reason: str | None = None
        if effective.type is ActionType.CUSTOMER_NUDGE and not result.recovered:
            escalate_reason = (
                f"customer nudge via {result.channel.value} did not collect the "
                f"payment ({result.detail}); handed to a human to follow up"
            )

        return GateOutcome(
            executed=True,
            recovered=result.recovered,
            escalate_reason=escalate_reason,
            constraint_result="PASS",
            constraint_reason=verdict.reason,
            outcome_detail=result.detail,
        )
