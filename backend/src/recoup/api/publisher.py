"""The concrete event sink: domain events become the contract's WebSocket frames.

:class:`BusPublisher` is the API-layer implementation of
:class:`~recoup.events.EventSink`. The state machine and gate pipeline call it with
plain domain objects; it renders them into the exact payload shapes of
`docs/interface-contract.md` §4.3 and publishes them on the :class:`~recoup.events.EventBus`.

Keeping this translation here — not in the domain layer — is what lets the domain
layer stay ignorant of the wire format and the batch CLI run with no bus at all.
Every payload is built through the Phase-9 response schemas, so a WebSocket frame
and the matching REST body are byte-for-byte the same shape and are serialised
(IST timestamps, enum values) in exactly one way.
"""

from __future__ import annotations

from recoup.api.metrics_view import compute_metrics
from recoup.api.schemas import AuditEventOut, EscalationOut, WorkItemOut
from recoup.clock import Clock
from recoup.domain.enums import State
from recoup.domain.models import Action, AuditEvent, WorkItem
from recoup.events import EventBus
from recoup.storage.audit import AuditLog
from recoup.storage.work_items import WorkItemRepo

__all__ = ["BusPublisher"]


class BusPublisher:
    """Publishes the contract's live frames onto the bus as transitions happen."""

    def __init__(self, bus: EventBus, repo: WorkItemRepo, audit: AuditLog, clock: Clock) -> None:
        self._bus = bus
        self._repo = repo
        self._audit = audit
        self._clock = clock

    def record_transition(
        self, previous_state: object, item: WorkItem, audit_event: AuditEvent
    ) -> None:
        """Emit ``audit.appended`` and ``workitem.updated`` for one transition, plus
        ``escalation.created`` and a refreshed ``metrics.updated`` when it is terminal."""
        self._bus.publish(
            "audit.appended", AuditEventOut.model_validate(audit_event).model_dump(mode="json")
        )

        previous = previous_state.value if isinstance(previous_state, State) else None
        workitem_payload = WorkItemOut.model_validate(item).model_dump(mode="json")
        self._bus.publish("workitem.updated", {"previous_state": previous, **workitem_payload})

        if item.state is State.ESCALATED:
            self._bus.publish(
                "escalation.created",
                EscalationOut(
                    txn_id=item.txn_id,
                    merchant_id=item.merchant_id,
                    amount_paise=item.amount_paise,
                    customer_name=item.customer.name,
                    cause=item.diagnosis.cause if item.diagnosis is not None else None,
                    reason=audit_event.rationale,
                    constraint_result=audit_event.constraint_result,
                    escalated_at=audit_event.timestamp,
                    retry_count=item.retry_count,
                ).model_dump(mode="json"),
            )

        # Recompute the counters only when a work item settles: an intermediate
        # transition never changes recovered/escalated totals, so emitting on every
        # step would flood the socket without moving a number the dashboard shows.
        if item.state in (State.RESOLVED, State.ESCALATED):
            self._bus.publish(
                "metrics.updated",
                compute_metrics(self._repo, self._audit, self._clock).model_dump(mode="json"),
            )

    def record_gate_rejection(
        self,
        item: WorkItem,
        action: Action,
        *,
        constraint: str,
        reason: str,
        limit_paise: int,
        max_retries: int,
    ) -> None:
        """Emit the demo-critical ``gate.rejected`` frame (contract §4.3, PRD §12.4)."""
        self._bus.publish(
            "gate.rejected",
            {
                "txn_id": item.txn_id,
                "constraint": constraint,
                "reason": reason,
                "amount_paise": item.amount_paise,
                "limit_paise": limit_paise,
                "retry_count": item.retry_count,
                "max_retries": max_retries,
                "fraud_flag": item.fraud_flag,
                "action_type": action.type.value,
                "channel": action.channel.value,
                "next_state": State.ESCALATED.value,
            },
        )
