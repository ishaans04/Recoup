"""Behavioural tests for :class:`~recoup.storage.work_items.WorkItemRepo`."""

from datetime import timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from recoup.domain.enums import ActionType, Cause, Channel, FailureType, State
from recoup.domain.models import Action, Customer, Diagnosis
from recoup.storage.db import unit_of_work
from recoup.storage.tables import WorkItemRow
from recoup.storage.work_items import WorkItemRepo, encode_cursor
from tests.conftest import CREATED_AT, make_work_item

# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #


def test_create_if_absent_is_idempotent_on_event_id(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    item = make_work_item()

    first_item, first_created = repo.create_if_absent(item)
    second_item, second_created = repo.create_if_absent(
        make_work_item(txn_id="pay_ADifferentTxnId", merchant_id="acc_Other")
    )

    assert first_created is True
    assert second_created is False
    assert second_item == first_item
    assert repo.count_by_state() == {State.DETECTED: 1}


def test_create_if_absent_does_not_raise_on_duplicate_event_id(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    repo.create_if_absent(make_work_item())

    # Must not raise even though the underlying insert violates the unique constraint.
    _, created = repo.create_if_absent(make_work_item(txn_id="pay_SecondDelivery"))

    assert created is False


def test_create_if_absent_with_a_fresh_event_id_creates_a_second_row(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    repo.create_if_absent(make_work_item())

    _, created = repo.create_if_absent(
        make_work_item(txn_id="pay_Second", event_id="evt_Second")
    )

    assert created is True
    assert repo.count_by_state() == {State.DETECTED: 2}


def test_create_if_absent_savepoint_does_not_roll_back_sibling_writes(engine: Engine) -> None:
    """The duplicate-``event_id`` path rolls back only its own ``SAVEPOINT``; an
    unrelated write earlier in the same caller-supplied transaction must survive."""
    repo = WorkItemRepo(engine)
    repo.create_if_absent(make_work_item())  # pre-existing, committed row

    with unit_of_work(engine) as session:
        sibling = make_work_item(txn_id="pay_Sibling", event_id="evt_Sibling")
        repo.save(sibling, session=session)

        _, created = repo.create_if_absent(
            make_work_item(txn_id="pay_DuplicateAttempt"), session=session
        )
        assert created is False

    assert repo.get("pay_Sibling") is not None


def test_unique_constraint_is_enforced_by_the_database(engine: Engine) -> None:
    """A direct second insert, bypassing the repository entirely, still fails."""
    with Session(engine) as session:
        session.add(
            WorkItemRow(
                txn_id="pay_First",
                event_id="evt_Shared",
                merchant_id="acc_A",
                amount_paise=1000,
                currency="INR",
                failure_code="X",
                failure_message="x",
                failure_type=FailureType.ONE_TIME.value,
                customer={"name": "A"},
                fraud_flag=False,
                created_at=CREATED_AT,
                state=State.DETECTED.value,
                retry_count=0,
            )
        )
        session.commit()

        session.add(
            WorkItemRow(
                txn_id="pay_Second",
                event_id="evt_Shared",
                merchant_id="acc_A",
                amount_paise=1000,
                currency="INR",
                failure_code="X",
                failure_message="x",
                failure_type=FailureType.ONE_TIME.value,
                customer={"name": "A"},
                fraud_flag=False,
                created_at=CREATED_AT,
                state=State.DETECTED.value,
                retry_count=0,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


# --------------------------------------------------------------------------- #
# get / save round trip
# --------------------------------------------------------------------------- #


def test_get_returns_none_for_an_unknown_txn_id(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    assert repo.get("pay_DoesNotExist") is None


def test_save_and_get_round_trip_with_full_nested_state(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    item = make_work_item(
        state=State.EXECUTED,
        retry_count=2,
        customer=Customer(name="Rohit Mehta", phone="+919876500000", email=None),
        diagnosis=Diagnosis(
            cause=Cause.INSUFFICIENT_FUNDS,
            confidence=0.96,
            rationale="Issuer message names an insufficient balance.",
            source="rules",
        ),
        action=Action(
            type=ActionType.SCHEDULED_RETRY,
            channel=Channel.PAYMENT_RETRY,
            scheduled_for=CREATED_AT + timedelta(days=20),
            attempt=2,
            reason="Insufficient funds: retry near the salary cycle.",
        ),
    )

    repo.save(item)
    restored = repo.get(item.txn_id)

    assert restored == item
    assert restored is not None
    assert restored.diagnosis is not None and restored.diagnosis.cause is Cause.INSUFFICIENT_FUNDS
    assert restored.action is not None and restored.action.attempt == 2


def test_save_is_a_full_checkpoint_that_overwrites_prior_fields(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    item = make_work_item(state=State.DETECTED, retry_count=0)
    repo.save(item)

    updated = item.model_copy(update={"state": State.DIAGNOSED, "retry_count": 1})
    repo.save(updated)

    restored = repo.get(item.txn_id)
    assert restored is not None
    assert restored.state is State.DIAGNOSED
    assert restored.retry_count == 1


def test_save_without_diagnosis_or_action_round_trips_nulls(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    item = make_work_item()

    repo.save(item)
    restored = repo.get(item.txn_id)

    assert restored is not None
    assert restored.diagnosis is None
    assert restored.action is None


# --------------------------------------------------------------------------- #
# list: filtering
# --------------------------------------------------------------------------- #


def _seed_varied_items(repo: WorkItemRepo) -> None:
    repo.save(
        make_work_item(
            txn_id="pay_1",
            event_id="evt_1",
            state=State.DIAGNOSED,
            created_at=CREATED_AT,
            diagnosis=Diagnosis(
                cause=Cause.INSUFFICIENT_FUNDS,
                confidence=0.9,
                rationale="Rules match.",
                source="rules",
            ),
        )
    )
    repo.save(
        make_work_item(
            txn_id="pay_2",
            event_id="evt_2",
            state=State.RESOLVED,
            created_at=CREATED_AT + timedelta(seconds=1),
            diagnosis=Diagnosis(
                cause=Cause.SOFT_DECLINE,
                confidence=0.8,
                rationale="Transient decline.",
                source="rules",
            ),
        )
    )
    repo.save(
        make_work_item(
            txn_id="pay_3",
            event_id="evt_3",
            state=State.DIAGNOSED,
            created_at=CREATED_AT + timedelta(seconds=2),
        )
    )


def test_list_filters_by_state(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    _seed_varied_items(repo)

    result = repo.list(state=State.DIAGNOSED)

    assert {item.txn_id for item in result} == {"pay_1", "pay_3"}


def test_list_filters_by_cause(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    _seed_varied_items(repo)

    result = repo.list(cause=Cause.INSUFFICIENT_FUNDS)

    assert {item.txn_id for item in result} == {"pay_1"}


def test_list_with_no_diagnosis_never_matches_a_cause_filter(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    _seed_varied_items(repo)

    result = repo.list(cause=Cause.SOFT_DECLINE)

    assert {item.txn_id for item in result} == {"pay_2"}


def test_list_defaults_to_newest_first(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    _seed_varied_items(repo)

    result = repo.list(limit=10)

    assert [item.txn_id for item in result] == ["pay_3", "pay_2", "pay_1"]


# --------------------------------------------------------------------------- #
# list: keyset pagination
# --------------------------------------------------------------------------- #


def test_list_respects_limit(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    for i in range(5):
        repo.save(
            make_work_item(
                txn_id=f"pay_{i}",
                event_id=f"evt_{i}",
                created_at=CREATED_AT + timedelta(seconds=i),
            )
        )

    result = repo.list(limit=2)

    assert len(result) == 2


def test_list_paginates_without_repeating_or_skipping_rows(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    for i in range(5):
        repo.save(
            make_work_item(
                txn_id=f"pay_{i}",
                event_id=f"evt_{i}",
                created_at=CREATED_AT + timedelta(seconds=i),
            )
        )

    first_page = repo.list(limit=2)
    cursor = encode_cursor(first_page[-1])
    second_page = repo.list(limit=2, cursor=cursor)
    cursor_2 = encode_cursor(second_page[-1])
    third_page = repo.list(limit=2, cursor=cursor_2)

    all_ids = [item.txn_id for item in (*first_page, *second_page, *third_page)]
    assert all_ids == ["pay_4", "pay_3", "pay_2", "pay_1", "pay_0"]
    assert len(set(all_ids)) == 5  # no repeats
    assert len(third_page) == 1  # last page is a partial page, not an off-by-one repeat


def test_list_paginates_correctly_when_created_at_ties(engine: Engine) -> None:
    """A batch run inserts many items in the same instant; txn_id must break the tie."""
    repo = WorkItemRepo(engine)
    for i in range(4):
        repo.save(
            make_work_item(txn_id=f"pay_{i}", event_id=f"evt_{i}", created_at=CREATED_AT)
        )

    first_page = repo.list(limit=2)
    cursor = encode_cursor(first_page[-1])
    second_page = repo.list(limit=2, cursor=cursor)

    all_ids = {item.txn_id for item in (*first_page, *second_page)}
    assert all_ids == {"pay_0", "pay_1", "pay_2", "pay_3"}


# --------------------------------------------------------------------------- #
# count_by_state
# --------------------------------------------------------------------------- #


def test_count_by_state_matches_a_hand_counted_fixture(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    repo.save(make_work_item(txn_id="pay_1", event_id="evt_1", state=State.DETECTED))
    repo.save(make_work_item(txn_id="pay_2", event_id="evt_2", state=State.DETECTED))
    repo.save(make_work_item(txn_id="pay_3", event_id="evt_3", state=State.RESOLVED))
    repo.save(make_work_item(txn_id="pay_4", event_id="evt_4", state=State.ESCALATED))

    assert repo.count_by_state() == {
        State.DETECTED: 2,
        State.RESOLVED: 1,
        State.ESCALATED: 1,
    }


def test_count_by_state_omits_states_with_no_rows(engine: Engine) -> None:
    repo = WorkItemRepo(engine)
    repo.save(make_work_item())

    counts = repo.count_by_state()

    assert State.SCHEDULED not in counts
