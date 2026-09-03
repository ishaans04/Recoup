"""SQLAlchemy 2.0 tables for the two persisted stores (PRD sections 9.6 and 10).

Two tables, and the split between them is the split PRD section 8.6 draws between
mutable working state and an immutable record of how it got there:

``work_items`` is the current, mutable snapshot of a failed payment — one row per
:class:`~recoup.domain.models.WorkItem`, updated in place as the state machine
advances it. ``audit_events`` is the append-only history of every transition any
work item has ever made — one row per :class:`~recoup.domain.models.AuditEvent`,
inserted and never touched again.

**Postgres compatibility.** PRD section 9.6's pitch is "SQLite for the demo,
Postgres in production, same schema", so every column type here is one both
dialects support identically: :class:`~sqlalchemy.String` (unbounded, unlike
MySQL neither dialect requires a length), :class:`~sqlalchemy.JSON`,
:class:`~sqlalchemy.DateTime` with ``timezone=True``, :class:`~sqlalchemy.Boolean`,
:class:`~sqlalchemy.Integer` and :class:`~sqlalchemy.BigInteger`. Nothing here is a
SQLite-only affinity trick or a Postgres-only extension type — swapping
``database_url`` to a ``postgresql://`` DSN is the entire migration.

**Append-only enforcement.** ``audit_events`` carries two triggers, attached via
``sqlalchemy.event.listen(AuditEventRow.__table__, "after_create", DDL(...))`` so
they are created in the same DDL pass as the table itself and cannot be forgotten.
On SQLite:

.. code-block:: sql

    CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events
    BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;

    CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events
    BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;

The Postgres equivalent is not the same syntax — Postgres triggers call a
``plpgsql`` function rather than inlining ``RAISE`` — so it is a second, separate
DDL statement, guarded to run only on the ``postgresql`` dialect:

.. code-block:: sql

    CREATE OR REPLACE FUNCTION audit_events_block_mutation() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'audit_events is append-only';
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_block_mutation();

    CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_block_mutation();

    REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC;

The ``REVOKE`` is belt-and-braces: it removes the privilege from the default
``PUBLIC`` role so that a connection which was never granted ``UPDATE``/``DELETE``
explicitly cannot exercise it even if the trigger were somehow dropped. A
production role should be granted ``SELECT, INSERT`` on this table and nothing
more. This project has no Postgres instance to run against, so the SQLite path is
the one exercised by the test suite; the Postgres DDL is written to the same
contract and guarded by dialect so it can never fire during a SQLite test.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, Integer, String, TypeDecorator
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.event import listen
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import DDL

__all__ = ["AuditEventRow", "Base", "UTCDateTime", "WorkItemRow"]


class UTCDateTime(TypeDecorator[datetime]):
    """A ``DateTime`` column that always stores and returns an aware UTC value.

    This is what makes the brief's "timestamps stored as timezone-aware UTC"
    literally true rather than aspirational. Postgres's native
    ``TIMESTAMP WITH TIME ZONE`` (what ``DateTime(timezone=True)`` compiles to
    there) already round-trips an aware datetime correctly on its own. SQLite has
    no such native type — pysqlite serialises ``DateTime(timezone=True)`` to a
    plain string and hands back a **naive** ``datetime`` on the way out, silently
    dropping whatever offset was written. Without this decorator, a work item's
    ``created_at`` would come back naive from SQLite and be rejected outright by
    :class:`~recoup.domain.models.WorkItem`'s own aware-datetime validator — a
    round trip that works in Postgres and fails in SQLite, which is exactly the
    kind of schema difference PRD section 9.6 promises does not exist.

    Every value is normalised to UTC on the way in (so the two dialects agree on
    *which* wall-clock moment a naive-looking SQLite string represents) and
    reattached as UTC on the way out.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTCDateTime requires a timezone-aware datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            # SQLite: the offset was stripped by the driver; the value was
            # normalised to UTC on the way in, so UTC is the correct one to
            # reattach here.
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    """The declarative base shared by every table in this module."""


class WorkItemRow(Base):
    """The persisted, mutable snapshot of one :class:`~recoup.domain.models.WorkItem`.

    Column names mirror the Pydantic model field-for-field; :mod:`recoup.storage.work_items`
    owns the mapping between the two. ``diagnosis`` and ``action`` are stored as JSON
    because they are optional, nested, and read back as a whole object — never
    queried by sub-field except ``diagnosis.cause`` for :meth:`WorkItemRepo.list`
    filtering, which SQLAlchemy's JSON comparator handles portably.
    """

    __tablename__ = "work_items"

    txn_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    """The idempotency key (PRD sections 8.1 and 13.2). The ``UNIQUE`` constraint is
    what makes a duplicate webhook delivery a database-enforced no-op rather than a
    convention callers might forget to check."""

    merchant_id: Mapped[str] = mapped_column(String, nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    """``BigInteger`` rather than ``Integer``: the domain model places no upper bound
    on an amount (only the constraint gate's ``max_amount_paise`` does, and that is
    policy, not a type limit), so the column should not silently wrap a value the
    model would accept."""
    currency: Mapped[str] = mapped_column(String, nullable=False, default="INR")
    failure_code: Mapped[str] = mapped_column(String, nullable=False)
    failure_message: Mapped[str] = mapped_column(String, nullable=False)
    failure_type: Mapped[str] = mapped_column(String, nullable=False)
    method: Mapped[str | None] = mapped_column(String, nullable=True)
    issuer: Mapped[str | None] = mapped_column(String, nullable=True)
    customer: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    fraud_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    """Indexed: the dashboard's default ordering (PRD section 8.8) and
    :meth:`WorkItemRepo.list`'s keyset cursor both sort on this column."""

    state: Mapped[str] = mapped_column(String, nullable=False, index=True)
    """Indexed: the dashboard filters the work-item table by state."""

    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    diagnosis: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    action: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class AuditEventRow(Base):
    """One append-only row of :class:`~recoup.domain.models.AuditEvent`.

    ``id`` is the autoincrement primary key and, because a primary key is always
    indexed, it already satisfies the brief's "index ``id`` ascending for the
    ``since_id`` cursor" requirement without a second, redundant index.
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    txn_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    """Indexed: :meth:`AuditLog.for_txn` is a per-transaction lookup."""

    from_state: Mapped[str | None] = mapped_column(String, nullable=True)
    to_state: Mapped[str] = mapped_column(String, nullable=False)
    diagnosis_cause: Mapped[str | None] = mapped_column(String, nullable=True)
    diagnosis_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    action_chosen: Mapped[str | None] = mapped_column(String, nullable=True)
    constraint_result: Mapped[str | None] = mapped_column(String, nullable=True)
    constraint_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    rationale: Mapped[str] = mapped_column(String, nullable=False)


def _ddl(text: str) -> DDL:
    """Construct a :class:`~sqlalchemy.schema.DDL` clause.

    A thin, typed wrapper: ``DDL.__init__`` itself has no type annotations, so
    every direct call is an ``[no-untyped-call]`` error under mypy strict.
    Isolating the one ``type: ignore`` here means every DDL statement below stays
    fully checked everywhere else.
    """
    return DDL(text)  # type: ignore[no-untyped-call]


_SQLITE_NO_UPDATE = _ddl(
    """
    CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events
    BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
    """
)

_SQLITE_NO_DELETE = _ddl(
    """
    CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events
    BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
    """
)

_POSTGRES_GUARD_FUNCTION = _ddl(
    """
    CREATE OR REPLACE FUNCTION audit_events_block_mutation() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'audit_events is append-only';
    END;
    $$ LANGUAGE plpgsql;
    """
)

_POSTGRES_NO_UPDATE = _ddl(
    """
    CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_block_mutation();
    """
)

_POSTGRES_NO_DELETE = _ddl(
    """
    CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_block_mutation();
    """
)

_POSTGRES_REVOKE = _ddl("REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC;")

# Attached to "after_create" so the triggers exist the instant the table does —
# there is no window between `init_schema` creating `audit_events` and the table
# becoming genuinely append-only.
listen(
    AuditEventRow.__table__,
    "after_create",
    _SQLITE_NO_UPDATE.execute_if(dialect="sqlite"),
)
listen(
    AuditEventRow.__table__,
    "after_create",
    _SQLITE_NO_DELETE.execute_if(dialect="sqlite"),
)
listen(
    AuditEventRow.__table__,
    "after_create",
    _POSTGRES_GUARD_FUNCTION.execute_if(dialect="postgresql"),
)
listen(
    AuditEventRow.__table__,
    "after_create",
    _POSTGRES_NO_UPDATE.execute_if(dialect="postgresql"),
)
listen(
    AuditEventRow.__table__,
    "after_create",
    _POSTGRES_NO_DELETE.execute_if(dialect="postgresql"),
)
listen(
    AuditEventRow.__table__,
    "after_create",
    _POSTGRES_REVOKE.execute_if(dialect="postgresql"),
)
