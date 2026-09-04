"""Tests for the Razorpay adapter (PRD §9.3, §13.1).

Every HTTP interaction is mocked with ``respx``; no live credentials are needed. The
shared contract suite already proves the adapter satisfies the ``PaymentGateway``
protocol; these tests pin the parts that suite cannot see — the error mapping
(timeout/5xx vs 4xx vs unknown id), the paise-safety, and that a credential never
leaks into an exception.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from recoup.domain.enums import Channel
from recoup.gateways.razorpay import (
    GatewayRejected,
    GatewayUnavailable,
    RazorpayGateway,
    UnknownTransaction,
)

_BASE = "https://api.razorpay.com/v1"
_TXN = "pay_TestAbc123"
_SECRET = "secret_never_leak_me"


def _gateway() -> RazorpayGateway:
    return RazorpayGateway("rzp_test_abc", _SECRET)


def _payment(**overrides: object) -> dict:
    body = {
        "id": _TXN,
        "amount": 249900,
        "currency": "INR",
        "status": "failed",
        "method": "card",
        "card": {"issuer": "HDFC", "network": "Visa"},
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "insufficient balance to complete the payment",
    }
    body.update(overrides)
    return body


@respx.mock
async def test_get_transaction_maps_the_payment_in_paise() -> None:
    respx.get(f"{_BASE}/payments/{_TXN}").mock(return_value=httpx.Response(200, json=_payment()))
    txn = await _gateway().get_transaction(_TXN)
    assert txn.txn_id == _TXN
    assert txn.amount_paise == 249900  # paise pass through untouched
    assert txn.issuer == "HDFC"


@respx.mock
async def test_fetch_failure_reason_maps_error_and_route() -> None:
    respx.get(f"{_BASE}/payments/{_TXN}").mock(return_value=httpx.Response(200, json=_payment()))
    ctx = await _gateway().fetch_failure_reason(_TXN)
    assert ctx.failure_code == "BAD_REQUEST_ERROR"
    assert ctx.route == "card:hdfc"
    assert ctx.amount_paise == 249900


@respx.mock
async def test_retry_creates_a_paid_link_and_reports_recovered() -> None:
    respx.get(f"{_BASE}/payments/{_TXN}").mock(return_value=httpx.Response(200, json=_payment()))
    respx.post(f"{_BASE}/payment_links").mock(
        return_value=httpx.Response(
            200, json={"id": "plink_1", "short_url": "https://rzp.io/i/x", "status": "paid"}
        )
    )
    result = await _gateway().retry_payment(_TXN, "recoup:pay_TestAbc123:0")
    assert result.recovered is True
    assert result.channel is Channel.PAYMENT_RETRY


@respx.mock
async def test_retry_is_idempotent_and_creates_one_link_per_key() -> None:
    respx.get(f"{_BASE}/payments/{_TXN}").mock(return_value=httpx.Response(200, json=_payment()))
    link_route = respx.post(f"{_BASE}/payment_links").mock(
        return_value=httpx.Response(
            200, json={"id": "plink_1", "short_url": "https://rzp.io/i/x", "status": "created"}
        )
    )
    gateway = _gateway()
    first = await gateway.retry_payment(_TXN, "recoup:pay_TestAbc123:0")
    second = await gateway.retry_payment(_TXN, "recoup:pay_TestAbc123:0")  # replay
    assert first == second
    assert first.recovered is False  # an unpaid link is a bounded non-recovery
    assert link_route.call_count == 1  # the replay created no second link


@respx.mock
async def test_unknown_transaction_raises_a_lookup_error() -> None:
    respx.get(f"{_BASE}/payments/{_TXN}").mock(return_value=httpx.Response(404, json={"error": {}}))
    with pytest.raises(UnknownTransaction):
        await _gateway().get_transaction(_TXN)
    # It is a LookupError, exactly what the shared contract suite's typed-error check accepts.
    assert issubclass(UnknownTransaction, LookupError)


@respx.mock
async def test_400_id_does_not_exist_maps_to_unknown_transaction() -> None:
    # Razorpay signals an unknown payment id with a 400 (confirmed live), not a 404.
    respx.get(f"{_BASE}/payments/{_TXN}").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "code": "BAD_REQUEST_ERROR",
                    "description": "The id provided does not exist",
                }
            },
        )
    )
    with pytest.raises(UnknownTransaction):
        await _gateway().get_transaction(_TXN)


@respx.mock
async def test_5xx_maps_to_gateway_unavailable() -> None:
    respx.get(f"{_BASE}/payments/{_TXN}").mock(return_value=httpx.Response(502, text="bad gateway"))
    with pytest.raises(GatewayUnavailable):
        await _gateway().get_transaction(_TXN)


@respx.mock
async def test_4xx_maps_to_gateway_rejected() -> None:
    respx.get(f"{_BASE}/payments/{_TXN}").mock(return_value=httpx.Response(400, json={"error": {}}))
    with pytest.raises(GatewayRejected):
        await _gateway().get_transaction(_TXN)


@respx.mock
async def test_timeout_maps_to_gateway_unavailable_without_leaking_the_secret() -> None:
    respx.get(f"{_BASE}/payments/{_TXN}").mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(GatewayUnavailable) as excinfo:
        await _gateway().get_transaction(_TXN)
    assert _SECRET not in str(excinfo.value)


@respx.mock
async def test_send_payment_link_returns_the_short_url() -> None:
    respx.get(f"{_BASE}/payments/{_TXN}").mock(return_value=httpx.Response(200, json=_payment()))
    respx.post(f"{_BASE}/payment_links").mock(
        return_value=httpx.Response(
            200, json={"id": "plink_1", "short_url": "https://rzp.io/i/pay", "status": "created"}
        )
    )
    url = await _gateway().send_payment_link(_TXN)
    assert url == "https://rzp.io/i/pay"
