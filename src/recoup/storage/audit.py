"""The append-only audit log reader and writer (PRD sections 8.6 and 10.2).

:class:`AuditLog` is the only code in this codebase that writes to
``audit_events``. That is not a convention this module asks callers to respect —
it is the reason the class exists at all: if every layer that wanted to record a
transition wrote its own ``INSERT``, "the audit trail is complete" would depend on
every one of them remembering to. Routing every append through one class makes it
possible to point at this file and say "this is the whole write path."

The class exposes no ``update`` or no ``delete`` method, and that absence is
deliberate and load-bearing, not an oversight to be filled in later. Combined with
the database triggers in :mod:`recoup.storage.tables`, immutability is enforced
twice — once by what this class simply cannot do, and once by what the database
physically refuses — so a bug in one layer does not silently defeat the other.
"""

from typing import Literal

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from recoup.domain.enums import ActionType, Cause, State
from recoup.domain.models import AuditEvent
from recoup.storage.db import unit_of_work
from recoup.storage.tables import AuditEventRow

__all__ = ["AuditLog"]

_ConstraintResult = Literal["PASS", "FAIL"]


def _constraint_result(value: str | None) -> _ConstraintResult | None:
    """Narrow a stored string back to the domain model's closed literal.

    The column has no database-level check constraint restricting it to these two
    values, so this is where a corrupted or hand-edited row would be caught rather
    than silently trusted.
    """
    if value is None:
        return None
    if value in ("PASS", "FAIL"):
        return value  # type: ignore[return-value]  # narrowed by the membership check above
    raise ValueError(f"audit_events.constraint_result has an invalid value: {value!r}")


def _to_row(event: AuditEvent) -> AuditEventRow:
    """Build a new, unpersisted row from a domain event.

    ``event.id`` is never read here: the id is assigned by the database on
    insert, so any value already set on the Pydantic model (there should not be
    one for a fresh append) is ignored rather than honoured.
    """
    return AuditEventRow(
        timestamp=event.timestamp,
        txn_id=event.txn_id,
        from_state=event.from_state.value if event.from_state is not None else None,
        to_state=event.to_state.value,
        diagnosis_cause=event.diagnosis_cause.value if event.diagnosis_cause is not None else None,
        diagnosis_confidence=event.diagnosis_confidence,
        action_chosen=event.action_chosen.value if event.action_chosen is not None else None,
        constraint_result=event.constraint_result,
        constraint_reason=event.constraint_reason,
        outcome=event.outcome,
        rationale=event.rationale,
    )


def _to_domain(row: AuditEventRow) -> AuditEvent:
    """Reconstruct the domain event a persisted row represents."""
    return AuditEvent(
        id=row.id,
        timestamp=row.timestamp,
        txn_id=row.txn_id,
        from_state=State(row.from_state) if row.from_state is not None else None,
        to_state=State(row.to_state),
        diagnosis_cause=Cause(row.diagnosis_cause) if row.diagnosis_cause is not None else None,
        diagnosis_confidence=row.diagnosis_confidence,
        action_chosen=ActionType(row.action_chosen) if row.action_chosen is not None else None,
        constraint_result=_constraint_result(row.constraint_result),
        constraint_reason=row.constraint_reason,
        outcome=row.outcome,
        rationale=row.rationale,
    )


class AuditLog:
    """Reads and writes ``audit_events``. The only writer; see the module docstring."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(self, event: AuditEvent, session: Session | None = None) -> int:
        """Insert ``event`` and return the id the database assigned it.

        When ``session`` is given, the insert joins that caller's transaction and
        is not committed here — the caller decides when (or whether) it becomes
        durable. This is what lets :func:`~recoup.storage.db.unit_of_work` wrap a
        work-item checkpoint and an audit append as one atomic commit.

        When ``session`` is omitted, this method opens and commits its own unit of
        work, so a standalone append is durable the moment this call returns.

        The row is flushed (not merely added) before its id is read back, in both
        branches, because SQLite assigns the autoincrement id at flush/insert time
        — reading ``row.id`` before that point would return ``None``.
        """
        row = _to_row(event)
        if session is not None:
            session.add(row)
            session.flush()
            return row.id

        with unit_of_work(self._engine) as owned_session:
            owned_session.add(row)
            owned_session.flush()
            assigned_id = row.id
        return assigned_id

    def list_since(self, since_id: int, limit: int = 100) -> list[AuditEvent]:
        """Rows with ``id > since_id``, ascending, capped at ``limit``.

        This is the WebSocket backfill: a client reconnects with the last ``seq``
        it saw, and this is the query that answers "what did I miss".
        """
        with unit_of_work(self._engine) as session:
            stmt = (
                select(AuditEventRow)
                .where(AuditEventRow.id > since_id)
                .order_by(AuditEventRow.id.asc())
                .limit(limit)
            )
            rows = session.execute(stmt).scalars().all()
            return [_to_domain(row) for row in rows]

    def for_txn(self, txn_id: str) -> list[AuditEvent]:
        """Every event recorded for ``txn_id``, ordered by id ascending.

        This is the per-transaction history the dashboard's expandable audit row
        renders: ``Event -> Diagnosis -> Action -> Constraint Check -> Result``,
        in the order it actually happened.
        """
        with unit_of_work(self._engine) as session:
            stmt = (
                select(AuditEventRow)
                .where(AuditEventRow.txn_id == txn_id)
                .order_by(AuditEventRow.id.asc())
            )
            rows = session.execute(stmt).scalars().all()
            return [_to_domain(row) for row in rows]
