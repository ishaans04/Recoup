"""Behavioural tests for :class:`~recoup.storage.audit.AuditLog`.

Immutability is proven in ``test_audit_immutability.py``; this file proves the log
is otherwise a correct, ordered, atomic append log.
"""

from datetime import timedelta

import pytest
from sqlalchemy import Engine

from recoup.domain.enums import State
from recoup.storage.audit import AuditLog
from recoup.storage.db import unit_of_work
from tests.conftest import CREATED_AT, make_audit_event


def test_ids_are_strictly_monotonic_across_appends(engine: Engine) -> None:
    audit_log = AuditLog(engine)

    first = audit_log.append(make_audit_event(txn_id="pay_A"))
    second = audit_log.append(make_audit_event(txn_id="pay_B"))
    third = audit_log.append(make_audit_event(txn_id="pay_A"))

    assert first < second < third


def test_list_since_returns_only_newer_rows_ascending(engine: Engine) -> None:
    audit_log = AuditLog(engine)
    ids = [audit_log.append(make_audit_event(txn_id=f"pay_{i}")) for i in range(5)]

    result = audit_log.list_since(ids[1])

    assert [event.id for event in result] == ids[2:]
    assert all(event.id is not None and event.id > ids[1] for event in result)


def test_list_since_honours_limit(engine: Engine) -> None:
    audit_log = AuditLog(engine)
    for i in range(5):
        audit_log.append(make_audit_event(txn_id=f"pay_{i}"))

    result = audit_log.list_since(0, limit=2)

    assert len(result) == 2
    assert result[0].id is not None and result[1].id is not None
    assert result[0].id < result[1].id


def test_list_since_with_nothing_newer_returns_empty(engine: Engine) -> None:
    audit_log = AuditLog(engine)
    last_id = audit_log.append(make_audit_event())

    assert audit_log.list_since(last_id) == []


def test_for_txn_filters_and_orders_ascending(engine: Engine) -> None:
    audit_log = AuditLog(engine)
    audit_log.append(
        make_audit_event(txn_id="pay_A", to_state=State.DETECTED, timestamp=CREATED_AT)
    )
    audit_log.append(
        make_audit_event(
            txn_id="pay_B", to_state=State.DETECTED, timestamp=CREATED_AT + timedelta(seconds=1)
        )
    )
    audit_log.append(
        make_audit_event(
            txn_id="pay_A",
            to_state=State.DIAGNOSED,
            timestamp=CREATED_AT + timedelta(seconds=2),
        )
    )

    result = audit_log.for_txn("pay_A")

    assert [event.to_state for event in result] == [State.DETECTED, State.DIAGNOSED]
    assert all(event.txn_id == "pay_A" for event in result)
    assert result[0].id is not None and result[1].id is not None
    assert result[0].id < result[1].id


def test_for_txn_with_no_events_returns_empty(engine: Engine) -> None:
    audit_log = AuditLog(engine)
    audit_log.append(make_audit_event(txn_id="pay_A"))

    assert audit_log.for_txn("pay_never_seen") == []


def test_append_returns_the_id_assigned_by_the_database(engine: Engine) -> None:
    audit_log = AuditLog(engine)

    assigned_id = audit_log.append(make_audit_event())

    [stored] = audit_log.list_since(0)
    assert stored.id == assigned_id


def test_append_inside_a_supplied_session_joins_the_caller_transaction(engine: Engine) -> None:
    """No commit happens until the caller's ``with unit_of_work(...)`` block exits."""
    audit_log = AuditLog(engine)

    with unit_of_work(engine) as session:
        audit_log.append(make_audit_event(txn_id="pay_joined"), session=session)
        # Not yet committed: a second, independent read sees nothing.
        assert audit_log.list_since(0) == []

    assert len(audit_log.list_since(0)) == 1


def test_append_inside_a_session_that_then_rolls_back_leaves_no_row(engine: Engine) -> None:
    audit_log = AuditLog(engine)

    with pytest.raises(RuntimeError), unit_of_work(engine) as session:
        audit_log.append(make_audit_event(txn_id="pay_doomed"), session=session)
        raise RuntimeError("simulated failure after the append")

    assert audit_log.list_since(0) == []
