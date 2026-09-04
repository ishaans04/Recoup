"""Tests for :class:`recoup.fsm.orchestrator.Orchestrator`.

The orchestrator is driven entirely by injected collaborators, so these tests build
fakes for ``diagnose``/``select_action``/``check_and_execute`` and assert the routing
policy of PRD section 7.4: the happy path resolves; a gate refusal escalates; a
future-dated action parks in ``SCHEDULED`` and later executes; a failed execution
with budget remaining loops back and increments ``retry_count``. One structural test
(``test_orchestrator_imports_no_external_service``) enforces PRD section 8.2 — the
orchestrator never imports a gateway, channel or LLM — by reading the module's own
AST rather than trusting its docstring.
"""

import ast
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

import recoup.fsm.orchestrator as orchestrator_module
from recoup.clock import SimulatedClock
from recoup.domain.enums import ActionType, Cause, Channel, State
from recoup.domain.models import Action, Diagnosis, WorkItem
from recoup.fsm.machine import StateMachine, TerminalStateError
from recoup.fsm.orchestrator import GateOutcome, Orchestrator, OrchestratorDeps
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
def machine(engine: Engine, repo: WorkItemRepo, clock: SimulatedClock) -> StateMachine:
    return StateMachine(engine, AuditLog(engine), repo, clock)


def _diagnosis(cause: Cause = Cause.SOFT_DECLINE) -> Diagnosis:
    return Diagnosis(
        cause=cause, confidence=0.9, rationale=f"diagnosed {cause.value}", source="rules"
    )


def _action(
    action_type: ActionType = ActionType.IMMEDIATE_RETRY, scheduled_for: object = None
) -> Action:
    return Action(
        type=action_type,
        channel=Channel.PAYMENT_RETRY,
        attempt=0,
        reason="test action",
        scheduled_for=scheduled_for,  # type: ignore[arg-type]
    )


def _pass_outcome(
    *, executed: bool = True, recovered: bool = False, escalate: str | None = None
) -> GateOutcome:
    return GateOutcome(
        executed=executed,
        recovered=recovered,
        escalate_reason=escalate,
        constraint_result="PASS",
        constraint_reason="all rules passed",
        outcome_detail="retry attempted" if executed else None,
    )


def _fail_outcome() -> GateOutcome:
    return GateOutcome(
        executed=False,
        recovered=False,
        escalate_reason="amount_cap: Rs 75,000 > Rs 50,000",
        constraint_result="FAIL",
        constraint_reason="amount_cap: Rs 75,000 > Rs 50,000",
        outcome_detail=None,
    )


def _deps(
    *,
    diagnosis: Diagnosis | None = None,
    action: Action | None = None,
    outcomes: list[GateOutcome] | None = None,
) -> tuple[OrchestratorDeps, dict[str, int]]:
    """Build deps with fakes, returning a call-count dict for assertions."""
    counts = {"diagnose": 0, "select": 0, "check": 0}
    the_diagnosis = diagnosis or _diagnosis()
    the_action = action or _action()
    outcome_queue = list(outcomes or [_pass_outcome(recovered=True)])

    async def diagnose(item: WorkItem) -> Diagnosis:
        counts["diagnose"] += 1
        return the_diagnosis

    def select_action(item: WorkItem, diag: Diagnosis) -> Action:
        counts["select"] += 1
        return the_action

    async def check_and_execute(item: WorkItem, act: Action) -> GateOutcome:
        counts["check"] += 1
        return outcome_queue.pop(0) if outcome_queue else _pass_outcome(recovered=True)

    return OrchestratorDeps(diagnose, select_action, check_and_execute), counts


def _audit_count(engine: Engine, txn_id: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM audit_events WHERE txn_id = :t"), {"t": txn_id}
        ).scalar_one()


async def test_happy_path_walks_to_resolved_with_one_row_per_transition(
    machine: StateMachine, repo: WorkItemRepo, engine: Engine, clock: SimulatedClock
) -> None:
    item, _ = repo.create_if_absent(make_work_item(state=State.DETECTED))
    deps, counts = _deps(outcomes=[_pass_outcome(executed=True, recovered=True)])
    orch = Orchestrator(machine, deps, clock)

    final = await orch.run_to_completion(item)

    assert final.state is State.RESOLVED
    # DETECTED->DIAGNOSED->ACTION_CHOSEN->CONSTRAINT_CHECKED->EXECUTED->RESOLVED = 5 rows.
    assert _audit_count(engine, item.txn_id) == 5
    assert counts == {"diagnose": 1, "select": 1, "check": 1}


async def test_gate_refusal_routes_to_escalated_with_reason(
    machine: StateMachine, repo: WorkItemRepo, engine: Engine, clock: SimulatedClock
) -> None:
    item, _ = repo.create_if_absent(make_work_item(state=State.DETECTED, amount_paise=7_500_000))
    deps, _ = _deps(outcomes=[_fail_outcome()])
    orch = Orchestrator(machine, deps, clock)

    final = await orch.run_to_completion(item)

    assert final.state is State.ESCALATED
    with engine.connect() as conn:
        reason = conn.execute(
            text(
                "SELECT rationale FROM audit_events WHERE txn_id = :t AND to_state = 'ESCALATED'"
            ),
            {"t": item.txn_id},
        ).scalar_one()
    assert "amount_cap" in reason


async def test_scheduled_action_parks_then_executes_after_clock_advances(
    machine: StateMachine, repo: WorkItemRepo, clock: SimulatedClock
) -> None:
    item, _ = repo.create_if_absent(make_work_item(state=State.DETECTED))
    future = CREATED_AT + timedelta(days=3)
    scheduled_action = _action(ActionType.SCHEDULED_RETRY, scheduled_for=future)
    # First check defers (executed=False); the on-schedule check recovers.
    deps, _ = _deps(
        action=scheduled_action,
        outcomes=[_pass_outcome(executed=False), _pass_outcome(executed=True, recovered=True)],
    )
    orch = Orchestrator(machine, deps, clock)

    # Advance to the point of parking.
    current = item
    for _ in range(4):  # DETECTED->DIAGNOSED->ACTION_CHOSEN->CONSTRAINT_CHECKED->SCHEDULED
        current = await orch.advance(current)
    assert current.state is State.SCHEDULED

    # Still parked: clock has not reached scheduled_for.
    parked = await orch.advance(current)
    assert parked.state is State.SCHEDULED

    # Fast-forward past the schedule; now it executes and resolves.
    clock.set(future + timedelta(minutes=1))
    final = await orch.run_to_completion(parked)
    assert final.state is State.RESOLVED


async def test_failed_execution_with_budget_loops_back_and_increments_retry(
    machine: StateMachine, repo: WorkItemRepo, clock: SimulatedClock
) -> None:
    item, _ = repo.create_if_absent(make_work_item(state=State.DETECTED, retry_count=0))
    # First attempt fails with no escalation (budget remains); second recovers.
    deps, _ = _deps(
        outcomes=[
            _pass_outcome(executed=True, recovered=False, escalate=None),
            _pass_outcome(executed=True, recovered=True),
        ]
    )
    orch = Orchestrator(machine, deps, clock)

    final = await orch.run_to_completion(item)
    assert final.state is State.RESOLVED
    assert final.retry_count == 1  # incremented once on EXECUTED->ACTION_CHOSEN


async def test_run_to_completion_raises_when_item_never_settles(
    machine: StateMachine, repo: WorkItemRepo, clock: SimulatedClock
) -> None:
    item, _ = repo.create_if_absent(make_work_item(state=State.DETECTED))
    # Every execution fails without escalating: an infinite retry loop, bounded by max_steps.
    deps, _ = _deps(
        outcomes=[_pass_outcome(executed=True, recovered=False, escalate=None) for _ in range(50)]
    )
    orch = Orchestrator(machine, deps, clock)

    with pytest.raises(RuntimeError, match="did not reach a terminal state"):
        await orch.run_to_completion(item, max_steps=12)


async def test_advancing_a_terminal_item_raises(
    machine: StateMachine, repo: WorkItemRepo, clock: SimulatedClock
) -> None:
    resolved, _ = repo.create_if_absent(make_work_item(state=State.RESOLVED))
    deps, _ = _deps()
    orch = Orchestrator(machine, deps, clock)
    with pytest.raises(TerminalStateError):
        await orch.advance(resolved)


def test_orchestrator_imports_no_external_service() -> None:
    """PRD section 8.2: the orchestrator never imports a gateway, channel or LLM."""
    source = Path(orchestrator_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = ("recoup.gateways", "recoup.channels", "recoup.diagnosis", "recoup.constraints")
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)

    offenders = [m for m in imported if any(m == f or m.startswith(f + ".") for f in forbidden)]
    assert offenders == [], f"orchestrator must not import external services, found: {offenders}"
