"""Tests for the constraint rules and the gate (PRD §12).

Each rule is checked on both sides. The gate is checked for the properties the
safety argument rests on: it evaluates every rule (so the audit log sees every
reason), mints a pass only when all pass, and the pass it mints is bound to one
transaction and one action and cannot be forged, replayed across transactions,
reused for a different action, or accepted once stale. The amount-cap breach string
is pinned exactly — it goes on stage (PRD §12.4, §16.5).
"""

from datetime import timedelta

import pytest

from recoup.clock import SimulatedClock
from recoup.constraints.gate import (
    ConstraintGate,
    GateBypassError,
    GatePass,
    action_fingerprint,
)
from recoup.constraints.rules import (
    AmountCapRule,
    ChannelAvailableRule,
    CircuitOpenRule,
    FraudBlockRule,
    RetryCapRule,
    TerminalStopRule,
    default_rules,
)
from recoup.domain.enums import ActionType, Channel, State
from recoup.domain.models import Action
from tests.conftest import CREATED_AT, make_work_item


def _retry_action(attempt: int = 0) -> Action:
    return Action(
        type=ActionType.SCHEDULED_RETRY,
        channel=Channel.PAYMENT_RETRY,
        attempt=attempt,
        reason="scheduled retry near salary cycle",
    )


def _nudge_action() -> Action:
    return Action(
        type=ActionType.CUSTOMER_NUDGE,
        channel=Channel.SMS,
        attempt=0,
        reason="expired instrument; nudge to re-authenticate",
    )


def _clock() -> SimulatedClock:
    return SimulatedClock(start=CREATED_AT)


# --- individual rules -------------------------------------------------------


def test_retry_cap_passes_within_limit_and_fails_beyond() -> None:
    rule = RetryCapRule(max_retries=3)
    assert rule.evaluate(_retry_action(), make_work_item(retry_count=3)).passed is True
    breach = rule.evaluate(_retry_action(), make_work_item(retry_count=4))
    assert breach.passed is False
    assert breach.rule_id == "retry_cap"


def test_retry_cap_does_not_apply_to_a_nudge() -> None:
    rule = RetryCapRule(max_retries=3)
    verdict = rule.evaluate(_nudge_action(), make_work_item(retry_count=9))
    assert verdict.passed is True  # trivial pass, but recorded


def test_amount_cap_breach_reason_renders_exactly() -> None:
    """The on-stage string of PRD §12.4 / §16.5."""
    rule = AmountCapRule(max_amount_paise=5_000_000)
    verdict = rule.evaluate(_retry_action(), make_work_item(amount_paise=7_500_000))
    assert verdict.passed is False
    assert verdict.reason == "amount_cap: Rs 75,000 > Rs 50,000"


def test_amount_cap_passes_at_the_limit() -> None:
    rule = AmountCapRule(max_amount_paise=5_000_000)
    assert rule.evaluate(_retry_action(), make_work_item(amount_paise=5_000_000)).passed is True


def test_fraud_block_fails_a_fraud_flagged_item() -> None:
    rule = FraudBlockRule()
    assert rule.evaluate(_retry_action(), make_work_item(fraud_flag=False)).passed is True
    assert rule.evaluate(_retry_action(), make_work_item(fraud_flag=True)).passed is False


def test_terminal_stop_fails_a_terminal_item() -> None:
    rule = TerminalStopRule()
    assert rule.evaluate(_retry_action(), make_work_item(state=State.ACTION_CHOSEN)).passed is True
    assert rule.evaluate(_retry_action(), make_work_item(state=State.RESOLVED)).passed is False
    assert rule.evaluate(_retry_action(), make_work_item(state=State.ESCALATED)).passed is False


def test_circuit_open_fails_when_route_is_open() -> None:
    class OpenBreaker:
        def is_open(self, route: str) -> bool:
            return True

    class ClosedBreaker:
        def is_open(self, route: str) -> bool:
            return False

    assert CircuitOpenRule(ClosedBreaker()).evaluate(_retry_action(), make_work_item()).passed
    assert not CircuitOpenRule(OpenBreaker()).evaluate(_retry_action(), make_work_item()).passed


def test_circuit_open_defaults_to_never_open() -> None:
    # No breaker configured -> NullBreaker -> every route available.
    assert CircuitOpenRule().evaluate(_retry_action(), make_work_item()).passed is True


def test_channel_available_fails_a_nudge_with_no_reachable_channel() -> None:
    reachable = ChannelAvailableRule(lambda item, channel: True)
    unreachable = ChannelAvailableRule(lambda item, channel: False)
    assert reachable.evaluate(_nudge_action(), make_work_item()).passed is True
    assert unreachable.evaluate(_nudge_action(), make_work_item()).passed is False
    # A retry is not a nudge, so the rule passes trivially regardless.
    assert unreachable.evaluate(_retry_action(), make_work_item()).passed is True


# --- the gate ---------------------------------------------------------------


def _gate(**overrides: object) -> ConstraintGate:
    rules = default_rules(max_retries=3, max_amount_paise=5_000_000)
    return ConstraintGate(rules, clock=_clock(), **overrides)  # type: ignore[arg-type]


def test_gate_passes_a_clean_action_and_mints_a_pass() -> None:
    verdict = _gate().check(_retry_action(), make_work_item(amount_paise=249900))
    assert verdict.result == "PASS"
    assert verdict.gate_pass is not None
    assert verdict.failed_rule_ids == ()


def test_gate_fail_carries_no_pass_and_names_the_rule() -> None:
    verdict = _gate().check(_retry_action(), make_work_item(amount_paise=7_500_000))
    assert verdict.result == "FAIL"
    assert verdict.gate_pass is None
    assert "amount_cap" in verdict.failed_rule_ids
    assert "Rs 75,000 > Rs 50,000" in verdict.reason


def test_gate_reports_all_failing_rules_not_just_the_first() -> None:
    item = make_work_item(amount_paise=7_500_000, fraud_flag=True)
    verdict = _gate().check(_retry_action(), item)
    assert set(verdict.failed_rule_ids) >= {"amount_cap", "fraud_block"}
    # Every rule was evaluated, not only the failing ones.
    assert len(verdict.verdicts) == 6


def test_gate_evaluates_every_rule_on_a_pass_too() -> None:
    verdict = _gate().check(_retry_action(), make_work_item(amount_paise=249900))
    assert len(verdict.verdicts) == 6
    assert all(v.passed for v in verdict.verdicts)


# --- pass integrity ---------------------------------------------------------


def test_valid_pass_verifies() -> None:
    gate = _gate()
    item = make_work_item()
    action = _retry_action()
    verdict = gate.check(action, item)
    assert verdict.gate_pass is not None
    gate.verify(verdict.gate_pass, action, item)  # does not raise


def test_forged_token_is_rejected() -> None:
    gate = _gate()
    item = make_work_item()
    action = _retry_action()
    forged = GatePass(
        txn_id=item.txn_id,
        action_fingerprint=action_fingerprint(action),
        checked_at=CREATED_AT,
        token="deadbeef" * 8,
    )
    with pytest.raises(GateBypassError, match="invalid"):
        gate.verify(forged, action, item)


def test_pass_for_another_transaction_is_rejected() -> None:
    gate = _gate()
    action = _retry_action()
    verdict = gate.check(action, make_work_item(txn_id="pay_A", event_id="evt_A"))
    assert verdict.gate_pass is not None
    other = make_work_item(txn_id="pay_B", event_id="evt_B")
    with pytest.raises(GateBypassError, match="minted for"):
        gate.verify(verdict.gate_pass, action, other)


def test_pass_for_a_different_action_is_rejected() -> None:
    gate = _gate()
    item = make_work_item()
    verdict = gate.check(_retry_action(), item)
    assert verdict.gate_pass is not None
    # A pass minted for a retry cannot authorise a nudge.
    with pytest.raises(GateBypassError, match="does not authorise"):
        gate.verify(verdict.gate_pass, _nudge_action(), item)


def test_stale_pass_is_rejected() -> None:
    clock = _clock()
    gate = ConstraintGate(
        default_rules(max_retries=3, max_amount_paise=5_000_000),
        clock=clock,
        max_pass_age_seconds=60,
    )
    item = make_work_item()
    action = _retry_action()
    verdict = gate.check(action, item)
    assert verdict.gate_pass is not None
    clock.advance(timedelta(seconds=61))
    with pytest.raises(GateBypassError, match="stale"):
        gate.verify(verdict.gate_pass, action, item)


def test_secret_is_not_exposed() -> None:
    gate = _gate()
    blob = f"{gate!r} {vars(gate)}"
    # The 32-byte secret must not appear in repr or the instance dict under any
    # guessable public name.
    assert "secret" not in vars(gate)
    assert all(
        "secret" not in key.lower() or key.startswith("_ConstraintGate__") for key in vars(gate)
    )
    assert "token_bytes" not in blob
