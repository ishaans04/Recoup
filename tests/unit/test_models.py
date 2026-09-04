"""Tests for the shared domain model.

The two things worth testing hardest here are the two things that cost money when
they go wrong: the paise invariant and the audit rationale. Everything else is a
round trip.
"""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from recoup.domain.enums import ActionType, Cause, Channel, FailureType, State
from recoup.domain.models import (
    Action,
    AuditEvent,
    ChannelResult,
    Customer,
    Diagnosis,
    ExecutionResult,
    FailureContext,
    WorkItem,
)

IST = timezone(timedelta(hours=5, minutes=30), "IST")
CREATED_AT = datetime(2026, 9, 3, 14, 32, 5, tzinfo=IST)


def make_work_item(**overrides: object) -> WorkItem:
    """A realistic work item; override only the field under test."""
    fields: dict[str, object] = {
        "txn_id": "pay_QjK9x2LmN4TzAb",
        "event_id": "evt_8fH2kQpR7sVdWx",
        "merchant_id": "acc_MerchantDemo01",
        "amount_paise": 249900,
        "failure_code": "BAD_REQUEST_ERROR",
        "failure_message": "Your card has insufficient balance to complete this payment.",
        "failure_type": FailureType.SUBSCRIPTION,
        "method": "card",
        "issuer": "HDFC",
        "customer": Customer(
            name="Ananya Rao", phone="+919876543210", email="ananya.rao@example.com"
        ),
        "created_at": CREATED_AT,
    }
    fields.update(overrides)
    return WorkItem(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Round trips
# --------------------------------------------------------------------------- #


def test_work_item_round_trips_through_json() -> None:
    """The dashboard and the audit store both see a serialised WorkItem."""
    original = make_work_item(
        state=State.EXECUTED,
        retry_count=2,
        diagnosis=Diagnosis(
            cause=Cause.INSUFFICIENT_FUNDS,
            confidence=0.96,
            rationale="Issuer message names an insufficient balance.",
            source="rules",
        ),
        action=Action(
            type=ActionType.SCHEDULED_RETRY,
            channel=Channel.PAYMENT_RETRY,
            scheduled_for=datetime(2026, 9, 30, 10, 0, tzinfo=IST),
            attempt=2,
            reason="Insufficient funds: retry near the salary cycle.",
        ),
    )

    restored = WorkItem.model_validate_json(original.model_dump_json())

    assert restored == original
    assert restored.amount_paise == 249900
    assert restored.diagnosis is not None
    assert restored.diagnosis.cause is Cause.INSUFFICIENT_FUNDS
    assert restored.action is not None
    assert restored.action.scheduled_for == datetime(2026, 9, 30, 10, 0, tzinfo=IST)


def test_work_item_round_trip_preserves_optional_nulls() -> None:
    """An undiagnosed item is the common case at DETECTED; nulls must survive."""
    original = make_work_item(
        method=None,
        issuer=None,
        customer=Customer(name="Rohit Mehta"),
    )

    restored = WorkItem.model_validate_json(original.model_dump_json())

    assert restored == original
    assert restored.method is None
    assert restored.issuer is None
    assert restored.diagnosis is None
    assert restored.action is None
    assert restored.state is State.DETECTED
    assert restored.retry_count == 0
    assert restored.fraud_flag is False
    assert restored.currency == "INR"


def test_audit_event_round_trips_through_json() -> None:
    original = AuditEvent(
        id=412,
        timestamp=datetime(2026, 9, 3, 14, 32, 6, tzinfo=IST),
        txn_id="pay_QjK9x2LmN4TzAb",
        from_state=State.ACTION_CHOSEN,
        to_state=State.CONSTRAINT_CHECKED,
        diagnosis_cause=Cause.INSUFFICIENT_FUNDS,
        diagnosis_confidence=0.96,
        action_chosen=ActionType.SCHEDULED_RETRY,
        constraint_result="PASS",
        constraint_reason="retry_count 1 <= 3; amount_paise 249900 <= 5000000",
        outcome=None,
        rationale="All four constraints evaluated; the proposal is within every cap.",
    )

    restored = AuditEvent.model_validate_json(original.model_dump_json())

    assert restored == original
    assert restored.constraint_result == "PASS"


def test_audit_event_first_row_has_no_from_state() -> None:
    """A work item's first transition has no prior state, and that is legal."""
    event = AuditEvent(
        timestamp=CREATED_AT,
        txn_id="pay_QjK9x2LmN4TzAb",
        to_state=State.DETECTED,
        rationale="Webhook payment.failed accepted; work item created.",
    )

    assert event.id is None
    assert event.from_state is None
    assert AuditEvent.model_validate_json(event.model_dump_json()) == event


# --------------------------------------------------------------------------- #
# Money
# --------------------------------------------------------------------------- #


def test_amount_paise_rejects_a_float() -> None:
    """Coercion would turn 2499.99 into 2499 and lose a rupee, silently."""
    with pytest.raises(ValidationError) as exc:
        make_work_item(amount_paise=249900.5)

    assert "amount_paise" in str(exc.value)


def test_amount_paise_rejects_a_whole_number_float() -> None:
    """Even a lossless float is rejected: money never arrives as a float."""
    with pytest.raises(ValidationError):
        make_work_item(amount_paise=249900.0)


def test_amount_paise_rejects_a_numeric_string() -> None:
    """Strict mode also refuses the string form, so parsing errors surface early."""
    with pytest.raises(ValidationError):
        make_work_item(amount_paise="249900")


def test_amount_paise_rejects_a_negative_amount() -> None:
    with pytest.raises(ValidationError) as exc:
        make_work_item(amount_paise=-1)

    assert "greater than or equal to 0" in str(exc.value)


def test_amount_paise_accepts_zero() -> None:
    """A zero-amount failure is meaningless but not malformed; the gate handles it."""
    assert make_work_item(amount_paise=0).amount_paise == 0


def test_amount_rupees_converts_exactly() -> None:
    """Decimal, not float: 1 paise must not become 0.009999999999999998 rupees."""
    assert make_work_item(amount_paise=249900).amount_rupees == Decimal("2499")
    assert make_work_item(amount_paise=7500000).amount_rupees == Decimal("75000")
    assert make_work_item(amount_paise=1).amount_rupees == Decimal("0.01")
    assert make_work_item(amount_paise=249999).amount_rupees == Decimal("2499.99")
    assert isinstance(make_work_item(amount_paise=1).amount_rupees, Decimal)


def test_retry_count_rejects_negative_and_float() -> None:
    """The retry cap is only meaningful if the counter cannot be gamed."""
    with pytest.raises(ValidationError):
        make_work_item(retry_count=-1)
    with pytest.raises(ValidationError):
        make_work_item(retry_count=1.0)


def test_assignment_is_revalidated() -> None:
    """The orchestrator mutates retry_count; validation must run again when it does."""
    item = make_work_item()
    item.retry_count = 3
    assert item.retry_count == 3

    with pytest.raises(ValidationError):
        item.retry_count = -1


# --------------------------------------------------------------------------- #
# Diagnosis
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rationale", ["", "   ", "\n\t "])
def test_diagnosis_rejects_an_empty_rationale(rationale: str) -> None:
    """PRD section 11.1: every diagnosis carries a rationale into the audit log."""
    with pytest.raises(ValidationError) as exc:
        Diagnosis(
            cause=Cause.UNKNOWN, confidence=0.4, rationale=rationale, source="fallback"
        )

    assert "empty" in str(exc.value)


def test_diagnosis_strips_surrounding_whitespace_from_the_rationale() -> None:
    diagnosis = Diagnosis(
        cause=Cause.SOFT_DECLINE,
        confidence=0.8,
        rationale="  Issuer returned a transient decline.  ",
        source="llm",
    )

    assert diagnosis.rationale == "Issuer returned a transient decline."


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 2.0, -1.0])
def test_diagnosis_rejects_out_of_range_confidence(confidence: float) -> None:
    with pytest.raises(ValidationError):
        Diagnosis(
            cause=Cause.UNKNOWN,
            confidence=confidence,
            rationale="Nothing in the failure text is decisive.",
            source="fallback",
        )


@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
def test_diagnosis_accepts_the_closed_unit_interval(confidence: float) -> None:
    diagnosis = Diagnosis(
        cause=Cause.UNKNOWN,
        confidence=confidence,
        rationale="Nothing in the failure text is decisive.",
        source="fallback",
    )

    assert diagnosis.confidence == confidence


def test_diagnosis_rejects_a_source_outside_the_three_tiers() -> None:
    """`source` distinguishes a deterministic match from a model's judgement."""
    with pytest.raises(ValidationError):
        Diagnosis(
            cause=Cause.UNKNOWN,
            confidence=0.5,
            rationale="Nothing in the failure text is decisive.",
            source="guess",  # type: ignore[arg-type]
        )


def test_audit_event_rejects_an_empty_rationale() -> None:
    with pytest.raises(ValidationError):
        AuditEvent(
            timestamp=CREATED_AT,
            txn_id="pay_QjK9x2LmN4TzAb",
            to_state=State.DETECTED,
            rationale="   ",
        )


# --------------------------------------------------------------------------- #
# Terminal states
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("state", [State.RESOLVED, State.ESCALATED])
def test_is_terminal_is_true_for_the_two_terminal_states(state: State) -> None:
    assert make_work_item(state=state).is_terminal is True


@pytest.mark.parametrize(
    "state",
    [
        State.DETECTED,
        State.DIAGNOSED,
        State.ACTION_CHOSEN,
        State.CONSTRAINT_CHECKED,
        State.SCHEDULED,
        State.EXECUTED,
    ],
)
def test_is_terminal_is_false_for_every_other_state(state: State) -> None:
    assert make_work_item(state=state).is_terminal is False


# --------------------------------------------------------------------------- #
# FailureContext.route
# --------------------------------------------------------------------------- #


def make_failure_context(**overrides: object) -> FailureContext:
    fields: dict[str, object] = {
        "failure_code": "GATEWAY_ERROR",
        "failure_message": "Payment processing failed at the issuing bank.",
        "method": "card",
        "issuer": "HDFC",
        "failure_type": FailureType.ONE_TIME,
        "amount_paise": 249900,
    }
    fields.update(overrides)
    return FailureContext(**fields)  # type: ignore[arg-type]


def test_route_joins_method_and_issuer() -> None:
    assert make_failure_context().route == "card:hdfc"


def test_route_substitutes_unknown_for_a_missing_issuer() -> None:
    assert make_failure_context(issuer=None).route == "card:unknown"


def test_route_substitutes_unknown_for_a_missing_method() -> None:
    assert make_failure_context(method=None).route == "unknown:hdfc"


def test_route_substitutes_unknown_for_both_missing_parts() -> None:
    assert make_failure_context(method=None, issuer=None).route == "unknown:unknown"


def test_route_treats_a_blank_string_as_missing() -> None:
    """PSP payloads carry "" as often as they omit the key entirely."""
    assert make_failure_context(method="", issuer="   ").route == "unknown:unknown"


def test_route_is_stable_across_casing_and_padding() -> None:
    """The breaker counts per route; two spellings must not become two routes."""
    assert make_failure_context(method="CARD", issuer=" hdfc ").route == "card:hdfc"
    assert make_failure_context(method="Card", issuer="Hdfc").route == "card:hdfc"


def test_failure_context_carries_no_customer_data() -> None:
    """It is the LLM prompt input; personal data must not be reachable from it."""
    assert set(FailureContext.model_fields) == {
        "failure_code",
        "failure_message",
        "method",
        "issuer",
        "failure_type",
        "amount_paise",
    }


# --------------------------------------------------------------------------- #
# Customer
# --------------------------------------------------------------------------- #


def test_has_contact_is_true_when_either_channel_is_reachable() -> None:
    assert Customer(name="A", phone="+919876543210").has_contact is True
    assert Customer(name="B", email="b@example.com").has_contact is True
    assert Customer(name="C", phone="+919876543210", email="c@example.com").has_contact is True


def test_has_contact_is_false_when_the_customer_is_unreachable() -> None:
    """No phone and no email means a nudge cannot succeed; only the queue remains."""
    assert Customer(name="D").has_contact is False
    assert Customer(name="E", phone="", email="").has_contact is False
    assert Customer(name="F", phone="   ").has_contact is False


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


def test_channel_result_separates_delivery_from_recovery() -> None:
    """A delivered nudge recovers nothing yet; the two facts are not the same fact."""
    nudge = ChannelResult(
        delivered=True,
        recovered=False,
        detail="Re-authorisation SMS delivered to +919876543210.",
        provider_ref="SM8fH2kQpR7sVdWx",
    )

    assert nudge.delivered is True
    assert nudge.recovered is False
    assert ChannelResult.model_validate_json(nudge.model_dump_json()) == nudge


def test_execution_result_records_the_channel_actually_used() -> None:
    """The executor names the channel; a channel does not know it was chosen."""
    result = ExecutionResult(
        recovered=True,
        channel=Channel.PAYMENT_RETRY,
        detail="Retry captured 249900 paise.",
        provider_ref="pay_QjK9x2LmN4TzAb/rt2",
    )

    assert result.channel is Channel.PAYMENT_RETRY
    assert ExecutionResult.model_validate_json(result.model_dump_json()) == result


def test_execution_and_channel_results_are_distinct_types() -> None:
    """They diverge in later phases; collapsing them now would have to be undone."""
    assert ExecutionResult is not ChannelResult
    assert set(ExecutionResult.model_fields) != set(ChannelResult.model_fields)
    assert "channel" in ExecutionResult.model_fields
    assert "delivered" in ChannelResult.model_fields


@pytest.mark.parametrize(
    "model",
    [ChannelResult, ExecutionResult],
)
def test_results_reject_an_empty_detail(model: type[ChannelResult | ExecutionResult]) -> None:
    """`detail` becomes the audit outcome; an empty one proves nothing."""
    payload: dict[str, object] = {"recovered": False, "detail": "  "}
    if model is ChannelResult:
        payload["delivered"] = False
    else:
        payload["channel"] = Channel.PAYMENT_RETRY

    with pytest.raises(ValidationError):
        model(**payload)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Timestamps and unknown fields
# --------------------------------------------------------------------------- #


def test_naive_datetimes_are_rejected() -> None:
    """Comparing a naive scheduled_for against an aware now() raises deep in the scheduler."""
    with pytest.raises(ValidationError) as exc:
        make_work_item(created_at=datetime(2026, 9, 3, 14, 32, 5))

    assert "timezone-aware" in str(exc.value)


def test_aware_datetimes_in_any_zone_are_accepted() -> None:
    """The clock produces IST, but a normalised webhook may arrive in UTC."""
    item = make_work_item(created_at=datetime(2026, 9, 3, 9, 2, 5, tzinfo=UTC))

    assert item.created_at.tzinfo is not None
    assert item.created_at == CREATED_AT


def test_action_rejects_a_naive_scheduled_for() -> None:
    with pytest.raises(ValidationError):
        Action(
            type=ActionType.SCHEDULED_RETRY,
            channel=Channel.PAYMENT_RETRY,
            scheduled_for=datetime(2026, 9, 30, 10, 0),
            reason="Salary-cycle retry.",
        )


def test_action_allows_a_null_scheduled_for() -> None:
    """`None` means execute now, which is the common case for an immediate retry."""
    action = Action(
        type=ActionType.IMMEDIATE_RETRY,
        channel=Channel.PAYMENT_RETRY,
        reason="Transient soft decline; one retry.",
    )

    assert action.scheduled_for is None
    assert action.attempt == 0


def test_unknown_fields_are_rejected_rather_than_dropped() -> None:
    """Normalising a third-party payload must not silently discard a mistyped key."""
    with pytest.raises(ValidationError) as exc:
        make_work_item(amount_paisa=249900)

    assert "amount_paisa" in str(exc.value)


def test_currency_is_pinned_to_inr() -> None:
    with pytest.raises(ValidationError):
        make_work_item(currency="USD")
