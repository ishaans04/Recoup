"""Live metrics and the escalation queue, derived from the database (contract §3.6, §3.7).

These are the honest-metrics payloads the dashboard reads and the WebSocket streams.
Both are computed by reading work items and their audit rows back from storage —
the same derive-from-the-trail discipline as the batch report — so the counters on
screen can always be reconstructed from the immutable log.

The contract's ``recovery_rate`` here is deliberately *count-based*
(``recovered / attempted``), unlike the batch report's paise-weighted rate: the
dashboard's live counter answers "of the recoveries we attempted, how many
landed?", and separates ``attempted`` from ``recovered`` so it never implies a
recovery it cannot evidence (PRD §13.4).
"""

from __future__ import annotations

from recoup.api.schemas import (
    ByCauseOut,
    ByChannelOut,
    EscalationOut,
    MetricsOut,
)
from recoup.clock import Clock
from recoup.domain.enums import Cause, Channel, State
from recoup.domain.models import AuditEvent, WorkItem
from recoup.storage.audit import AuditLog
from recoup.storage.work_items import WorkItemRepo

__all__ = ["compute_metrics", "compute_escalations"]

_SCAN_LIMIT = 100_000
"""A ceiling far above any demo dataset; the metrics scan reads every work item."""


def _all_items(repo: WorkItemRepo) -> list[WorkItem]:
    return repo.list(limit=_SCAN_LIMIT)


def compute_metrics(repo: WorkItemRepo, audit: AuditLog, clock: Clock) -> MetricsOut:
    """Aggregate the honest-metrics payload from every work item and its audit rows."""
    items = _all_items(repo)

    total_failed = 0
    total_failed_paise = 0
    attempted = 0
    recovered = 0
    recovered_paise = 0
    escalated = 0
    gate_rejections = 0
    in_flight = 0

    cause_count: dict[Cause, int] = {}
    cause_recovered: dict[Cause, int] = {}
    cause_recovered_paise: dict[Cause, int] = {}
    channel_attempted: dict[Channel, int] = {}
    channel_recovered: dict[Channel, int] = {}
    channel_recovered_paise: dict[Channel, int] = {}

    for item in items:
        total_failed += 1
        total_failed_paise += item.amount_paise
        is_recovered = item.state is State.RESOLVED

        rows = audit.for_txn(item.txn_id)
        gate_rejections += sum(1 for row in rows if row.constraint_result == "FAIL")
        executed = any(row.to_state is State.EXECUTED for row in rows)

        if is_recovered:
            recovered += 1
            recovered_paise += item.amount_paise
        elif item.state is State.ESCALATED:
            escalated += 1
        else:
            in_flight += 1

        if item.diagnosis is not None:
            cause = item.diagnosis.cause
            cause_count[cause] = cause_count.get(cause, 0) + 1
            if is_recovered:
                cause_recovered[cause] = cause_recovered.get(cause, 0) + 1
                cause_recovered_paise[cause] = (
                    cause_recovered_paise.get(cause, 0) + item.amount_paise
                )

        if executed and item.action is not None:
            attempted += 1
            channel = item.action.channel
            channel_attempted[channel] = channel_attempted.get(channel, 0) + 1
            if is_recovered:
                channel_recovered[channel] = channel_recovered.get(channel, 0) + 1
                channel_recovered_paise[channel] = (
                    channel_recovered_paise.get(channel, 0) + item.amount_paise
                )

    # Enum-ordered so the payload is deterministic; only categories that actually
    # occurred are listed, rather than padding every enum member with zeroes.
    by_cause = [
        ByCauseOut(
            cause=cause,
            count=cause_count[cause],
            recovered=cause_recovered.get(cause, 0),
            recovered_paise=cause_recovered_paise.get(cause, 0),
        )
        for cause in Cause
        if cause in cause_count
    ]
    by_channel = [
        ByChannelOut(
            channel=channel,
            attempted=channel_attempted[channel],
            recovered=channel_recovered.get(channel, 0),
            recovered_paise=channel_recovered_paise.get(channel, 0),
        )
        for channel in Channel
        if channel in channel_attempted
    ]

    recovery_rate = round(recovered / attempted, 2) if attempted else 0.0

    return MetricsOut(
        total_failed=total_failed,
        total_failed_paise=total_failed_paise,
        attempted=attempted,
        recovered=recovered,
        recovered_paise=recovered_paise,
        recovery_rate=recovery_rate,
        escalated=escalated,
        gate_rejections=gate_rejections,
        in_flight=in_flight,
        by_cause=by_cause,
        by_channel=by_channel,
        generated_at=clock.now(),
    )


def _escalated_row(rows: list[AuditEvent]) -> AuditEvent | None:
    """The transition that put a work item into ESCALATED (its last, being terminal)."""
    for row in reversed(rows):
        if row.to_state is State.ESCALATED:
            return row
    return None


def escalation_of(item: WorkItem, rows: list[AuditEvent]) -> EscalationOut | None:
    """Build one escalation-queue entry for an ESCALATED work item, or ``None``.

    ``reason`` is the escalating transition's rationale — the constraint that
    refused, the exhausted retries, the missing contact — never a generic label.
    """
    row = _escalated_row(rows)
    if row is None:
        return None
    return EscalationOut(
        txn_id=item.txn_id,
        merchant_id=item.merchant_id,
        amount_paise=item.amount_paise,
        customer_name=item.customer.name,
        cause=item.diagnosis.cause if item.diagnosis is not None else None,
        reason=row.rationale,
        constraint_result=row.constraint_result,
        escalated_at=row.timestamp,
        retry_count=item.retry_count,
    )


def compute_escalations(repo: WorkItemRepo, audit: AuditLog) -> list[EscalationOut]:
    """Every ESCALATED work item as a human-queue entry, newest escalation first."""
    escalated = repo.list(state=State.ESCALATED, limit=_SCAN_LIMIT)
    entries: list[EscalationOut] = []
    for item in escalated:
        entry = escalation_of(item, audit.for_txn(item.txn_id))
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda e: e.escalated_at, reverse=True)
    return entries
