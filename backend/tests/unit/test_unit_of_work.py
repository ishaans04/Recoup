"""Tests for :func:`~recoup.storage.db.unit_of_work`.

The property under test is the one PRD section 8.6's completeness claim depends
on: a work-item checkpoint and its audit append share one transaction, so they
persist together or not at all. Phase 2's ``StateMachine.transition`` is built on
this guarantee. These tests write directly through the ORM tables — the audit log
and work-item repository that will normally do this do not exist yet at this
point in the build — because ``unit_of_work`` itself is generic infrastructure
that does not depend on either.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select

from recoup.storage.db import unit_of_work
from recoup.storage.tables import AuditEventRow, WorkItemRow

_CREATED_AT = datetime(2026, 9, 3, 14, 32, 5, tzinfo=UTC)


def _work_item_row(txn_id: str) -> WorkItemRow:
    return WorkItemRow(
        txn_id=txn_id,
        event_id=f"evt_{txn_id}",
        merchant_id="acc_MerchantDemo01",
        amount_paise=249900,
        currency="INR",
        failure_code="BAD_REQUEST_ERROR",
        failure_message="Your card has insufficient balance to complete this payment.",
        failure_type="subscription",
        customer={"name": "Ananya Rao"},
        fraud_flag=False,
        created_at=_CREATED_AT,
        state="DETECTED",
        retry_count=0,
    )


def _audit_event_row(txn_id: str) -> AuditEventRow:
    return AuditEventRow(
        timestamp=_CREATED_AT,
        txn_id=txn_id,
        to_state="DETECTED",
        rationale="Webhook payment.failed accepted; work item created.",
    )


def test_a_work_item_and_an_audit_row_both_persist_on_commit(engine: Engine) -> None:
    with unit_of_work(engine) as session:
        session.add(_work_item_row("pay_A"))
        session.add(_audit_event_row("pay_A"))

    with engine.connect() as conn:
        assert conn.execute(
            select(WorkItemRow.txn_id).where(WorkItemRow.txn_id == "pay_A")
        ).scalar_one_or_none() == "pay_A"
        assert (
            conn.execute(
                select(AuditEventRow.txn_id).where(AuditEventRow.txn_id == "pay_A")
            ).scalar_one_or_none()
            == "pay_A"
        )


def test_an_exception_inside_the_unit_rolls_back_both_writes(engine: Engine) -> None:
    with pytest.raises(RuntimeError), unit_of_work(engine) as session:
        session.add(_work_item_row("pay_B"))
        session.add(_audit_event_row("pay_B"))
        raise RuntimeError("simulated failure after both writes")

    with engine.connect() as conn:
        assert (
            conn.execute(
                select(WorkItemRow.txn_id).where(WorkItemRow.txn_id == "pay_B")
            ).scalar_one_or_none()
            is None
        )
        assert (
            conn.execute(
                select(AuditEventRow.txn_id).where(AuditEventRow.txn_id == "pay_B")
            ).scalar_one_or_none()
            is None
        )


def test_the_yielded_session_is_not_committed_until_the_block_exits_cleanly(
    engine: Engine,
) -> None:
    with unit_of_work(engine) as session:
        session.add(_work_item_row("pay_C"))
        # A second, independent connection must not see the uncommitted write.
        with engine.connect() as other_conn:
            assert (
                other_conn.execute(
                    select(WorkItemRow.txn_id).where(WorkItemRow.txn_id == "pay_C")
                ).scalar_one_or_none()
                is None
            )

    with engine.connect() as conn:
        assert (
            conn.execute(
                select(WorkItemRow.txn_id).where(WorkItemRow.txn_id == "pay_C")
            ).scalar_one_or_none()
            == "pay_C"
        )
