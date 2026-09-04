"""The work-item repository: the mutable side of persistence (PRD section 10.1).

Where :class:`~recoup.storage.audit.AuditLog` is append-only, :class:`WorkItemRepo`
is the opposite by design — a work item is one row that is checkpointed again and
again as the state machine advances it. The two invariants this module owns:

**Idempotency is database-enforced, not merely checked.** PRD sections 8.1 and
13.2 require that a webhook delivered twice never starts a second recovery.
:meth:`WorkItemRepo.create_if_absent` does not implement this as "check whether the
row exists, then insert if not" — that check-then-act sequence has a race between
two concurrent deliveries of the same event. Instead it always attempts the
insert and lets the ``event_id`` unique constraint (declared in
:mod:`recoup.storage.tables`) be the arbiter; a violation means another writer got
there first, so this call re-reads and returns what is actually stored. Two
concurrent callers with the same ``event_id`` can therefore never both succeed.

**Keyset, not offset, pagination.** :meth:`WorkItemRepo.list` pages on
``(created_at, txn_id)`` rather than ``OFFSET``. An offset page shifts under a
writer that is inserting rows concurrently — exactly what the batch runner and the
dashboard's live feed both are — so page 2 would silently skip or repeat rows.
Keyset pagination has no such window: each page's cursor is the last row's own
sort key, not a row count.
"""

from datetime import datetime

from sqlalchemy import ColumnElement, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from recoup.domain.enums import Cause, FailureType, State
from recoup.domain.models import Action, Customer, Diagnosis, WorkItem
from recoup.storage.db import unit_of_work
from recoup.storage.tables import WorkItemRow

__all__ = ["WorkItemRepo", "encode_cursor"]


def _populate_row(row: WorkItemRow, item: WorkItem) -> None:
    """Copy every field of ``item`` onto ``row``, in place.

    Used both to fill a freshly constructed row and to overwrite an existing one
    on :meth:`WorkItemRepo.save` — a "full checkpoint" means every mutable field is
    rewritten, not just the ones that happened to change.
    """
    row.txn_id = item.txn_id
    row.event_id = item.event_id
    row.merchant_id = item.merchant_id
    row.amount_paise = item.amount_paise
    row.currency = item.currency
    row.failure_code = item.failure_code
    row.failure_message = item.failure_message
    row.failure_type = item.failure_type.value
    row.method = item.method
    row.issuer = item.issuer
    row.customer = item.customer.model_dump(mode="json")
    row.fraud_flag = item.fraud_flag
    row.created_at = item.created_at
    row.state = item.state.value
    row.retry_count = item.retry_count
    row.diagnosis = item.diagnosis.model_dump(mode="json") if item.diagnosis is not None else None
    row.action = item.action.model_dump(mode="json") if item.action is not None else None


def _row_to_domain(row: WorkItemRow) -> WorkItem:
    """Reconstruct the domain work item a persisted row represents."""
    return WorkItem(
        txn_id=row.txn_id,
        event_id=row.event_id,
        merchant_id=row.merchant_id,
        amount_paise=row.amount_paise,
        currency=row.currency,  # type: ignore[arg-type]  # v1 supports only "INR"; validated by WorkItem
        failure_code=row.failure_code,
        failure_message=row.failure_message,
        failure_type=FailureType(row.failure_type),
        method=row.method,
        issuer=row.issuer,
        customer=Customer.model_validate(row.customer),
        fraud_flag=row.fraud_flag,
        created_at=row.created_at,
        state=State(row.state),
        retry_count=row.retry_count,
        diagnosis=Diagnosis.model_validate(row.diagnosis) if row.diagnosis is not None else None,
        action=Action.model_validate(row.action) if row.action is not None else None,
    )


class WorkItemRepo:
    """Reads and writes ``work_items``."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_if_absent(
        self, item: WorkItem, session: Session | None = None
    ) -> tuple[WorkItem, bool]:
        """Insert ``item`` unless its ``event_id`` is already stored.

        Returns ``(item, True)`` on a fresh insert, or ``(stored_item, False)``
        when ``event_id`` already exists — ``stored_item`` is what the database
        actually holds, which may differ from ``item`` if the first delivery
        carried different field values. Never raises for a duplicate ``event_id``;
        that is the whole point (PRD section 13.2).

        The insert is attempted inside a ``SAVEPOINT`` (:meth:`Session.begin_nested`)
        so that a unique-constraint violation only rolls back this one insert, not
        anything else pending in a caller-supplied session's transaction.
        """
        if session is not None:
            return self._create_if_absent(item, session)
        with unit_of_work(self._engine) as owned_session:
            return self._create_if_absent(item, owned_session)

    def _create_if_absent(self, item: WorkItem, session: Session) -> tuple[WorkItem, bool]:
        row = WorkItemRow(txn_id=item.txn_id)
        _populate_row(row, item)
        try:
            with session.begin_nested():
                session.add(row)
                session.flush()
        except IntegrityError:
            existing = session.execute(
                select(WorkItemRow).where(WorkItemRow.event_id == item.event_id)
            ).scalar_one()
            return _row_to_domain(existing), False
        return _row_to_domain(row), True

    def get(self, txn_id: str) -> WorkItem | None:
        """The work item stored under ``txn_id``, or ``None`` if there is none."""
        with unit_of_work(self._engine) as session:
            row = session.get(WorkItemRow, txn_id)
            return _row_to_domain(row) if row is not None else None

    def save(self, item: WorkItem, session: Session | None = None) -> WorkItem:
        """Checkpoint every mutable field of ``item``.

        Updates the existing row for ``item.txn_id`` if one exists, or inserts a
        new one otherwise — the state machine always calls this after
        :meth:`create_if_absent` has already inserted the row, but treating a
        missing row as "insert" rather than an error keeps this method correct on
        its own rather than dependent on call order elsewhere.
        """
        if session is not None:
            return self._save(item, session)
        with unit_of_work(self._engine) as owned_session:
            return self._save(item, owned_session)

    def _save(self, item: WorkItem, session: Session) -> WorkItem:
        row = session.get(WorkItemRow, item.txn_id)
        if row is None:
            row = WorkItemRow(txn_id=item.txn_id)
            session.add(row)
        _populate_row(row, item)
        session.flush()
        return _row_to_domain(row)

    def list(
        self,
        state: State | None = None,
        cause: Cause | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> list[WorkItem]:
        """Work items, newest first, filtered and paginated.

        Ordering is ``created_at DESC, txn_id DESC`` — ``txn_id`` breaks ties
        between two items created in the same instant, which a batch run
        routinely produces. ``cursor`` is the opaque string
        :func:`encode_cursor` produced for the last row of the previous page;
        passing it back returns the next page with no gap and no repeat, even if
        rows are being inserted concurrently, because the comparison is against
        that row's own sort key rather than against a row count.

        ``cause`` filters on ``diagnosis.cause`` inside the JSON column. A work
        item with no diagnosis yet never matches a ``cause`` filter, which is
        correct: it has no cause to match.
        """
        with unit_of_work(self._engine) as session:
            stmt = select(WorkItemRow)
            if state is not None:
                stmt = stmt.where(WorkItemRow.state == state.value)
            if cause is not None:
                stmt = stmt.where(WorkItemRow.diagnosis["cause"].as_string() == cause.value)
            if cursor is not None:
                cursor_created_at, cursor_txn_id = _decode_cursor(cursor)
                stmt = stmt.where(_before_cursor(cursor_created_at, cursor_txn_id))
            stmt = stmt.order_by(WorkItemRow.created_at.desc(), WorkItemRow.txn_id.desc()).limit(
                limit
            )
            rows = session.execute(stmt).scalars().all()
            return [_row_to_domain(row) for row in rows]

    def count_by_state(self) -> dict[State, int]:
        """How many work items are currently in each state.

        Only states with at least one row appear; a state with zero items is
        simply absent rather than present with a ``0`` (the dashboard's Phase 10
        consumer treats a missing key as zero)."""
        with unit_of_work(self._engine) as session:
            stmt = select(WorkItemRow.state, func.count()).group_by(WorkItemRow.state)
            rows = session.execute(stmt).all()
            return {State(state_value): count for state_value, count in rows}


def _before_cursor(created_at: datetime, txn_id: str) -> ColumnElement[bool]:
    """The keyset predicate for "strictly after ``(created_at, txn_id)`` in
    descending order" — i.e. everything the previous page had not yet reached.

    Expressed as a row-value comparison
    ``(created_at, txn_id) < (cursor_created_at, cursor_txn_id)`` so that a page
    boundary falling on a tied ``created_at`` (routine in a batch run, where many
    items share a timestamp) still advances past every row already returned,
    rather than only past ties broken by ``created_at`` alone.
    """
    return (WorkItemRow.created_at < created_at) | (
        (WorkItemRow.created_at == created_at) & (WorkItemRow.txn_id < txn_id)
    )


def encode_cursor(item: WorkItem) -> str:
    """The pagination cursor for ``item``, suitable for the ``cursor`` parameter
    of the next call to :meth:`WorkItemRepo.list`."""
    return f"{item.created_at.isoformat()}|{item.txn_id}"


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    raw_created_at, _, txn_id = cursor.partition("|")
    return datetime.fromisoformat(raw_created_at), txn_id
