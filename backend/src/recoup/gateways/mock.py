"""A scriptable in-memory payment gateway (PRD §8.4).

The adapter layer exists so business logic never imports a PSP SDK, and so the
gateway can be *mocked to force failures on demand* — PRD §8.4 is explicit that the
mock is "essential for demoing the circuit breaker without waiting for a real
outage." This implementation is that mock: it satisfies the same
:class:`~recoup.gateways.base.PaymentGateway` protocol the real Razorpay adapter
will (Phase 12), passes the same conformance suite
(``tests/contract/test_payment_gateway.py``), and adds three levers a real gateway
does not give you — per-transaction scripting, on-demand route degradation, and a
recorded call log — so a whole recovery run can be staged deterministically.

Everything is deterministic under the constructor ``seed``: the same script and the
same seed produce the same outcomes on every run, which is what lets Phase 8 assert
a batch is reproducible.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from random import Random

from recoup.clock import Clock
from recoup.domain.enums import Channel, FailureType
from recoup.domain.models import ExecutionResult, FailureContext, WorkItem
from recoup.gateways.base import GatewayTxn

__all__ = ["MockGateway", "UnknownTransaction"]


class UnknownTransaction(Exception):
    """Raised when a method is called for a ``txn_id`` that was never seeded.

    The conformance suite requires a typed error here, not a ``None`` or a
    silent default, so both the mock and the real adapter fail the same way on an
    identifier neither has seen.
    """


@dataclass
class _SeededTxn:
    txn: GatewayTxn
    failure_code: str
    failure_message: str
    succeeds_on_attempt: int | None
    failure_type: FailureType = FailureType.ONE_TIME
    attempts: int = 0


@dataclass
class _Degradation:
    failure_rate: float
    routes: dict[str, float] = field(default_factory=dict)


class MockGateway:
    """An in-memory :class:`~recoup.gateways.base.PaymentGateway` you can script."""

    def __init__(self, *, clock: Clock, seed: int = 42) -> None:
        self._clock = clock
        self._seed = seed
        self._txns: dict[str, _SeededTxn] = {}
        self._degraded: dict[str, float] = {}
        self._latency_seconds = 0.0
        self._idempotency: dict[str, ExecutionResult] = {}
        self._calls: list[tuple[str, str]] = []

    # --- scripting levers (test/demo only, not part of the protocol) --------

    def seed_transaction(
        self,
        txn: GatewayTxn,
        *,
        failure_code: str,
        failure_message: str,
        succeeds_on_attempt: int | None = None,
        failure_type: FailureType = FailureType.ONE_TIME,
    ) -> None:
        """Register a transaction and how it behaves under retry.

        ``succeeds_on_attempt`` is the 1-based attempt on which a retry finally
        recovers the money — ``2`` means "fails once, then succeeds"; ``None`` means
        it never recovers on its own. Route degradation overrides this: a degraded
        route fails every attempt regardless.
        """
        self._txns[txn.txn_id] = _SeededTxn(
            txn=txn,
            failure_code=failure_code,
            failure_message=failure_message,
            succeeds_on_attempt=succeeds_on_attempt,
            failure_type=failure_type,
        )

    def degrade_route(self, route: str, *, failure_rate: float = 1.0) -> None:
        """Make every attempt on ``route`` fail (``1.0``) or fail at ``failure_rate``.

        Deterministic: whether a partial-rate attempt fails is a pure function of
        the seed, the route, the transaction and the attempt number, so a degraded
        run reproduces exactly. This is the lever that trips the breaker on stage.
        """
        self._degraded[route] = failure_rate

    def restore_route(self, route: str) -> None:
        self._degraded.pop(route, None)

    def set_latency(self, seconds: float) -> None:
        """Add an artificial per-call delay, so a staged run *feels* like a network."""
        self._latency_seconds = max(0.0, seconds)

    @property
    def calls(self) -> list[tuple[str, str]]:
        """Every real gateway call as ``(method, txn_id)``, in order.

        An idempotent replay does **not** append here — the whole point of the
        idempotency key is that it is not a second charge — so a test can assert the
        real number of attempts against this list.
        """
        return list(self._calls)

    # --- the PaymentGateway protocol ----------------------------------------

    async def get_transaction(self, txn_id: str) -> GatewayTxn:
        await self._simulate_latency()
        return self._require(txn_id).txn

    async def fetch_failure_reason(self, txn_id: str) -> FailureContext:
        await self._simulate_latency()
        seeded = self._require(txn_id)
        return FailureContext(
            failure_code=seeded.failure_code,
            failure_message=seeded.failure_message,
            method=seeded.txn.method,
            issuer=seeded.txn.issuer,
            failure_type=seeded.failure_type,
            amount_paise=seeded.txn.amount_paise,
        )

    async def retry_payment(self, txn_id: str, idempotency_key: str) -> ExecutionResult:
        await self._simulate_latency()
        if idempotency_key in self._idempotency:
            # A replay of an attempt already made: same result, not a new charge.
            return self._idempotency[idempotency_key]

        seeded = self._require(txn_id)
        self._calls.append(("retry_payment", txn_id))
        seeded.attempts += 1

        recovered = self._decide_recovery(seeded)
        result = ExecutionResult(
            recovered=recovered,
            channel=Channel.PAYMENT_RETRY,
            detail=(
                "retry recovered the payment"
                if recovered
                else f"retry failed: {seeded.failure_code}"
            ),
            provider_ref=f"mock_retry_{txn_id}_{seeded.attempts}",
        )
        self._idempotency[idempotency_key] = result
        return result

    async def send_payment_link(self, txn_id: str) -> str:
        await self._simulate_latency()
        self._require(txn_id)
        return f"https://rzp.mock/i/{txn_id}"

    # --- internals ----------------------------------------------------------

    def _require(self, txn_id: str) -> _SeededTxn:
        seeded = self._txns.get(txn_id)
        if seeded is None:
            raise UnknownTransaction(f"no seeded transaction for {txn_id!r}")
        return seeded

    def _decide_recovery(self, seeded: _SeededTxn) -> bool:
        route = _route_of(seeded.txn)
        if route in self._degraded:
            rate = self._degraded[route]
            if rate >= 1.0:
                return False
            rng = Random(f"{self._seed}:{route}:{seeded.txn.txn_id}:{seeded.attempts}")
            return rng.random() >= rate  # recovers only when the draw beats the failure rate
        if seeded.succeeds_on_attempt is None:
            return False
        return seeded.attempts >= seeded.succeeds_on_attempt

    async def _simulate_latency(self) -> None:
        if self._latency_seconds > 0:
            await asyncio.sleep(self._latency_seconds)


def _route_of(txn: GatewayTxn) -> str:
    method = (txn.method or "").strip().lower() or "unknown"
    issuer = (txn.issuer or "").strip().lower() or "unknown"
    return f"{method}:{issuer}"


def route_of_item(item: WorkItem) -> str:
    """The route key for a work item, matching :attr:`FailureContext.route` exactly."""
    return FailureContext(
        failure_code=item.failure_code,
        failure_message=item.failure_message,
        method=item.method,
        issuer=item.issuer,
        failure_type=item.failure_type,
        amount_paise=item.amount_paise,
    ).route
