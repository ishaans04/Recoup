"""The payment gateway interface.

PRD sections 8.4 and 9.3 make the adapter, not Razorpay, the architectural
decision. Business logic never imports a PSP SDK; it depends on
:class:`PaymentGateway` and is handed an implementation. Three things follow from
that, and all three are load-bearing:

- A second PSP is a new class, not a change to the orchestrator or the gate.
- The gateway can be mocked, so failures are producible on demand — which is how
  the circuit breaker is demonstrated rather than merely described.
- The money-safe core runs with no credentials at all.

Phase 0 declares this interface. Phase 7 implements the mock, phase 12 the real
Razorpay adapter. Nothing here is a stub: a protocol body of ``...`` is the
declaration itself.
"""

from typing import Protocol, runtime_checkable

from recoup.domain.models import ExecutionResult, FailureContext, PaiseInt, RecoupModel

__all__ = ["GatewayTxn", "PaymentGateway"]


class GatewayTxn(RecoupModel):
    """A transaction as the gateway describes it.

    The normalised view of whatever the PSP returns. Recoup reads this rather than
    a provider payload, so a Razorpay field rename cannot reach the state machine.
    """

    txn_id: str
    """The provider's identifier for the payment."""

    amount_paise: PaiseInt
    """The amount, in integer paise. Razorpay already denominates in paise, so this
    is a pass-through there; an adapter for a rupee-denominated provider converts
    once, here, and never again."""

    status: str
    """The provider's own status string, unmodified — ``failed``, ``captured``,
    ``authorized``. Deliberately not an enum: statuses differ per provider and
    coercing an unrecognised one into a known bucket would misreport what actually
    happened, which the audit log cannot afford."""

    method: str | None = None
    """The instrument used, when the provider reports one. Part of the breaker route."""

    issuer: str | None = None
    """The issuing bank or network, when known. Part of the breaker route."""


@runtime_checkable
class PaymentGateway(Protocol):
    """Everything Recoup needs from a payment service provider.

    Four methods, and no more. The narrowness is the point: this is the complete
    surface through which Recoup can touch a merchant's payments, so it can be read
    in full before trusting it.
    """

    async def get_transaction(self, txn_id: str) -> GatewayTxn:
        """Fetch the current state of a transaction.

        Used to confirm an outcome against the provider's own record rather than
        against Recoup's assumption of it.
        """
        ...

    async def fetch_failure_reason(self, txn_id: str) -> FailureContext:
        """Fetch what the provider says about why a transaction failed.

        The result is the input to the diagnosis engine. It carries no customer or
        merchant data, so the Tier-2 prompt built from it carries none either.
        """
        ...

    async def retry_payment(self, txn_id: str, idempotency_key: str) -> ExecutionResult:
        """Re-present a failed payment.

        This is the only method here that moves money, and it may be called only
        after the constraint gate has passed the action.

        ``idempotency_key`` is required, not optional. A retry request that is
        transmitted twice — a timeout, a redelivery, an operator repeating a step —
        must charge the customer once. Making the caller supply the key means the
        question "what makes this safe to repeat?" has to be answered at every call
        site rather than left to the provider's defaults.
        """
        ...

    async def send_payment_link(self, txn_id: str) -> str:
        """Create a payment link for this transaction and return its URL.

        The recovery path for a failure no retry can fix: an expired card or a
        lapsed mandate needs the customer to act, and the nudge channels need
        somewhere to send them.
        """
        ...
