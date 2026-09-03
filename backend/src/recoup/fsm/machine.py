"""The state machine: validated, atomic, audited transitions.

PRD section 4's sentence — "the state machine decides... and the audit log proves
it" — is implemented in exactly one place: :meth:`StateMachine.transition`. Every
other component in this codebase that wants to move a work item forward calls this
method rather than assigning ``item.state`` directly, which is what makes "illegal
transitions are impossible" true of the whole system rather than true of the parts
that remembered to check :mod:`recoup.fsm.states` themselves.

Three properties make that promise real:

1. **Validation precedes mutation.** The terminal check (PRD section 12.2's
   stopping rule), the legal-transition check (PRD section 7.4) and the rationale
   check (PRD section 8.6) all run before anything is written. A rejected
   transition never touches the work item or the audit log.
2. **Atomicity.** The work-item checkpoint and the audit append happen inside one
   :func:`~recoup.storage.db.unit_of_work`, so they commit together or not at all —
   the guarantee Phase 1 built and this module is the first to depend on.
3. **No in-place mutation.** ``transition`` returns a new, freshly-reloaded
   :class:`~recoup.domain.models.WorkItem` rather than mutating the caller's
   instance. A caller that ignores the return value keeps holding the pre-transition
   object, which cannot be mistaken for a half-applied one.
"""

from typing import Literal

from sqlalchemy import Engine

from recoup.clock import Clock
from recoup.domain.enums import State
from recoup.domain.models import Action, AuditEvent, Diagnosis, WorkItem
from recoup.fsm.states import LEGAL_TRANSITIONS, is_terminal
from recoup.storage.audit import AuditLog
from recoup.storage.db import unit_of_work
from recoup.storage.work_items import WorkItemRepo

__all__ = ["IllegalTransition", "StateMachine", "TerminalStateError"]

_ConstraintResult = Literal["PASS", "FAIL"]


class IllegalTransition(Exception):
    """Raised when ``to`` is not in ``LEGAL_TRANSITIONS[item.state]``.

    Names both the current and the requested state, since that is exactly what a
    caller needs to see to know whether it built the wrong ``to`` or is holding a
    stale ``item``.
    """


class TerminalStateError(Exception):
    """Raised when a transition is attempted from ``RESOLVED`` or ``ESCALATED``.

    This is PRD section 12.2's stopping rule ("no further action after RESOLVED or
    ESCALATED") enforced at the lowest level that can enforce it, so no later phase
    — the orchestrator, the batch runner, a stray admin script — can bypass it by
    calling :meth:`StateMachine.transition` directly.
    """


class StateMachine:
    """Validates, checkpoints and audits every transition a work item makes."""

    def __init__(self, engine: Engine, audit: AuditLog, repo: WorkItemRepo, clock: Clock) -> None:
        self._engine = engine
        self._audit = audit
        self._repo = repo
        self._clock = clock

    def transition(
        self,
        item: WorkItem,
        to: State,
        *,
        rationale: str,
        diagnosis: Diagnosis | None = None,
        action: Action | None = None,
        constraint_result: _ConstraintResult | None = None,
        constraint_reason: str | None = None,
        outcome: str | None = None,
    ) -> WorkItem:
        """Validate, mutate, checkpoint and audit — atomically, in one unit of work.

        ``diagnosis`` and ``action``, when given, replace the work item's current
        value; when omitted, the item's existing value (if any) is carried forward
        unchanged. This is what lets a transition that only re-evaluates the
        constraint gate (``ACTION_CHOSEN -> CONSTRAINT_CHECKED``) leave the action
        chosen two steps earlier untouched, while still letting the audit row for
        that transition report it: the recorded ``diagnosis_cause``,
        ``diagnosis_confidence`` and ``action_chosen`` always reflect the work
        item's state *after* this transition is applied, not only a value supplied
        to this particular call. A gate-evaluation row therefore still shows which
        diagnosis and which action were being evaluated, which is what makes a
        single audit row self-explanatory instead of requiring a reader to
        reconstruct context from earlier rows.

        Raises:
            TerminalStateError: ``item.state`` is already ``RESOLVED`` or
                ``ESCALATED``. Checked first, so a stale terminal item can never
                reach the legal-transition check at all.
            IllegalTransition: ``to`` is not a legal successor of ``item.state``.
            ValueError: ``rationale`` is empty or whitespace-only.
        """
        if is_terminal(item.state):
            raise TerminalStateError(
                f"{item.txn_id} is already {item.state} (terminal); "
                f"no transition to {to} (or any other state) is permitted"
            )

        legal = LEGAL_TRANSITIONS[item.state]
        if to not in legal:
            raise IllegalTransition(
                f"{item.state} -> {to} is not a legal transition for {item.txn_id} "
                f"(legal next states: {sorted(legal) or 'none (terminal)'})"
            )

        if not rationale.strip():
            raise ValueError("rationale must not be empty or whitespace-only")

        from_state = item.state
        is_retry = from_state is State.EXECUTED and to is State.ACTION_CHOSEN
        retry_count = item.retry_count + 1 if is_retry else item.retry_count

        updated = item.model_copy(
            update={
                "state": to,
                "retry_count": retry_count,
                "diagnosis": diagnosis if diagnosis is not None else item.diagnosis,
                "action": action if action is not None else item.action,
            }
        )

        event = AuditEvent(
            timestamp=self._clock.now(),
            txn_id=item.txn_id,
            from_state=from_state,
            to_state=to,
            diagnosis_cause=updated.diagnosis.cause if updated.diagnosis is not None else None,
            diagnosis_confidence=(
                updated.diagnosis.confidence if updated.diagnosis is not None else None
            ),
            action_chosen=updated.action.type if updated.action is not None else None,
            constraint_result=constraint_result,
            constraint_reason=constraint_reason,
            outcome=outcome,
            rationale=rationale,
        )

        with unit_of_work(self._engine) as session:
            saved = self._repo.save(updated, session=session)
            self._audit.append(event, session=session)

        return saved
