"""The real Razorpay adapter (PRD §9.3, §13.1).

Phase 7 built the :class:`~recoup.gateways.base.PaymentGateway` boundary and a shared
contract suite; this module is the proof that boundary was real. ``RazorpayGateway``
satisfies the identical protocol ``MockGateway`` does, so swapping PSPs is a new
class here and nothing in the core (PRD §9.3). Business logic never imports a
Razorpay SDK — nor does this file: it speaks to the documented REST API over
``httpx``, which keeps the dependency surface small and gives precise control over
timeouts and error mapping.

**How recovery is modelled — an honest design decision, not a workaround.** In test
mode a *failed* payment cannot literally be re-charged: Razorpay has no "retry this
failed payment id" endpoint. The product recovers the money the way a merchant
actually does — it re-presents the amount as a fresh **payment link** for the same
transaction, carrying the idempotency key so a duplicated call returns the *same*
link rather than billing the customer twice. ``retry_payment`` therefore creates (or
idempotently re-fetches) a recovery link and reports ``recovered`` from that link's
own status: a link Razorpay reports as ``paid`` (a mandate that captured, or a link
the customer already settled) is a real recovery; a freshly created, still-unpaid
link is a bounded non-recovery that the retry budget and the nudge channels take
from there. The amount stays in integer paise throughout — Razorpay denominates in
paise, so nothing is ever divided or converted.

Credentials are never logged and never placed in an exception message.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from recoup.domain.enums import Channel, FailureType
from recoup.domain.models import ExecutionResult, FailureContext
from recoup.gateways.base import GatewayTxn

__all__ = [
    "GatewayRejected",
    "GatewayUnavailable",
    "RazorpayError",
    "RazorpayGateway",
    "UnknownTransaction",
]

_LOG = logging.getLogger("recoup.gateways.razorpay")
_BASE_URL = "https://api.razorpay.com/v1"


class RazorpayError(Exception):
    """Base class for adapter-level Razorpay failures. Never carries a credential."""


class GatewayUnavailable(RazorpayError):
    """A timeout or 5xx — retryable within the bounded budget (PRD §13.1)."""


class GatewayRejected(RazorpayError):
    """A 4xx the request itself caused — not retryable; escalate (PRD §13.1)."""


class UnknownTransaction(RazorpayError, LookupError):
    """No payment exists for this id. Subclasses ``LookupError`` so the shared
    contract suite's typed-error assertion accepts it exactly as it does the mock's."""


class RazorpayGateway:
    """A :class:`~recoup.gateways.base.PaymentGateway` backed by the Razorpay REST API."""

    def __init__(
        self,
        key_id: str,
        key_secret: str,
        *,
        base_url: str = _BASE_URL,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._auth = (key_id, key_secret)
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # An injectable transport lets the shared contract suite exercise this exact
        # adapter against Razorpay-shaped responses with no live account; production
        # leaves it None and httpx uses the network.
        self._transport = transport
        # Idempotency: a key maps to the result already produced for it, so a retry
        # re-issued after a crash returns the same artifact instead of a second one.
        self._idempotency: dict[str, ExecutionResult] = {}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, auth=self._auth, transport=self._transport)

    async def get_transaction(self, txn_id: str) -> GatewayTxn:
        """Fetch a payment and map it to a :class:`GatewayTxn`."""
        payment = await self._get(f"/payments/{txn_id}", txn_id=txn_id)
        return _to_gateway_txn(payment)

    async def fetch_failure_reason(self, txn_id: str) -> FailureContext:
        """Fetch a payment and map its error fields into a :class:`FailureContext`."""
        payment = await self._get(f"/payments/{txn_id}", txn_id=txn_id)
        return _to_failure_context(payment)

    async def retry_payment(self, txn_id: str, idempotency_key: str) -> ExecutionResult:
        """Re-present ``txn_id`` as a recovery payment link; report recovery from its status.

        Idempotent on ``idempotency_key``: a replay returns the recorded result and
        creates no second link.
        """
        if idempotency_key in self._idempotency:
            return self._idempotency[idempotency_key]

        payment = await self._get(f"/payments/{txn_id}", txn_id=txn_id)
        link = await self._create_payment_link(payment, idempotency_key=idempotency_key)

        recovered = str(link.get("status")) == "paid"
        result = ExecutionResult(
            recovered=recovered,
            channel=Channel.PAYMENT_RETRY,
            detail=(
                "recovery link settled by the customer"
                if recovered
                else f"recovery link issued, awaiting payment: {link.get('short_url', '')}"
            ),
            provider_ref=str(link.get("id")) if link.get("id") else None,
        )
        self._idempotency[idempotency_key] = result
        return result

    async def send_payment_link(self, txn_id: str) -> str:
        """Create a payment link for ``txn_id`` and return its short URL."""
        payment = await self._get(f"/payments/{txn_id}", txn_id=txn_id)
        link = await self._create_payment_link(payment, idempotency_key=None)
        short_url = link.get("short_url")
        if not isinstance(short_url, str) or not short_url:
            raise GatewayRejected("payment link response carried no short_url")
        return short_url

    async def _create_payment_link(
        self, payment: dict[str, Any], *, idempotency_key: str | None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "amount": payment.get("amount"),
            "currency": payment.get("currency", "INR"),
            "accept_partial": False,
            "reference_id": idempotency_key or f"recoup_{payment.get('id')}",
            "description": "Recoup payment recovery",
        }
        return await self._post("/payment_links", body)

    async def _get(self, path: str, *, txn_id: str) -> dict[str, Any]:
        try:
            async with self._client() as client:
                response = await client.get(f"{self._base_url}{path}")
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise GatewayUnavailable(
                f"Razorpay request timed out or failed: {type(exc).__name__}"
            ) from None
        return _parse(response, txn_id=txn_id)

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._client() as client:
                response = await client.post(f"{self._base_url}{path}", json=body)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise GatewayUnavailable(
                f"Razorpay request timed out or failed: {type(exc).__name__}"
            ) from None
        return _parse(response, txn_id=None)


def _parse(response: httpx.Response, *, txn_id: str | None) -> dict[str, Any]:
    """Map an HTTP response to a JSON body or a typed error, never leaking a credential.

    A missing payment surfaces two ways from Razorpay — a ``404``, or (as observed
    live) a ``400`` whose error description is "The id provided does not exist" — and
    both become :class:`UnknownTransaction` so the caller treats an unknown id the
    same however the API phrases it. Only the response body feeds the message; the
    credentials never do.
    """
    status = response.status_code
    if status < 400:
        try:
            body: dict[str, Any] = response.json()
        except (ValueError, TypeError) as exc:
            raise GatewayRejected("Razorpay response was not valid JSON") from exc
        return body

    detail = _error_description(response)
    if txn_id is not None and (status == 404 or "does not exist" in detail.lower()):
        raise UnknownTransaction(f"no Razorpay payment for {txn_id!r}")
    if status >= 500:
        raise GatewayUnavailable(f"Razorpay returned {status}")
    raise GatewayRejected(f"Razorpay rejected the request with {status}")


def _error_description(response: httpx.Response) -> str:
    """Razorpay's ``error.description`` from the body, or ``""`` — never a credential."""
    try:
        body = response.json()
    except (ValueError, TypeError):
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("description") or "")
    return ""


def _to_gateway_txn(payment: dict[str, Any]) -> GatewayTxn:
    return GatewayTxn(
        txn_id=str(payment["id"]),
        amount_paise=int(payment["amount"]),
        status=str(payment.get("status", "failed")),
        method=_optional_str(payment.get("method")),
        issuer=_issuer_of(payment),
    )


def _to_failure_context(payment: dict[str, Any]) -> FailureContext:
    return FailureContext(
        failure_code=str(payment.get("error_code") or "unknown"),
        failure_message=str(payment.get("error_description") or "no description provided"),
        method=_optional_str(payment.get("method")),
        issuer=_issuer_of(payment),
        failure_type=FailureType.ONE_TIME,
        amount_paise=int(payment["amount"]),
    )


def _issuer_of(payment: dict[str, Any]) -> str | None:
    """Razorpay carries the issuer under card.issuer for cards, else bank/wallet/vpa."""
    card = payment.get("card")
    if isinstance(card, dict):
        issuer = _optional_str(card.get("issuer"))
        if issuer is not None:
            return issuer
    return _optional_str(payment.get("bank")) or _optional_str(payment.get("wallet"))


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
