"""Behavioural tests for :func:`recoup.ingestion.normalize.normalize` (PRD section 8.1).

Fixtures live in ``src/recoup/batch/fixtures`` and are reused, unmodified, by the
batch demo runner and later phases (PRD section 8.1's "live and batch share the
same code path" claim) — these tests are the proof that every one of them actually
normalizes to a well-formed :class:`~recoup.domain.models.WorkItem`.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from recoup.clock import IST, SimulatedClock
from recoup.domain.enums import FailureType
from recoup.ingestion.normalize import MalformedPayload, UnsupportedEvent, normalize

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "src" / "recoup" / "batch" / "fixtures"

CLOCK = SimulatedClock(datetime(2026, 9, 3, 12, 0, 0, tzinfo=IST))


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _payment_failed_insufficient_funds() -> dict[str, Any]:
    return _load("payment_failed_insufficient_funds.json")


# --------------------------------------------------------------------------- #
# Every fixture normalizes to the expected shape
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    (
        "fixture_name",
        "txn_id",
        "event_id",
        "amount_paise",
        "failure_code",
        "failure_type",
        "method",
        "issuer",
    ),
    [
        (
            "payment_failed_insufficient_funds.json",
            "pay_InsuffFundsAB01",
            "evt_pf_insuff_0001",
            249900,
            "BAD_REQUEST_ERROR",
            FailureType.ONE_TIME,
            "card",
            "HDFC",
        ),
        (
            "payment_failed_gateway_error.json",
            "pay_GatewayErrTx02",
            "evt_pf_gateway_0002",
            75000,
            "GATEWAY_ERROR",
            FailureType.ONE_TIME,
            "upi",
            "ICICI",
        ),
        (
            "payment_failed_card_expired.json",
            "pay_CardExpiredTx03",
            "evt_pf_expired_0003",
            129900,
            "CARD_EXPIRED",
            FailureType.ONE_TIME,
            "card",
            "SBI",
        ),
        (
            "subscription_halted.json",
            "sub_HaltedMandate04",
            "evt_sub_halted_0004",
            499900,
            "MANDATE_HALTED",
            FailureType.SUBSCRIPTION,
            "card",
            "AXIS",
        ),
        (
            "invoice_expired.json",
            "inv_ExpiredInvoice05",
            "evt_inv_expired_0005",
            899900,
            "INVOICE_EXPIRED",
            FailureType.INVOICE,
            None,
            None,
        ),
        (
            "payment_failed_fraud_flagged.json",
            "pay_FraudFlaggedTx06",
            "evt_pf_fraud_0006",
            4999900,
            "PAYMENT_DECLINED",
            FailureType.ONE_TIME,
            "card",
            "HDFC",
        ),
        (
            "payment_failed_unknown_code.json",
            "pay_UnknownCodeTx07",
            "evt_pf_unknown_0007",
            199900,
            "XYZ_UNRECOGNIZED_9001",
            FailureType.ONE_TIME,
            "netbanking",
            "Kotak Mahindra Bank",
        ),
    ],
)
def test_fixture_normalizes_to_expected_work_item(
    fixture_name: str,
    txn_id: str,
    event_id: str,
    amount_paise: int,
    failure_code: str,
    failure_type: FailureType,
    method: str | None,
    issuer: str | None,
) -> None:
    item = normalize(_load(fixture_name), clock=CLOCK)

    assert item.txn_id == txn_id
    assert item.event_id == event_id
    assert item.amount_paise == amount_paise
    assert item.failure_code == failure_code
    assert item.failure_type == failure_type
    assert item.method == method
    assert item.issuer == issuer
    assert item.customer is not None


def test_amount_paise_is_copied_not_divided() -> None:
    """A Rs 750 payment arrives as 75000 and stays 75000 (Razorpay already sends paise)."""
    item = normalize(_load("payment_failed_gateway_error.json"), clock=CLOCK)

    assert item.amount_paise == 75000


def test_event_id_comes_from_the_envelope_not_the_entity_id() -> None:
    payload = _payment_failed_insufficient_funds()
    item = normalize(payload, clock=CLOCK)

    assert item.event_id == payload["id"]
    assert item.txn_id == payload["payload"]["payment"]["entity"]["id"]
    assert item.event_id != item.txn_id


def test_missing_customer_contact_still_normalizes_with_has_contact_false() -> None:
    item = normalize(_load("payment_failed_card_expired.json"), clock=CLOCK)

    assert item.customer.phone is None
    assert item.customer.email is None
    assert item.customer.has_contact is False


def test_fraud_flagged_fixture_sets_fraud_flag_true() -> None:
    item = normalize(_load("payment_failed_fraud_flagged.json"), clock=CLOCK)

    assert item.fraud_flag is True


def test_non_fraud_fixtures_are_not_flagged() -> None:
    item = normalize(_payment_failed_insufficient_funds(), clock=CLOCK)

    assert item.fraud_flag is False


def test_created_at_falls_back_to_clock_when_envelope_omits_it() -> None:
    payload = _payment_failed_insufficient_funds()
    del payload["created_at"]

    item = normalize(payload, clock=CLOCK)

    assert item.created_at == CLOCK.now()


# --------------------------------------------------------------------------- #
# Malformed payloads
# --------------------------------------------------------------------------- #


def test_missing_amount_raises_malformed_payload_naming_the_field() -> None:
    payload = _payment_failed_insufficient_funds()
    del payload["payload"]["payment"]["entity"]["amount"]

    with pytest.raises(MalformedPayload, match="amount"):
        normalize(payload, clock=CLOCK)


def test_wrong_type_amount_raises_malformed_payload() -> None:
    payload = _payment_failed_insufficient_funds()
    payload["payload"]["payment"]["entity"]["amount"] = "249900"

    with pytest.raises(MalformedPayload, match="amount"):
        normalize(payload, clock=CLOCK)


def test_missing_entity_id_raises_malformed_payload_naming_the_field() -> None:
    payload = _payment_failed_insufficient_funds()
    del payload["payload"]["payment"]["entity"]["id"]

    with pytest.raises(MalformedPayload, match="entity.id"):
        normalize(payload, clock=CLOCK)


def test_missing_envelope_id_raises_malformed_payload_naming_the_field() -> None:
    payload = _payment_failed_insufficient_funds()
    del payload["id"]

    with pytest.raises(MalformedPayload, match="id"):
        normalize(payload, clock=CLOCK)


def test_missing_account_id_raises_malformed_payload_naming_the_field() -> None:
    payload = _payment_failed_insufficient_funds()
    del payload["account_id"]

    with pytest.raises(MalformedPayload, match="account_id"):
        normalize(payload, clock=CLOCK)


def test_missing_error_code_raises_malformed_payload() -> None:
    payload = _payment_failed_insufficient_funds()
    del payload["payload"]["payment"]["entity"]["error_code"]

    with pytest.raises(MalformedPayload, match="error_code"):
        normalize(payload, clock=CLOCK)


def test_missing_payload_section_raises_malformed_payload() -> None:
    payload = _payment_failed_insufficient_funds()
    del payload["payload"]

    with pytest.raises(MalformedPayload, match="payload"):
        normalize(payload, clock=CLOCK)


def test_non_dict_payload_raises_malformed_payload() -> None:
    with pytest.raises(MalformedPayload):
        normalize([], clock=CLOCK)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Unsupported events
# --------------------------------------------------------------------------- #


def test_unknown_event_type_raises_unsupported_event() -> None:
    payload = _payment_failed_insufficient_funds()
    payload["event"] = "refund.created"

    with pytest.raises(UnsupportedEvent):
        normalize(payload, clock=CLOCK)


def test_successful_subscription_charged_raises_unsupported_event() -> None:
    """subscription.charged only becomes a work item when the charge failed."""
    payload = _load("subscription_halted.json")
    payload["event"] = "subscription.charged"
    payload["payload"]["payment"] = payload["payload"].pop("subscription")
    payload["payload"]["payment"]["entity"]["status"] = "captured"

    with pytest.raises(UnsupportedEvent):
        normalize(payload, clock=CLOCK)


def test_failed_subscription_charged_normalizes_to_subscription_failure_type() -> None:
    payload = _load("subscription_halted.json")
    payload["event"] = "subscription.charged"
    payload["id"] = "evt_sub_charged_failed_0008"
    payload["payload"]["payment"] = payload["payload"].pop("subscription")
    payload["payload"]["payment"]["entity"]["status"] = "failed"
    payload["payload"]["payment"]["entity"]["id"] = "pay_ChargeFailedTx08"

    item = normalize(payload, clock=CLOCK)

    assert item.failure_type == FailureType.SUBSCRIPTION
    assert item.txn_id == "pay_ChargeFailedTx08"
