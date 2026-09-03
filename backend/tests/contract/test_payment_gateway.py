"""The shared PaymentGateway conformance suite (PRD §8.4, §9.3).

Every behaviour any conforming gateway must have is asserted here, once, against
whatever implementations the ``gateway`` fixture is parameterized over. Today that
is only :class:`~recoup.gateways.mock.MockGateway`; in Phase 12,
``RazorpayGateway`` is added to the same fixture and this file runs **unmodified**.
If the real adapter passes the identical tests the mock passes, the adapter boundary
of PRD §9.3 — "swap in a second PSP without touching core logic" — is demonstrated,
not merely claimed.

**Adding an implementation (Phase 12):** add one entry to ``_GATEWAY_FACTORIES``
below — a name and a callable that builds a seeded instance ready for these tests.
Nothing else changes.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from recoup.clock import SimulatedClock
from recoup.gateways.base import GatewayTxn, PaymentGateway
from recoup.gateways.mock import MockGateway, UnknownTransaction
from tests.conftest import CREATED_AT

_KNOWN_TXN = "pay_ContractAB01"
_UNKNOWN_TXN = "pay_NeverSeen99"


def _mock_gateway() -> PaymentGateway:
    gateway = MockGateway(clock=SimulatedClock(start=CREATED_AT), seed=42)
    gateway.seed_transaction(
        GatewayTxn(
            txn_id=_KNOWN_TXN,
            amount_paise=249900,
            status="failed",
            method="card",
            issuer="HDFC",
        ),
        failure_code="insufficient_funds",
        failure_message="insufficient balance",
        succeeds_on_attempt=1,  # recovers on the first retry
    )
    return gateway


# name -> factory producing a gateway seeded with the _KNOWN_TXN above.
_GATEWAY_FACTORIES: dict[str, Callable[[], PaymentGateway]] = {
    "mock": _mock_gateway,
}


@pytest.fixture(params=list(_GATEWAY_FACTORIES), ids=list(_GATEWAY_FACTORIES))
def gateway(request: pytest.FixtureRequest) -> PaymentGateway:
    return _GATEWAY_FACTORIES[request.param]()


async def test_get_transaction_returns_the_transaction(gateway: PaymentGateway) -> None:
    txn = await gateway.get_transaction(_KNOWN_TXN)
    assert txn.txn_id == _KNOWN_TXN
    assert txn.amount_paise == 249900


async def test_fetch_failure_reason_has_a_stable_nonempty_route(gateway: PaymentGateway) -> None:
    ctx = await gateway.fetch_failure_reason(_KNOWN_TXN)
    assert ctx.route
    assert ctx.route == (await gateway.fetch_failure_reason(_KNOWN_TXN)).route


async def test_successful_retry_reports_recovered(gateway: PaymentGateway) -> None:
    result = await gateway.retry_payment(_KNOWN_TXN, "recoup:pay_ContractAB01:0")
    assert result.recovered is True


async def test_replaying_an_idempotency_key_returns_the_same_result(
    gateway: PaymentGateway,
) -> None:
    key = "recoup:pay_ContractAB01:0"
    first = await gateway.retry_payment(_KNOWN_TXN, key)
    second = await gateway.retry_payment(_KNOWN_TXN, key)
    assert first == second


async def test_send_payment_link_returns_a_nonempty_url(gateway: PaymentGateway) -> None:
    link = await gateway.send_payment_link(_KNOWN_TXN)
    assert isinstance(link, str) and link


async def test_unknown_transaction_raises_a_typed_error(gateway: PaymentGateway) -> None:
    with pytest.raises((UnknownTransaction, KeyError, LookupError)):
        await gateway.get_transaction(_UNKNOWN_TXN)
