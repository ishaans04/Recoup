"""Proof that ``audit_events`` is physically append-only (PRD section 8.6).

This is the test the whole phase exists to make pass. If the database ever stops
refusing an ``UPDATE`` or a ``DELETE`` on this table, "append-only, never updated,
never deleted" stops being true of the running system and becomes only a claim in
a docstring — so these tests issue the mutation directly in SQL against a row
inserted through SQLAlchemy Core (not through any Recoup application code, which
does not exist yet at this point in the build) to prove the refusal is the
database's own, not merely something the application layer chooses not to do.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, insert, select, text
from sqlalchemy.exc import DBAPIError

from recoup.storage.tables import AuditEventRow

_TIMESTAMP = datetime(2026, 9, 3, 14, 32, 5, tzinfo=UTC)


def _insert_row(engine: Engine, rationale: str) -> int:
    with engine.begin() as conn:
        result = conn.execute(
            insert(AuditEventRow).values(
                timestamp=_TIMESTAMP,
                txn_id="pay_QjK9x2LmN4TzAb",
                to_state="DETECTED",
                rationale=rationale,
            )
        )
        inserted_id = result.inserted_primary_key
        assert inserted_id is not None
        return int(inserted_id[0])


def test_audit_row_cannot_be_updated(engine: Engine) -> None:
    """SQLite's ``RAISE(ABORT, ...)`` surfaces to the driver as a constraint
    violation (``sqlite3.IntegrityError``), not a generic operational failure — so
    this asserts on :class:`~sqlalchemy.exc.DBAPIError`, the common base every
    driver-level failure shares, rather than pinning to one SQLite-specific
    subclass that a different dialect would not raise."""
    row_id = _insert_row(engine, "Original rationale, never to be overwritten.")

    with engine.connect() as conn:
        try:
            with pytest.raises(DBAPIError) as exc:
                conn.execute(
                    text("UPDATE audit_events SET rationale = 'tampered' WHERE id = :id"),
                    {"id": row_id},
                )
        finally:
            conn.rollback()

    assert "append-only" in str(exc.value)

    with engine.connect() as conn:
        stored_rationale = conn.execute(
            select(AuditEventRow.rationale).where(AuditEventRow.id == row_id)
        ).scalar_one()
    assert stored_rationale == "Original rationale, never to be overwritten."


def test_audit_row_cannot_be_deleted(engine: Engine) -> None:
    _insert_row(engine, "Irrelevant to this test.")
    with engine.connect() as conn:
        ids_before = conn.execute(select(AuditEventRow.id)).scalars().all()

    with engine.connect() as conn:
        try:
            with pytest.raises(DBAPIError) as exc:
                conn.execute(text("DELETE FROM audit_events"))
        finally:
            conn.rollback()

    assert "append-only" in str(exc.value)

    with engine.connect() as conn:
        ids_after = conn.execute(select(AuditEventRow.id)).scalars().all()
    assert ids_after == ids_before
