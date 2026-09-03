"""Tests for :mod:`recoup.policy.selector`.

This is PRD §10.3's cause-to-action table made executable: one test per row, plus
the two safety properties that hold regardless of the diagnosis — a fraud flag is
never acted on, and an unrecognised cause escalates rather than being guessed at.
The three-causes-three-actions property is the on-stage demo moment of PRD §16.3.
"""

from datetime import datetime

import pytest

from recoup.clock import IST, SimulatedClock
from recoup.domain.enums import ActionType, Cause, Channel
from recoup.domain.models import Customer, Diagnosis
from recoup.policy.selector import chain_for, select_action
from tests.conftest import make_work_item

_NOW = datetime(2026, 6, 10, 11, 0, tzinfo=IST)
_NO_CONTACT = Customer(name="Unknown Customer", phone=None, email=None)


def _clock() -> SimulatedClock:
    return SimulatedClock(start=_NOW)


def _diagnosis(cause: Cause, confidence: float = 0.95) -> Diagnosis:
    return Diagnosis(
        cause=cause, confidence=confidence, rationale=f"diagnosed {cause.value}", source="rules"
    )


def test_insufficient_funds_maps_to_scheduled_retry() -> None:
    action = select_action(make_work_item(), _diagnosis(Cause.INSUFFICIENT_FUNDS), clock=_clock())
    assert action.type is ActionType.SCHEDULED_RETRY
    assert action.channel is Channel.PAYMENT_RETRY
    assert action.scheduled_for is not None and action.scheduled_for > _NOW


def test_gateway_degradation_maps_to_backoff_retry() -> None:
    action = select_action(make_work_item(), _diagnosis(Cause.GATEWAY_DEGRADATION), clock=_clock())
    assert action.type is ActionType.BACKOFF_RETRY
    assert action.channel is Channel.PAYMENT_RETRY
    assert action.scheduled_for is not None


def test_soft_decline_first_time_maps_to_immediate_retry() -> None:
    action = select_action(
        make_work_item(retry_count=0), _diagnosis(Cause.SOFT_DECLINE), clock=_clock()
    )
    assert action.type is ActionType.IMMEDIATE_RETRY
    assert action.channel is Channel.PAYMENT_RETRY


def test_soft_decline_second_time_escalates() -> None:
    action = select_action(
        make_work_item(retry_count=1), _diagnosis(Cause.SOFT_DECLINE), clock=_clock()
    )
    assert action.type is ActionType.ESCALATE
    assert action.channel is Channel.HUMAN_QUEUE


def test_expired_instrument_with_contact_nudges_via_head_of_chain() -> None:
    # Default customer has phone+email, amount 249900 is below the high-value line,
    # so the chain is [SMS, EMAIL] and the nudge leads with SMS.
    action = select_action(make_work_item(), _diagnosis(Cause.EXPIRED_INSTRUMENT), clock=_clock())
    assert action.type is ActionType.CUSTOMER_NUDGE
    assert action.channel is Channel.SMS


def test_high_value_expired_instrument_nudges_via_voice() -> None:
    action = select_action(
        make_work_item(amount_paise=600_000), _diagnosis(Cause.EXPIRED_INSTRUMENT), clock=_clock()
    )
    assert action.type is ActionType.CUSTOMER_NUDGE
    assert action.channel is Channel.VOICE


def test_expired_instrument_without_contact_escalates_with_reason() -> None:
    action = select_action(
        make_work_item(customer=_NO_CONTACT),
        _diagnosis(Cause.EXPIRED_INSTRUMENT),
        clock=_clock(),
    )
    assert action.type is ActionType.ESCALATE
    assert action.channel is Channel.HUMAN_QUEUE
    assert "contact" in action.reason.lower()


def test_fraud_flagged_cause_yields_no_action() -> None:
    action = select_action(make_work_item(), _diagnosis(Cause.FRAUD_FLAGGED), clock=_clock())
    assert action.type is ActionType.NO_ACTION
    assert action.channel is Channel.HUMAN_QUEUE


def test_fraud_flag_on_item_overrides_a_benign_diagnosis() -> None:
    """A safety property: item.fraud_flag blocks even when the diagnosis says
    something actionable."""
    action = select_action(
        make_work_item(fraud_flag=True), _diagnosis(Cause.INSUFFICIENT_FUNDS), clock=_clock()
    )
    assert action.type is ActionType.NO_ACTION
    assert action.channel is Channel.HUMAN_QUEUE


def test_unknown_cause_escalates_never_guesses() -> None:
    action = select_action(make_work_item(), _diagnosis(Cause.UNKNOWN, 0.0), clock=_clock())
    assert action.type is ActionType.ESCALATE
    assert action.channel is Channel.HUMAN_QUEUE


def test_three_causes_produce_three_different_actions() -> None:
    """PRD §16.3: not a retry loop, a root-cause router."""
    clock = _clock()
    a = select_action(make_work_item(), _diagnosis(Cause.INSUFFICIENT_FUNDS), clock=clock)
    b = select_action(make_work_item(), _diagnosis(Cause.GATEWAY_DEGRADATION), clock=clock)
    c = select_action(
        make_work_item(amount_paise=600_000), _diagnosis(Cause.EXPIRED_INSTRUMENT), clock=clock
    )
    assert len({a.type, b.type, c.type}) == 3


def test_every_action_carries_a_specific_nonempty_reason() -> None:
    for cause in Cause:
        action = select_action(make_work_item(), _diagnosis(cause), clock=_clock())
        assert action.reason.strip()
        assert cause.value in action.reason or action.type is ActionType.NO_ACTION


def test_attempt_reflects_retry_count() -> None:
    action = select_action(
        make_work_item(retry_count=2), _diagnosis(Cause.GATEWAY_DEGRADATION), clock=_clock()
    )
    assert action.attempt == 2


@pytest.mark.parametrize(
    ("cause", "expected_channel"),
    [
        (Cause.INSUFFICIENT_FUNDS, Channel.PAYMENT_RETRY),
        (Cause.FRAUD_FLAGGED, Channel.HUMAN_QUEUE),
        (Cause.UNKNOWN, Channel.HUMAN_QUEUE),
    ],
)
def test_chain_for_returns_single_channel_for_non_nudge_causes(
    cause: Cause, expected_channel: Channel
) -> None:
    assert chain_for(make_work_item(), _diagnosis(cause)) == [expected_channel]


def test_chain_for_expired_instrument_returns_full_fallback_chain() -> None:
    chain = chain_for(make_work_item(amount_paise=600_000), _diagnosis(Cause.EXPIRED_INSTRUMENT))
    assert chain == [Channel.VOICE, Channel.SMS, Channel.EMAIL]
