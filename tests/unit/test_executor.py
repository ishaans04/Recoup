"""Tests for the executor and the gate pipeline (PRD §12).

The executor's contract is that it verifies a pass *first* and runs a channel only
after, and that a fraud-flagged or over-cap item never reaches a channel at all —
proven with a spy channel that records every call. The pipeline's contract is the
four outcomes it produces (refuse, escalate-by-policy, defer, execute) as the
`GateOutcome` the orchestrator routes on.
"""

from datetime import timedelta

import pytest

from recoup.channels.base import ChannelRegistry
from recoup.clock import SimulatedClock
from recoup.constraints.gate import ConstraintGate, GateBypassError, GatePass, action_fingerprint
from recoup.constraints.rules import default_rules
from recoup.domain.enums import ActionType, Channel
from recoup.domain.models import Action, ChannelResult, WorkItem
from recoup.execution.executor import ActionExecutor
from recoup.execution.pipeline import GatePipeline
from tests.conftest import CREATED_AT, make_work_item


class SpyChannel:
    """A recovery channel that records its calls and returns a scripted result."""

    def __init__(self, name: Channel, *, recovered: bool, handles: bool = True) -> None:
        self._name = name
        self._recovered = recovered
        self._handles = handles
        self.calls: list[str] = []

    @property
    def name(self) -> Channel:
        return self._name

    def can_handle(self, item: WorkItem) -> bool:
        return self._handles

    async def execute(self, item: WorkItem, action: Action) -> ChannelResult:
        self.calls.append(item.txn_id)
        return ChannelResult(
            delivered=True,
            recovered=self._recovered,
            detail="retry reached the gateway",
            provider_ref="pay_retry_ref_1",
        )


def _clock() -> SimulatedClock:
    return SimulatedClock(start=CREATED_AT)


def _retry_action(attempt: int = 0) -> Action:
    return Action(
        type=ActionType.SCHEDULED_RETRY,
        channel=Channel.PAYMENT_RETRY,
        attempt=attempt,
        reason="scheduled retry",
    )


def _gate(clock: SimulatedClock) -> ConstraintGate:
    return ConstraintGate(default_rules(max_retries=3, max_amount_paise=5_000_000), clock=clock)


# --- executor ---------------------------------------------------------------


async def test_executor_runs_the_channel_for_a_valid_pass() -> None:
    clock = _clock()
    gate = _gate(clock)
    registry = ChannelRegistry()
    spy = SpyChannel(Channel.PAYMENT_RETRY, recovered=True)
    registry.register(spy)
    executor = ActionExecutor(gate, registry)

    item = make_work_item(amount_paise=249900)
    action = _retry_action()
    verdict = gate.check(action, item)
    assert verdict.gate_pass is not None

    result = await executor.execute(verdict.gate_pass, item, action)
    assert result.recovered is True
    assert result.channel is Channel.PAYMENT_RETRY
    assert spy.calls == [item.txn_id]


async def test_executor_reports_no_channel_when_registry_is_empty() -> None:
    clock = _clock()
    gate = _gate(clock)
    executor = ActionExecutor(gate, ChannelRegistry())
    item = make_work_item(amount_paise=249900)
    action = _retry_action()
    verdict = gate.check(action, item)
    assert verdict.gate_pass is not None

    result = await executor.execute(verdict.gate_pass, item, action)
    assert result.recovered is False
    assert "no channel available" in result.detail


async def test_executor_rejects_a_forged_pass_before_touching_a_channel() -> None:
    clock = _clock()
    gate = _gate(clock)
    registry = ChannelRegistry()
    spy = SpyChannel(Channel.PAYMENT_RETRY, recovered=True)
    registry.register(spy)
    executor = ActionExecutor(gate, registry)

    item = make_work_item()
    action = _retry_action()
    forged = GatePass(item.txn_id, action_fingerprint(action), CREATED_AT, token="00" * 32)
    with pytest.raises(GateBypassError):
        await executor.execute(forged, item, action)
    assert spy.calls == []  # channel never reached


# --- pipeline: the four outcomes -------------------------------------------


def _pipeline(
    clock: SimulatedClock, spy: SpyChannel | None = None
) -> tuple[GatePipeline, SpyChannel]:
    gate = _gate(clock)
    registry = ChannelRegistry()
    channel = spy or SpyChannel(Channel.PAYMENT_RETRY, recovered=True)
    registry.register(channel)
    pipeline = GatePipeline(gate, ActionExecutor(gate, registry), clock)
    return pipeline, channel


async def test_pipeline_executes_a_clean_due_retry() -> None:
    clock = _clock()
    pipeline, spy = _pipeline(clock)
    item = make_work_item(amount_paise=249900)
    outcome = await pipeline.check_and_execute(item, _retry_action())
    assert outcome.executed is True
    assert outcome.recovered is True
    assert outcome.constraint_result == "PASS"
    assert spy.calls == [item.txn_id]


async def test_pipeline_refuses_over_cap_and_never_runs_a_channel() -> None:
    clock = _clock()
    pipeline, spy = _pipeline(clock)
    item = make_work_item(amount_paise=7_500_000)
    outcome = await pipeline.check_and_execute(item, _retry_action())
    assert outcome.executed is False
    assert outcome.constraint_result == "FAIL"
    assert "amount_cap: Rs 75,000 > Rs 50,000" in outcome.constraint_reason
    assert outcome.escalate_reason is not None
    assert spy.calls == []  # nothing executed


async def test_pipeline_never_runs_a_channel_for_a_fraud_item() -> None:
    clock = _clock()
    pipeline, spy = _pipeline(clock)
    item = make_work_item(fraud_flag=True)
    outcome = await pipeline.check_and_execute(item, _retry_action())
    assert outcome.constraint_result == "FAIL"
    assert "fraud_block" in outcome.constraint_reason
    assert spy.calls == []


async def test_pipeline_escalates_a_policy_escalate_action_without_executing() -> None:
    clock = _clock()
    pipeline, spy = _pipeline(clock)
    escalate = Action(
        type=ActionType.ESCALATE,
        channel=Channel.HUMAN_QUEUE,
        attempt=0,
        reason="unknown cause; escalating rather than guessing",
    )
    outcome = await pipeline.check_and_execute(make_work_item(), escalate)
    assert outcome.executed is False
    assert outcome.constraint_result == "PASS"  # the gate did not object; policy escalates
    assert "unknown cause" in outcome.escalate_reason
    assert spy.calls == []


async def test_pipeline_defers_a_future_scheduled_retry() -> None:
    clock = _clock()
    pipeline, spy = _pipeline(clock)
    future = CREATED_AT + timedelta(days=3)
    action = Action(
        type=ActionType.SCHEDULED_RETRY,
        channel=Channel.PAYMENT_RETRY,
        attempt=0,
        scheduled_for=future,
        reason="salary-cycle retry",
    )
    outcome = await pipeline.check_and_execute(make_work_item(amount_paise=249900), action)
    assert outcome.executed is False
    assert outcome.constraint_result == "PASS"
    assert outcome.escalate_reason is None  # parked, not escalated
    assert spy.calls == []

    # Once the clock reaches the schedule, the same action executes.
    clock.set(future + timedelta(minutes=1))
    outcome2 = await pipeline.check_and_execute(make_work_item(amount_paise=249900), action)
    assert outcome2.executed is True
    assert spy.calls  # now it ran
