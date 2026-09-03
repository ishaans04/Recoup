"""The payment-retry recovery channel (PRD §10.3, §11.4, §13.1).

The one recovery channel that moves money directly: it re-presents a failed payment
through the :class:`~recoup.gateways.base.PaymentGateway` and feeds the outcome to
the circuit breaker, closing the loop the breaker needs — attempts feed counters,
counters gate future attempts.

Two money-safety properties live here. The idempotency key is a pure function of the
transaction and the attempt number, so a retry re-issued after a crash reuses the
exact key of the attempt it is repeating and the gateway returns the recorded result
rather than charging twice. And a gateway that raises is caught, recorded as a
breaker failure, and returned as a non-recovery — PRD §13.1's "never silently drop a
work item" — rather than propagating and losing the item mid-flight.
"""

from __future__ import annotations

from recoup.domain.enums import ActionType, Channel
from recoup.domain.models import Action, ChannelResult, FailureContext, WorkItem
from recoup.gateways.base import PaymentGateway
from recoup.gateways.circuit_breaker import CircuitBreaker

__all__ = ["PaymentRetryChannel", "idempotency_key_for"]

_RETRY_ACTION_TYPES = frozenset(
    {ActionType.SCHEDULED_RETRY, ActionType.BACKOFF_RETRY, ActionType.IMMEDIATE_RETRY}
)


def idempotency_key_for(txn_id: str, attempt: int) -> str:
    """The stable idempotency key for the ``attempt``-th retry of ``txn_id``.

    Deterministic and attempt-scoped: the same attempt always yields the same key
    (so a crash-and-retry cannot double-charge), and different attempts yield
    different keys (so a genuine second attempt is not mistaken for a replay of the
    first).
    """
    return f"recoup:{txn_id}:{attempt}"


class PaymentRetryChannel:
    """Re-presents a payment through the gateway and reports whether it recovered."""

    def __init__(self, gateway: PaymentGateway, breaker: CircuitBreaker) -> None:
        self._gateway = gateway
        self._breaker = breaker

    @property
    def name(self) -> Channel:
        return Channel.PAYMENT_RETRY

    def can_handle(self, item: WorkItem) -> bool:
        """The retry channel can re-present any payment.

        The executor only ever resolves this channel for an action whose channel is
        ``PAYMENT_RETRY`` (a retry action), so there is nothing item-specific to
        refuse here — the routing already guaranteed the action is a retry.
        """
        return True

    async def execute(self, item: WorkItem, action: Action) -> ChannelResult:
        """Retry the payment, record the outcome against the breaker, and report it."""
        route = self._route_of(item)
        key = idempotency_key_for(item.txn_id, action.attempt)

        try:
            result = await self._gateway.retry_payment(item.txn_id, key)
        except Exception as exc:  # noqa: BLE001 - any gateway failure is a bounded outcome
            self._breaker.record_failure(route)
            return ChannelResult(
                delivered=False,
                recovered=False,
                detail=f"retry could not reach the gateway: {exc}",
                provider_ref=None,
            )

        if result.recovered:
            self._breaker.record_success(route)
        else:
            self._breaker.record_failure(route)

        return ChannelResult(
            delivered=True,
            recovered=result.recovered,
            detail=result.detail,
            provider_ref=result.provider_ref,
        )

    @staticmethod
    def _route_of(item: WorkItem) -> str:
        return FailureContext(
            failure_code=item.failure_code,
            failure_message=item.failure_message,
            method=item.method,
            issuer=item.issuer,
            failure_type=item.failure_type,
            amount_paise=item.amount_paise,
        ).route
