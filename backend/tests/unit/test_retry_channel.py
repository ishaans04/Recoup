"""Tests for :class:`recoup.channels.retry.PaymentRetryChannel` (PRD §11.4, §13.1).

The money-safety properties: the idempotency key is stable per attempt and distinct
between attempts, a replayed attempt does not produce a second charge, and a gateway
exception becomes a bounded non-recovery rather than propagating. The breaker is fed
the outcome of every attempt so the loop stays closed.
"""


from recoup.channels.retry import PaymentRetryChannel, idempotency_key_for
from recoup.clock import SimulatedClock
from recoup.domain.enums import ActionType, Channel
from recoup.domain.models import Action
from recoup.gateways.base import GatewayTxn
from recoup.gateways.circuit_breaker import BreakerStatus, CircuitBreaker
from recoup.gateways.mock import MockGateway
from tests.conftest import CREATED_AT, make_work_item

_TXN = "pay_QjK9x2LmN4TzAb"  # matches make_work_item's default txn_id


def _retry_action(attempt: int = 0) -> Action:
    return Action(
        type=ActionType.SCHEDULED_RETRY,
        channel=Channel.PAYMENT_RETRY,
        attempt=attempt,
        reason="retry",
    )


def _setup(
    *, succeeds_on_attempt: int | None
) -> tuple[PaymentRetryChannel, MockGateway, CircuitBreaker]:
    clock = SimulatedClock(start=CREATED_AT)
    gateway = MockGateway(clock=clock, seed=42)
    gateway.seed_transaction(
        GatewayTxn(txn_id=_TXN, amount_paise=249900, status="failed", method="card", issuer="HDFC"),
        failure_code="insufficient_funds",
        failure_message="insufficient balance",
        succeeds_on_attempt=succeeds_on_attempt,
    )
    breaker = CircuitBreaker(clock=clock, failure_threshold=3, cooldown_seconds=60)
    return PaymentRetryChannel(gateway, breaker), gateway, breaker


def test_idempotency_key_is_stable_per_attempt_and_distinct_between_attempts() -> None:
    assert idempotency_key_for(_TXN, 0) == idempotency_key_for(_TXN, 0)
    assert idempotency_key_for(_TXN, 0) != idempotency_key_for(_TXN, 1)


async def test_successful_retry_reports_recovery_and_records_a_breaker_success() -> None:
    channel, _gateway, breaker = _setup(succeeds_on_attempt=1)
    result = await channel.execute(make_work_item(), _retry_action(attempt=0))
    assert result.recovered is True
    assert breaker.status("card:hdfc") is BreakerStatus.CLOSED


async def test_failed_retry_reports_no_recovery_and_records_a_breaker_failure() -> None:
    channel, _gateway, breaker = _setup(succeeds_on_attempt=None)  # never recovers
    result = await channel.execute(make_work_item(), _retry_action(attempt=0))
    assert result.recovered is False
    # Threshold is 3; one failure keeps it closed but counting.
    assert breaker.status("card:hdfc") is BreakerStatus.CLOSED


async def test_replaying_the_same_attempt_does_not_double_charge() -> None:
    channel, gateway, _breaker = _setup(succeeds_on_attempt=1)
    item = make_work_item()
    await channel.execute(item, _retry_action(attempt=0))
    await channel.execute(item, _retry_action(attempt=0))  # same attempt -> same key
    # Exactly one real charge, despite two execute calls.
    assert gateway.calls == [("retry_payment", _TXN)]


async def test_distinct_attempts_produce_distinct_charges() -> None:
    channel, gateway, _breaker = _setup(succeeds_on_attempt=None)
    item = make_work_item()
    await channel.execute(item, _retry_action(attempt=0))
    await channel.execute(item, _retry_action(attempt=1))
    assert len(gateway.calls) == 2


async def test_a_gateway_exception_becomes_a_bounded_non_recovery() -> None:
    clock = SimulatedClock(start=CREATED_AT)

    class ExplodingGateway:
        async def get_transaction(self, txn_id: str):  # type: ignore[no-untyped-def]
            raise RuntimeError("down")

        async def fetch_failure_reason(self, txn_id: str):  # type: ignore[no-untyped-def]
            raise RuntimeError("down")

        async def retry_payment(self, txn_id: str, idempotency_key: str):  # type: ignore[no-untyped-def]
            raise RuntimeError("gateway exploded")

        async def send_payment_link(self, txn_id: str) -> str:
            raise RuntimeError("down")

    breaker = CircuitBreaker(clock=clock, failure_threshold=1)
    channel = PaymentRetryChannel(ExplodingGateway(), breaker)  # type: ignore[arg-type]

    result = await channel.execute(make_work_item(), _retry_action())
    assert result.delivered is False
    assert result.recovered is False
    assert "gateway" in result.detail.lower()
    # The failure was still recorded against the breaker.
    assert breaker.is_open("card:hdfc") is True


def test_can_handle_is_true_for_the_retry_channel() -> None:
    channel, _gateway, _breaker = _setup(succeeds_on_attempt=1)
    assert channel.can_handle(make_work_item()) is True
    assert channel.name is Channel.PAYMENT_RETRY
