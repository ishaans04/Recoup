"""The money-safe core, composed for real (PRD §12).

Phases 2, 4, 5 and 6 were each unit-tested against fakes of their neighbours. This
wires the *real* diagnosis engine, action selector, constraint gate, executor and
state machine together behind the orchestrator and proves the property the whole
system exists to guarantee: a dangerous action — over the amount cap, or
fraud-flagged — is driven to ESCALATED through the actual finite-state machine,
its refusal recorded in the immutable audit log, and no recovery channel is ever
run. A spy channel registered under payment retry records any execution, so
"nothing ran" is proven, not assumed.
"""

import pytest
from sqlalchemy import Engine, text

from recoup.channels.base import ChannelRegistry
from recoup.clock import SimulatedClock
from recoup.constraints.gate import ConstraintGate
from recoup.constraints.rules import default_rules
from recoup.diagnosis.engine import DiagnosisEngine
from recoup.diagnosis.rules import RulesTable
from recoup.domain.enums import Channel, State
from recoup.domain.models import Action, ChannelResult, Diagnosis, WorkItem
from recoup.execution.executor import ActionExecutor
from recoup.execution.pipeline import GatePipeline
from recoup.fsm.machine import StateMachine
from recoup.fsm.orchestrator import Orchestrator, OrchestratorDeps
from recoup.policy.selector import select_action
from recoup.storage.audit import AuditLog
from recoup.storage.work_items import WorkItemRepo
from tests.conftest import CREATED_AT, make_work_item


class SpyChannel:
    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def name(self) -> Channel:
        return Channel.PAYMENT_RETRY

    def can_handle(self, item: WorkItem) -> bool:
        return True

    async def execute(self, item: WorkItem, action: Action) -> ChannelResult:
        self.calls.append(item.txn_id)
        return ChannelResult(delivered=True, recovered=True, detail="ran", provider_ref="x")


@pytest.fixture
def wired(engine: Engine) -> tuple[Orchestrator, SpyChannel, AuditLog]:
    clock = SimulatedClock(start=CREATED_AT)
    repo = WorkItemRepo(engine)
    audit = AuditLog(engine)
    machine = StateMachine(engine, audit, repo, clock)

    diagnosis_engine = DiagnosisEngine(RulesTable(), llm=None)
    gate = ConstraintGate(default_rules(max_retries=3, max_amount_paise=5_000_000), clock=clock)
    registry = ChannelRegistry()
    spy = SpyChannel()
    registry.register(spy)
    pipeline = GatePipeline(gate, ActionExecutor(gate, registry), clock)

    async def diagnose(item: WorkItem) -> Diagnosis:
        return await diagnosis_engine.diagnose(item)

    def select(item: WorkItem, diagnosis: Diagnosis) -> Action:
        return select_action(item, diagnosis, clock=clock)

    deps = OrchestratorDeps(
        diagnose=diagnose,
        select_action=select,
        check_and_execute=pipeline.check_and_execute,
    )
    return Orchestrator(machine, deps, clock), spy, audit


def _rationales(engine: Engine, txn_id: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT rationale FROM audit_events WHERE txn_id = :t ORDER BY id"),
            {"t": txn_id},
        )
        return [row[0] for row in rows]


async def test_over_cap_item_escalates_through_the_real_stack_without_executing(
    wired: tuple[Orchestrator, SpyChannel, AuditLog], engine: Engine
) -> None:
    orch, spy, _ = wired
    item, _ = WorkItemRepo(engine).create_if_absent(
        make_work_item(
            amount_paise=7_500_000,
            failure_code="insufficient_funds",
            failure_message="Insufficient balance.",
            state=State.DETECTED,
        )
    )
    final = await orch.run_to_completion(item)

    assert final.state is State.ESCALATED
    assert spy.calls == []  # the gate refused before any channel could run
    joined = " ".join(_rationales(engine, item.txn_id))
    assert "amount_cap: Rs 75,000 > Rs 50,000" in joined


async def test_fraud_item_escalates_through_the_real_stack_without_executing(
    wired: tuple[Orchestrator, SpyChannel, AuditLog], engine: Engine
) -> None:
    orch, spy, _ = wired
    item, _ = WorkItemRepo(engine).create_if_absent(
        make_work_item(fraud_flag=True, state=State.DETECTED)
    )
    final = await orch.run_to_completion(item)

    assert final.state is State.ESCALATED
    assert spy.calls == []
    joined = " ".join(_rationales(engine, item.txn_id))
    assert "fraud_block" in joined
