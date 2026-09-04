"""Proof that ``audit_events`` is physically append-only (PRD section 8.6).

This is the test the whole phase exists to make pass. If the database ever stops
refusing an ``UPDATE`` or a ``DELETE`` on this table, "append-only, never updated,
never deleted" stops being true of the running system and becomes only a claim in
a docstring — so these tests issue the mutation directly in SQL, not through any
Recoup code, to prove the refusal is the database's, not the application's.
"""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from recoup.storage.audit import AuditLog
from tests.conftest import make_audit_event


def test_audit_row_cannot_be_updated(engine: Engine) -> None:
    """SQLite's ``RAISE(ABORT, ...)`` surfaces to the driver as a constraint
    violation (``sqlite3.IntegrityError``), not a generic operational failure — so
    this asserts on :class:`~sqlalchemy.exc.DBAPIError`, the common base every
    driver-level failure shares, rather than pinning to one SQLite-specific
    subclass that a different dialect would not raise."""
    audit_log = AuditLog(engine)
    event = make_audit_event(rationale="Original rationale, never to be overwritten.")
    row_id = audit_log.append(event)

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
    [stored] = audit_log.for_txn(event.txn_id)
    assert stored.rationale == "Original rationale, never to be overwritten."


def test_audit_row_cannot_be_deleted(engine: Engine) -> None:
    audit_log = AuditLog(engine)
    event = make_audit_event()
    audit_log.append(event)
    before_count = len(audit_log.list_since(0))

    with engine.connect() as conn:
        try:
            with pytest.raises(DBAPIError) as exc:
                conn.execute(text("DELETE FROM audit_events"))
        finally:
            conn.rollback()

    assert "append-only" in str(exc.value)
    assert len(audit_log.list_since(0)) == before_count


def test_audit_log_class_exposes_no_mutation_methods() -> None:
    """The absence is deliberate (see the ``AuditLog`` class docstring): no public
    attribute name may contain ``update``, ``delete`` or ``remove``."""
    forbidden_substrings = ("update", "delete", "remove")
    public_attrs = [name for name in dir(AuditLog) if not name.startswith("_")]

    assert public_attrs, "sanity check: AuditLog must expose at least its public API"
    offenders = [
        name for name in public_attrs if any(bad in name.lower() for bad in forbidden_substrings)
    ]
    assert offenders == []
