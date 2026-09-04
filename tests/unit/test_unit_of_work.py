"""Tests for :func:`~recoup.storage.db.unit_of_work`.

The property under test is the one PRD section 8.6's completeness claim depends
on: a work-item checkpoint and its audit append share one transaction, so they
persist together or not at all. Phase 2's ``StateMachine.transition`` is built on
this guarantee.
"""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from recoup.domain.enums import State
from recoup.storage.audit import AuditLog
from recoup.storage.db import init_schema, unit_of_work
from recoup.storage.work_items import WorkItemRepo
from tests.conftest import make_audit_event, make_work_item


def test_a_work_item_save_and_an_audit_append_both_persist_on_commit(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    audit_log = AuditLog(engine)
    item = make_work_item()

    with unit_of_work(engine) as session:
        repo.save(item, session=session)
        audit_log.append(
            make_audit_event(txn_id=item.txn_id, to_state=State.DETECTED), session=session
        )

    assert repo.get(item.txn_id) is not None
    assert len(audit_log.for_txn(item.txn_id)) == 1


def test_an_exception_inside_the_unit_rolls_back_both_writes(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    audit_log = AuditLog(engine)
    item = make_work_item()

    with pytest.raises(RuntimeError), unit_of_work(engine) as session:
        repo.save(item, session=session)
        audit_log.append(
            make_audit_event(txn_id=item.txn_id, to_state=State.DETECTED), session=session
        )
        raise RuntimeError("simulated failure after both writes")

    assert repo.get(item.txn_id) is None
    assert audit_log.for_txn(item.txn_id) == []


def test_the_yielded_session_is_not_committed_until_the_block_exits_cleanly(
    engine: Engine,
) -> None:
    repo = WorkItemRepo(engine)
    item = make_work_item()

    with unit_of_work(engine) as session:
        repo.save(item, session=session)
        # A second, independent repository read must not see the uncommitted write.
        assert repo.get(item.txn_id) is None

    assert repo.get(item.txn_id) is not None


def test_init_schema_is_idempotent(engine: Engine) -> None:
    """The ``engine`` fixture already called ``init_schema`` once; calling it again
    against the same engine must not raise, and the append-only triggers — created
    only alongside a freshly-created ``audit_events`` table — must still be in
    force, proving the second call did not silently skip attaching them."""
    init_schema(engine)  # second call: must be a genuine no-op, not an error

    audit_log = AuditLog(engine)
    row_id = audit_log.append(make_audit_event())

    with engine.connect() as conn:
        try:
            with pytest.raises(DBAPIError) as exc:
                conn.execute(text("DELETE FROM audit_events WHERE id = :id"), {"id": row_id})
        finally:
            conn.rollback()

    assert "append-only" in str(exc.value)
