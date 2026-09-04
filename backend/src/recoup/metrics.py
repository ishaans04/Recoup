"""The batch report and its derivation from the audit trail (PRD §13.4, §15.1).

The headline number and, beside it, the honest exception list. PRD §13.4 is
categorical: "The system never cherry-picks. The batch run reports the true
recovery rate and the full list of exceptions it could not resolve, with reasons."
So :class:`BatchReport` carries `exceptions` as a required field, `recovery_rate`
is `recovered / at_risk` with nothing filtered out of the denominator, and the
whole report is derived from the immutable audit log — deriving it from the trail
rather than from in-memory bookkeeping is what makes the numbers trustworthy and
proves the trail is complete enough to reconstruct the run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from recoup.domain.enums import Cause, Channel, State
from recoup.domain.models import AuditEvent, WorkItem
from recoup.money import format_inr_paise

__all__ = [
    "BatchReport",
    "CauseStats",
    "EscalationRecord",
    "ExceptionRecord",
    "RejectionRecord",
    "build_report",
]


@dataclass(frozen=True)
class CauseStats:
    attempted: int = 0
    recovered: int = 0
    recovered_paise: int = 0


@dataclass(frozen=True)
class RejectionRecord:
    txn_id: str
    rule_id: str
    reason: str


@dataclass(frozen=True)
class EscalationRecord:
    txn_id: str
    reason: str


@dataclass(frozen=True)
class ExceptionRecord:
    """A transaction the system could not recover, with a specific reason.

    Required in every report (PRD §13.4). ``reason`` is drawn from the audit trail —
    the rule that refused, the missing contact, the exhausted retries — never a
    generic "failed".
    """

    txn_id: str
    amount_paise: int
    cause: Cause | None
    final_state: State
    reason: str


@dataclass(frozen=True)
class BatchReport:
    run_id: str
    total_transactions: int
    total_at_risk_paise: int
    total_recovered_paise: int
    recovery_rate: float
    recovered_count: int
    by_cause: Mapping[Cause, CauseStats]
    by_channel: Mapping[Channel, int]
    constraint_rejections: Sequence[RejectionRecord]
    escalations: Sequence[EscalationRecord]
    exceptions: Sequence[ExceptionRecord]
    diagnosis_sources: Mapping[str, int]
    breaker_trips: Mapping[str, str]
    started_at: datetime
    finished_at: datetime
    _unsettled: Sequence[str] = field(default=())

    def render_text(self) -> str:
        """A human-readable report for the CLI — designed to be read aloud on stage."""
        lines: list[str] = []
        lines.append(f"Recoup batch report  ·  run {self.run_id}")
        lines.append("=" * 60)
        lines.append(f"Transactions processed : {self.total_transactions}")
        lines.append(f"At-risk revenue        : {format_inr_paise(self.total_at_risk_paise)}")
        lines.append(
            f"Recovered              : {format_inr_paise(self.total_recovered_paise)} "
            f"({self.recovered_count} txns)"
        )
        lines.append(f"Recovery rate          : {self.recovery_rate:.1%}")
        lines.append("")
        lines.append("Recovery by cause:")
        for cause, stats in sorted(self.by_cause.items(), key=lambda kv: kv[0].value):
            lines.append(
                f"  {cause.value:<22} {stats.recovered}/{stats.attempted} recovered "
                f"({format_inr_paise(stats.recovered_paise)})"
            )
        lines.append("")
        lines.append("Actions by channel:")
        for channel, count in sorted(self.by_channel.items(), key=lambda kv: kv[0].value):
            lines.append(f"  {channel.value:<16} {count}")
        lines.append("")
        lines.append(f"Constraint rejections  : {len(self.constraint_rejections)}")
        for rej in self.constraint_rejections:
            lines.append(f"  {rej.txn_id}: {rej.reason}")
        lines.append(f"Breaker trips          : {self.breaker_trips or 'none'}")
        lines.append("")
        lines.append(f"Diagnosis sources      : {dict(self.diagnosis_sources)}")
        lines.append("")
        lines.append(f"EXCEPTIONS ({len(self.exceptions)}) — honestly reported, not cherry-picked:")
        for exc in self.exceptions:
            cause_label = exc.cause.value if exc.cause else "undiagnosed"
            lines.append(
                f"  {exc.txn_id} [{format_inr_paise(exc.amount_paise)}, {cause_label}] "
                f"-> {exc.final_state.value}: {exc.reason}"
            )
        if self._unsettled:
            lines.append("")
            lines.append(f"WARNING — items that did not settle: {list(self._unsettled)}")
        return "\n".join(lines)


def _rule_id_from_reason(reason: str) -> str:
    """The rule id is the token before the first colon in a constraint reason.

    Reasons are formatted `"<rule_id>: <detail>"` by the gate, so this recovers the
    id from the row without the audit schema needing a separate column for it.
    """
    return reason.split(":", 1)[0].strip() if reason else "unknown"


def build_report(
    run_id: str,
    work_items: Sequence[WorkItem],
    audit_by_txn: Mapping[str, Sequence[AuditEvent]],
    breaker_snapshot: Mapping[str, str],
    *,
    started_at: datetime,
    finished_at: datetime,
) -> BatchReport:
    """Compute a :class:`BatchReport` purely from work items and their audit rows.

    Pure given its inputs, so calling it twice over the same database — once from
    the run, once from a fresh reader — yields the same report, which is the
    reproducibility/derived-from-the-trail property PRD §13.4 leans on.
    """
    total_at_risk = 0
    total_recovered = 0
    recovered_count = 0
    by_cause: dict[Cause, CauseStats] = {}
    by_channel: dict[Channel, int] = {}
    rejections: list[RejectionRecord] = []
    escalations: list[EscalationRecord] = []
    exceptions: list[ExceptionRecord] = []
    diagnosis_sources: dict[str, int] = {}
    unsettled: list[str] = []

    for item in sorted(work_items, key=lambda w: w.txn_id):
        rows = audit_by_txn.get(item.txn_id, ())
        total_at_risk += item.amount_paise
        recovered = item.state is State.RESOLVED

        cause = item.diagnosis.cause if item.diagnosis else None
        if cause is not None:
            stats = by_cause.get(cause, CauseStats())
            by_cause[cause] = CauseStats(
                attempted=stats.attempted + 1,
                recovered=stats.recovered + (1 if recovered else 0),
                recovered_paise=stats.recovered_paise + (item.amount_paise if recovered else 0),
            )
        if item.diagnosis is not None:
            src = item.diagnosis.source
            diagnosis_sources[src] = diagnosis_sources.get(src, 0) + 1

        if recovered:
            recovered_count += 1
            total_recovered += item.amount_paise

        # Actions taken by channel: one per item that reached an executed action.
        executed = any(r.to_state is State.EXECUTED for r in rows)
        if item.action is not None and executed:
            by_channel[item.action.channel] = by_channel.get(item.action.channel, 0) + 1

        # Constraint rejections: every FAIL row, in order.
        for row in rows:
            if row.constraint_result == "FAIL" and row.constraint_reason:
                rejections.append(
                    RejectionRecord(
                        txn_id=item.txn_id,
                        rule_id=_rule_id_from_reason(row.constraint_reason),
                        reason=row.constraint_reason,
                    )
                )

        if item.state is State.ESCALATED:
            reason = rows[-1].rationale if rows else "escalated"
            escalations.append(EscalationRecord(txn_id=item.txn_id, reason=reason))
            exceptions.append(
                ExceptionRecord(
                    txn_id=item.txn_id,
                    amount_paise=item.amount_paise,
                    cause=cause,
                    final_state=item.state,
                    reason=reason,
                )
            )
        elif item.state is not State.RESOLVED:
            unsettled.append(item.txn_id)

    rate = (total_recovered / total_at_risk) if total_at_risk else 0.0

    return BatchReport(
        run_id=run_id,
        total_transactions=len(work_items),
        total_at_risk_paise=total_at_risk,
        total_recovered_paise=total_recovered,
        recovery_rate=rate,
        recovered_count=recovered_count,
        by_cause=by_cause,
        by_channel=by_channel,
        constraint_rejections=rejections,
        escalations=escalations,
        exceptions=exceptions,
        diagnosis_sources=diagnosis_sources,
        breaker_trips={r: s for r, s in breaker_snapshot.items() if s != "closed"},
        started_at=started_at,
        finished_at=finished_at,
        _unsettled=unsettled,
    )
