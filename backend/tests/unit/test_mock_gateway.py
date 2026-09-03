"""Tests for :class:`recoup.gateways.mock.MockGateway` (PRD §8.4).

The mock's job is to make a recovery run stageable and reproducible: route
degradation forces failures on demand (to trip the breaker without a real outage),
per-transaction scripting decides when a retry recovers, and the whole thing is
deterministic under the seed.
"""

import pytest

from recoup.clock import SimulatedClock
from recoup.gateways.base import GatewayTxn
from recoup.gateways.mock import MockGateway, UnknownTransaction
from tests.conftest import CREATED_AT


def _gateway(seed: int = 42) -> MockGateway:
    gw = MockGateway(clock=SimulatedClock(start=CREATED_AT), seed=seed)
    gw.seed_transaction(
        GatewayTxn(
            txn_id="pay_1", amount_paise=100000, status="failed", method="card", issuer="HDFC"
        ),
        failure_code="gateway_error",
        failure_message="upstream timeout",
        succeeds_on_attempt=2,
    )
    gw.seed_transaction(
        GatewayTxn(
            txn_id="pay_2", amount_paise=100000, status="failed", method="upi", issuer="SBI"
        ),
        failure_code="insufficient_funds",
        failure_message="low balance",
        succeeds_on_attempt=1,
    )
    return gw


async def test_transaction_recovers_on_the_scripted_attempt() -> None:
    gw = _gateway()
    first = await gw.retry_payment("pay_1", "recoup:pay_1:0")
    second = await gw.retry_payment("pay_1", "recoup:pay_1:1")
    assert first.recovered is False  # fails once
    assert second.recovered is True  # succeeds on attempt 2


async def test_degraded_route_fails_every_attempt() -> None:
    gw = _gateway()
    gw.degrade_route("card:hdfc")  # pay_1's route
    result = await gw.retry_payment("pay_1", "recoup:pay_1:0")
    assert result.recovered is False
    # A different route still behaves per its script.
    other = await gw.retry_payment("pay_2", "recoup:pay_2:0")
    assert other.recovered is True


async def test_restore_route_lifts_degradation() -> None:
    gw = _gateway()
    gw.degrade_route("upi:sbi")
    assert (await gw.retry_payment("pay_2", "recoup:pay_2:0")).recovered is False
    gw.restore_route("upi:sbi")
    # A fresh attempt (new key) now follows the script again.
    assert (await gw.retry_payment("pay_2", "recoup:pay_2:1")).recovered is True


async def test_unknown_transaction_raises() -> None:
    gw = _gateway()
    with pytest.raises(UnknownTransaction):
        await gw.get_transaction("pay_missing")


async def test_calls_excludes_idempotent_replays() -> None:
    gw = _gateway()
    await gw.retry_payment("pay_1", "recoup:pay_1:0")
    await gw.retry_payment("pay_1", "recoup:pay_1:0")  # replay
    assert gw.calls == [("retry_payment", "pay_1")]


async def test_same_seed_reproduces_partial_rate_outcomes() -> None:
    gw_a = _gateway(seed=7)
    gw_b = _gateway(seed=7)
    gw_a.degrade_route("card:hdfc", failure_rate=0.5)
    gw_b.degrade_route("card:hdfc", failure_rate=0.5)
    a = [(await gw_a.retry_payment("pay_1", f"recoup:pay_1:{i}")).recovered for i in range(6)]
    b = [(await gw_b.retry_payment("pay_1", f"recoup:pay_1:{i}")).recovered for i in range(6)]
    assert a == b  # deterministic under a fixed seed
