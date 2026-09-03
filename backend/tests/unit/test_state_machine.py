"""Tests for :class:`recoup.fsm.machine.StateMachine`.

The properties under test are the three the whole system leans on (PRD sections 4,
7.4, 8.6, 12.2): a legal transition is persisted *and* audited as one atomic unit;
an illegal or post-terminal transition changes nothing; and a failed audit append
rolls the state change back with it. That last one is the Phase 1 ``unit_of_work``
guarantee proven at the layer that first depends on it.
"""


import pytest
from sqlalchemy import Engine, text

from recoup.clock import SimulatedClock
from recoup.domain.enums import ActionType, Cause, Channel, State
from recoup.domain.models import Action, Diagnosis, WorkItem
from recoup.fsm.machine import IllegalTransition, StateMachine, TerminalStateError
from recoup.storage.audit import AuditLog
from recoup.storage.work_items import WorkItemRepo
from tests.conftest import CREATED_AT, make_work_item


@pytest.fixture
def clock() -> SimulatedClock:
    return SimulatedClock(start=CREATED_AT)


@pytest.fixture
def repo(engine: Engine) -> WorkItemRepo:
    return WorkItemRepo(engine)


@pytest.fixture
def audit(engine: Engine) -> AuditLog:
    return AuditLog(engine)


@pytest.fixture
def machine(
    engine: Engine, audit: AuditLog, repo: WorkItemRepo, clock: SimulatedClock
) -> StateMachine:
    return StateMachine(engine, audit, repo, clock)


@pytest.fixture
def detected_item(repo: WorkItemRepo) -> WorkItem:
    """A persisted work item in the initial ``DETECTED`` state."""
    item, _ = repo.create_if_absent(make_work_item(state=State.DETECTED))
    return item


def _audit_rows(engine: Engine) -> list[dict[str, object]]:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM audit_events ORDER BY id"))
        return [dict(row._mapping) for row in result]


def test_legal_transition_persists_state_and_writes_one_audit_row(
    machine: StateMachine, repo: WorkItemRepo, engine: Engine, detected_item: WorkItem
) -> None:
    updated = machine.transition(
        detected_item,
        State.DIAGNOSED,
        rationale="diagnosed as insufficient_funds via rules",
        diagnosis=Diagnosis(
            cause=Cause.INSUFFICIENT_FUNDS,
            confidence=1.0,
            rationale="failure code maps to insufficient funds",
            source="rules",
        ),
    )

    assert updated.state is State.DIAGNOSED
    assert repo.get(detected_item.txn_id).state is State.DIAGNOSED

    rows = _audit_rows(engine)
    assert len(rows) == 1
    assert rows[0]["from_state"] == State.DETECTED.value
    assert rows[0]["to_state"] == State.DIAGNOSED.value
    assert rows[0]["diagnosis_cause"] == Cause.INSUFFICIENT_FUNDS.value
    assert rows[0]["diagnosis_confidence"] == 1.0


def test_illegal_transition_raises_and_changes_nothing(
    machine: StateMachine, repo: WorkItemRepo, engine: Engine, detected_item: WorkItem
) -> None:
    with pytest.raises(IllegalTransition) as exc:
        machine.transition(detected_item, State.RESOLVED, rationale="skip the whole lifecycle")

    # Both states named, for a caller diagnosing a stale item vs a wrong target.
    assert State.DETECTED.value in str(exc.value)
    assert State.RESOLVED.value in str(exc.value)
    # Nothing persisted: state unchanged, no audit row.
    assert repo.get(detected_item.txn_id).state is State.DETECTED
    assert _audit_rows(engine) == []


def test_transition_out_of_resolved_raises_terminal_error(
    machine: StateMachine, repo: WorkItemRepo, engine: Engine
) -> None:
    resolved, _ = repo.create_if_absent(make_work_item(state=State.RESOLVED))
    with pytest.raises(TerminalStateError):
        machine.transition(resolved, State.ACTION_CHOSEN, rationale="cannot resurrect")
    assert _audit_rows(engine) == []


def test_transition_out_of_escalated_raises_terminal_error(
    machine: StateMachine, repo: WorkItemRepo
) -> None:
    escalated, _ = repo.create_if_absent(make_work_item(state=State.ESCALATED))
    with pytest.raises(TerminalStateError):
        machine.transition(escalated, State.ACTION_CHOSEN, rationale="cannot revive")


@pytest.mark.parametrize("bad_rationale", ["", "   ", "\n\t"])
def test_empty_rationale_is_rejected(
    machine: StateMachine, engine: Engine, detected_item: WorkItem, bad_rationale: str
) -> None:
    with pytest.raises(ValueError, match="rationale"):
        machine.transition(detected_item, State.DIAGNOSED, rationale=bad_rationale)
    assert _audit_rows(engine) == []


def test_audit_row_records_action_and_constraint_fields(
    machine: StateMachine, repo: WorkItemRepo, engine: Engine
) -> None:
    item, _ = repo.create_if_absent(make_work_item(state=State.ACTION_CHOSEN))
    action = Action(
        type=ActionType.SCHEDULED_RETRY,
        channel=Channel.PAYMENT_RETRY,
        attempt=0,
        reason="insufficient funds; retry near salary cycle",
    )
    machine.transition(
        item,
        State.CONSTRAINT_CHECKED,
        rationale="constraint gate: PASS",
        action=action,
        constraint_result="PASS",
        constraint_reason="all rules passed",
    )
    rows = _audit_rows(engine)
    assert rows[-1]["action_chosen"] == ActionType.SCHEDULED_RETRY.value
    assert rows[-1]["constraint_result"] == "PASS"
    assert rows[-1]["constraint_reason"] == "all rules passed"


def test_failed_audit_append_rolls_back_the_state_change(
    engine: Engine, repo: WorkItemRepo, clock: SimulatedClock, detected_item: WorkItem
) -> None:
    """Atomicity: if the audit append raises, the work item must not advance.

    This is the ``unit_of_work`` guarantee Phase 1 built, proven at the first layer
    that couples a checkpoint to an append.
    """

    class ExplodingAudit(AuditLog):
        def append(self, event: object, session: object = None) -> int:  # type: ignore[override]
            raise RuntimeError("audit sink is down")

    machine = StateMachine(engine, ExplodingAudit(engine), repo, clock)

    with pytest.raises(RuntimeError, match="audit sink is down"):
        machine.transition(detected_item, State.DIAGNOSED, rationale="should roll back")

    # Neither the state change nor any audit row survived.
    assert repo.get(detected_item.txn_id).state is State.DETECTED
    assert _audit_rows(engine) == []


def test_retry_count_increments_only_on_executed_to_action_chosen(
    machine: StateMachine, repo: WorkItemRepo
) -> None:
    executed, _ = repo.create_if_absent(make_work_item(state=State.EXECUTED, retry_count=0))
    retried = machine.transition(
        executed, State.ACTION_CHOSEN, rationale="attempt failed; retrying"
    )
    assert retried.retry_count == 1


def test_retry_count_unchanged_on_other_transitions(
    machine: StateMachine, repo: WorkItemRepo
) -> None:
    executed, _ = repo.create_if_absent(make_work_item(state=State.EXECUTED, retry_count=2))
    resolved = machine.transition(executed, State.RESOLVED, rationale="payment recovered")
    assert resolved.retry_count == 2

    detected, _ = repo.create_if_absent(
        make_work_item(txn_id="pay_other", event_id="evt_other", state=State.DETECTED)
    )
    diagnosed = machine.transition(
        detected,
        State.DIAGNOSED,
        rationale="diagnosed",
        diagnosis=Diagnosis(
            cause=Cause.SOFT_DECLINE, confidence=0.9, rationale="soft decline", source="rules"
        ),
    )
    assert diagnosed.retry_count == 0


def test_transition_returns_fresh_item_without_mutating_caller(
    machine: StateMachine, detected_item: WorkItem
) -> None:
    original_state = detected_item.state
    updated = machine.transition(
        detected_item,
        State.DIAGNOSED,
        rationale="diagnosed",
        diagnosis=Diagnosis(
            cause=Cause.INSUFFICIENT_FUNDS, confidence=1.0, rationale="rules", source="rules"
        ),
    )
    assert detected_item.state is original_state  # caller's instance untouched
    assert updated.state is State.DIAGNOSED
    assert updated is not detected_item
