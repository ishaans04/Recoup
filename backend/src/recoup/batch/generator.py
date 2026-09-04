"""The deterministic synthetic transaction generator (PRD §5.1, §16).

A demo is only honest if the batch it runs on is honest, and it is only
reproducible if the batch is reproducible. This module produces both properties at
once: a fixed distribution of failed-payment scenarios across all six causes,
seeded so that the same ``seed`` yields byte-for-byte the same batch, and shaped so
that the recovery rate is *genuinely* below 100% because some transactions are
genuinely unrecoverable — over the amount cap, fraud-flagged, contactless, or
retry-exhausted (PRD §13.4's honesty requirement is a property of the *input*, not
of the report).

Two outputs are derived from one spec list, and that single source is what keeps
them consistent:

- :func:`generate_batch` returns raw **Razorpay-shaped payloads**, not
  :class:`~recoup.domain.models.WorkItem` objects, so the batch enters the system
  through the exact same :meth:`~recoup.ingestion.idempotency.Ingestor.ingest_payload`
  path a live webhook would (PRD §8.1: live and batch runs share code paths).
- :func:`build_gateway` returns a :class:`~recoup.gateways.mock.MockGateway` seeded
  so each transaction recovers, or does not, on the scripted attempt — and the
  deliberately degraded route is degraded there. A payload cannot carry "this
  recovers on the second retry"; that lives with the gateway, so the two are built
  from the same :data:`_SPECS`-producing function rather than guessed at separately.

:data:`SEEDED_SCENARIOS` maps each named scenario to the ``txn_id`` it produced, so
the demo endpoint (Phase 9) and the tests can address "the Rs 75,000 rejection" or
"the breaker cluster" by name instead of by index.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any

from recoup.clock import Clock
from recoup.domain.enums import FailureType
from recoup.gateways.base import GatewayTxn
from recoup.gateways.mock import MockGateway

__all__ = [
    "DEGRADED_ROUTE",
    "OVER_CAP_AMOUNT_PAISE",
    "SEEDED_SCENARIOS",
    "build_gateway",
    "generate_batch",
]

OVER_CAP_AMOUNT_PAISE = 7_500_000
"""Rs 75,000 — the transaction that must exceed the Rs 50,000 amount cap and be
rejected on stage (PRD §16.5). Named so a test cannot silently drift it under the
cap."""

DEGRADED_ROUTE = "upi:sbi"
"""The single ``method:issuer`` route the generator degrades so a cluster of
same-route failures trips the circuit breaker (PRD §16.3). No other scenario uses
this route, so nothing else contributes failures to it."""

_MERCHANT_ID = "acc_MerchantDemo01"

# Contact details reused across scenarios that have a reachable customer.
_PHONE = "+919876543210"
_EMAIL = "asha.menon@example.com"

# Issuers/methods for routes that must NOT collide with DEGRADED_ROUTE, so a
# non-cluster failure never contributes to the breaker's cluster count. "SBI" is
# deliberately absent here; only the cluster uses it.
_METHODS = ("card", "upi", "netbanking")
_ISSUERS = ("HDFC", "ICICI", "AXIS", "KOTAK", "YESBANK")

# event -> the FailureType a work item derived from it carries. Mirrors
# recoup.ingestion.normalize so the seeded GatewayTxn and the normalized WorkItem
# agree on the failure type.
_EVENT_FAILURE_TYPE: dict[str, FailureType] = {
    "payment.failed": FailureType.ONE_TIME,
    "subscription.halted": FailureType.SUBSCRIPTION,
    "invoice.expired": FailureType.INVOICE,
}
_EVENT_ENTITY_KEY: dict[str, str] = {
    "payment.failed": "payment",
    "subscription.halted": "subscription",
    "invoice.expired": "invoice",
}


@dataclass(frozen=True)
class _Spec:
    """One synthetic transaction, enough to build both a payload and a gateway seed."""

    scenario: str
    """Named scenario for :data:`SEEDED_SCENARIOS`, or ``""`` for bulk filler."""

    txn_id: str
    event_id: str
    event: str
    amount_paise: int
    error_code: str
    error_message: str
    method: str | None
    issuer: str | None
    fraud: bool
    phone: str | None
    email: str | None
    succeeds_on_attempt: int | None
    """The 1-based retry attempt on which the gateway recovers this payment, or
    ``None`` for a payment that never recovers on its own."""

    degraded: bool
    """Whether this transaction sits on :data:`DEGRADED_ROUTE` (the breaker cluster)."""

    @property
    def failure_type(self) -> FailureType:
        return _EVENT_FAILURE_TYPE[self.event]


def _bulk_route(rng: Random) -> tuple[str, str]:
    """A random non-degraded ``(method, issuer)`` for a bulk transaction."""
    return rng.choice(_METHODS), rng.choice(_ISSUERS)


def _specs(n: int, seed: int) -> list[_Spec]:
    """The full ordered spec list: mandatory scenarios first, then bulk filler.

    Deterministic under ``seed``. The mandatory, individually-named scenarios lead
    the list so that a smaller ``n`` still keeps them; the bulk recoverers and
    failers follow, tuned so the paise-weighted recovery rate lands in a plausible,
    non-perfect band with a populated exception list.
    """
    rng = Random(seed)
    specs: list[_Spec] = []
    counter = 0

    def _next_ids(tag: str) -> tuple[str, str]:
        nonlocal counter
        counter += 1
        return f"pay_{tag}{counter:03d}", f"evt_{tag}{counter:03d}"

    # --- Mandatory named scenarios (PRD §16 puts each on screen) --------------

    txn, evt = _next_ids("OVERCAP")
    specs.append(
        _Spec(
            scenario="over_cap",
            txn_id=txn,
            event_id=evt,
            event="payment.failed",
            amount_paise=OVER_CAP_AMOUNT_PAISE,
            error_code="BAD_REQUEST_ERROR",
            error_message="Your card has insufficient balance to complete this payment.",
            method="card",
            issuer="HDFC",
            fraud=False,
            phone=_PHONE,
            email=_EMAIL,
            succeeds_on_attempt=1,  # would recover if it ever ran; the cap stops it first
            degraded=False,
        )
    )

    method, issuer = DEGRADED_ROUTE.split(":")
    for _ in range(6):
        txn, evt = _next_ids("CLUSTER")
        specs.append(
            _Spec(
                scenario="breaker_cluster",  # every cluster txn shares this label
                txn_id=txn,
                event_id=evt,
                event="payment.failed",
                amount_paise=rng.randint(3_000, 5_000) * 100,
                error_code="gateway_error",
                error_message="Gateway timed out; the acquiring bank did not respond.",
                method=method,
                issuer=issuer.upper(),
                fraud=False,
                phone=_PHONE,
                email=_EMAIL,
                succeeds_on_attempt=None,  # the degraded route fails regardless
                degraded=True,
            )
        )

    txn, evt = _next_ids("VOICE")
    specs.append(
        _Spec(
            scenario="voice_candidate",
            txn_id=txn,
            event_id=evt,
            event="subscription.halted",
            amount_paise=4_500_000,  # high value, but under the Rs 50,000 cap
            error_code="subscription_halted",
            error_message="The mandate has been revoked and the subscription is halted.",
            method="card",
            issuer="ICICI",
            fraud=False,
            phone=_PHONE,
            email=None,  # phone-only: high-value + phone routes voice first
            succeeds_on_attempt=None,
            degraded=False,
        )
    )

    txn, evt = _next_ids("FRAUD")
    specs.append(
        _Spec(
            scenario="fraud_flagged",
            txn_id=txn,
            event_id=evt,
            event="payment.failed",
            amount_paise=rng.randint(4_000, 9_000) * 100,
            error_code="payment_frozen",
            error_message="Payment blocked: flagged by the risk engine.",
            method="card",
            issuer="AXIS",
            fraud=True,
            phone=_PHONE,
            email=_EMAIL,
            succeeds_on_attempt=None,
            degraded=False,
        )
    )

    txn, evt = _next_ids("NOCONTACT")
    specs.append(
        _Spec(
            scenario="no_contact",
            txn_id=txn,
            event_id=evt,
            event="payment.failed",
            amount_paise=rng.randint(3_000, 7_000) * 100,
            error_code="card_expired",
            error_message="The card has expired and can no longer be charged.",
            method="card",
            issuer="KOTAK",
            fraud=False,
            phone=None,  # unreachable: no retry can fix an expired card, no channel to nudge
            email=None,
            succeeds_on_attempt=None,
            degraded=False,
        )
    )

    txn, evt = _next_ids("UNKNOWN")
    specs.append(
        _Spec(
            scenario="unknown_code",
            txn_id=txn,
            event_id=evt,
            event="payment.failed",
            amount_paise=rng.randint(3_000, 7_000) * 100,
            error_code="u_nonstandard_9000",
            error_message="The acquirer returned a nonstandard condition.",
            method="upi",
            issuer="YESBANK",
            fraud=False,
            phone=_PHONE,
            email=_EMAIL,
            succeeds_on_attempt=None,
            degraded=False,
        )
    )

    # --- Bulk filler, tuned for a plausible non-perfect recovery rate --------
    #
    # Recoverers carry mid-to-high amounts and failers mostly small ones, which is
    # realistic (a small unfunded top-up is likelier to churn than a large invoice)
    # and keeps the paise-weighted rate off both 0% and 100% without ever filtering
    # the denominator — the report's arithmetic is untouched (PRD §13.4).

    def _recovering(tag: str, code: str, message: str) -> _Spec:
        method, issuer = _bulk_route(rng)
        txn, evt = _next_ids(tag)
        return _Spec(
            scenario="",
            txn_id=txn,
            event_id=evt,
            event="payment.failed",
            amount_paise=rng.randint(6_000, 12_000) * 100,
            error_code=code,
            error_message=message,
            method=method,
            issuer=issuer,
            fraud=False,
            phone=_PHONE,
            email=_EMAIL,
            succeeds_on_attempt=1,
            degraded=False,
        )

    def _failing(tag: str, code: str, message: str, *, contact: bool = True) -> _Spec:
        method, issuer = _bulk_route(rng)
        txn, evt = _next_ids(tag)
        return _Spec(
            scenario="",
            txn_id=txn,
            event_id=evt,
            event="payment.failed",
            amount_paise=rng.randint(2_000, 5_000) * 100,
            error_code=code,
            error_message=message,
            method=method,
            issuer=issuer,
            fraud=False,
            phone=_PHONE if contact else None,
            email=_EMAIL if contact else None,
            succeeds_on_attempt=None,
            degraded=False,
        )

    _IF_CODE = "BAD_REQUEST_ERROR"
    _IF_MSG = "Your account has insufficient balance to complete this payment."
    _SOFT_CODE = "payment_failed"
    _SOFT_MSG = "The payment was declined by the issuer."
    _GW_CODE = "gateway_error"
    _GW_MSG = "The gateway was briefly unavailable; please try again."
    _EXP_CODE = "card_expired"
    _EXP_MSG = "The saved card has expired; the customer must update it."

    for _ in range(13):
        specs.append(_recovering("IF", _IF_CODE, _IF_MSG))  # salary-cycle retry recovers
    for _ in range(3):
        specs.append(_failing("IFX", _IF_CODE, _IF_MSG))  # retries exhausted -> escalate
    for _ in range(8):
        specs.append(_recovering("GW", _GW_CODE, _GW_MSG))  # backoff retry recovers
    for _ in range(6):
        specs.append(_recovering("SOFT", _SOFT_CODE, _SOFT_MSG))  # one immediate retry recovers
    for _ in range(5):
        specs.append(_failing("SOFTX", _SOFT_CODE, _SOFT_MSG))  # second decline -> escalate
    for _ in range(4):
        # Expired instrument, contactable: nudged, but no nudge channel exists yet
        # (Phase 13/14), so it settles as an honest unrecovered exception.
        specs.append(_failing("EXP", _EXP_CODE, _EXP_MSG))

    if len(specs) > n:
        return specs[:n]
    while len(specs) < n:
        specs.append(_recovering("IF", _IF_CODE, _IF_MSG))
    return specs


def _entity(spec: _Spec) -> dict[str, Any]:
    """The Razorpay entity body for ``spec``, matching what ``normalize`` reads."""
    entity: dict[str, Any] = {
        "id": spec.txn_id,
        "amount": spec.amount_paise,
        "currency": "INR",
        "status": "failed",
        "method": spec.method,
        "error_code": spec.error_code,
        "error_description": spec.error_message,
        "notes": {"customer_name": "Asha Menon"},
    }
    if spec.issuer is not None:
        entity["card"] = {"network": "Visa", "issuer": spec.issuer}
    if spec.phone is not None:
        entity["contact"] = spec.phone
    if spec.email is not None:
        entity["email"] = spec.email
    if spec.fraud:
        entity["fraud_flag"] = True
    return entity


def _payload(spec: _Spec, created_at_unix: int) -> dict[str, Any]:
    """The full Razorpay webhook envelope for ``spec``."""
    return {
        "entity": "event",
        "account_id": _MERCHANT_ID,
        "event": spec.event,
        "contains": [_EVENT_ENTITY_KEY[spec.event]],
        "id": spec.event_id,
        "payload": {_EVENT_ENTITY_KEY[spec.event]: {"entity": _entity(spec)}},
        "created_at": created_at_unix,
    }


def generate_batch(n: int = 50, *, seed: int = 42, clock: Clock) -> list[dict[str, Any]]:
    """Return ``n`` Razorpay-shaped webhook payloads, deterministic under ``seed``.

    The payloads carry every mandatory scenario (over-cap, breaker cluster,
    voice candidate, fraud, no-contact, unknown code) plus a distribution of
    recoverable and unrecoverable transactions across all six causes. Feed them to
    :meth:`~recoup.ingestion.idempotency.Ingestor.ingest_payload`; pair with the
    gateway from :func:`build_gateway` built at the same ``n`` and ``seed``.
    """
    created_at_unix = int(clock.now().timestamp())
    return [_payload(spec, created_at_unix) for spec in _specs(n, seed)]


def build_gateway(clock: Clock, *, n: int = 50, seed: int = 42) -> MockGateway:
    """A :class:`MockGateway` seeded to match :func:`generate_batch` at ``n``/``seed``.

    Every transaction is seeded with its scripted recovery attempt, and
    :data:`DEGRADED_ROUTE` is degraded so the cluster trips the breaker. Because
    both this and :func:`generate_batch` iterate the same :func:`_specs` output,
    the gateway and the payloads can never disagree about a transaction.
    """
    gateway = MockGateway(clock=clock, seed=seed)
    degrade = False
    for spec in _specs(n, seed):
        gateway.seed_transaction(
            GatewayTxn(
                txn_id=spec.txn_id,
                amount_paise=spec.amount_paise,
                status="failed",
                method=spec.method,
                issuer=spec.issuer,
            ),
            failure_code=spec.error_code,
            failure_message=spec.error_message,
            succeeds_on_attempt=spec.succeeds_on_attempt,
            failure_type=spec.failure_type,
        )
        degrade = degrade or spec.degraded
    if degrade:
        gateway.degrade_route(DEGRADED_ROUTE, failure_rate=1.0)
    return gateway


SEEDED_SCENARIOS: dict[str, str] = {
    spec.scenario: spec.txn_id for spec in _specs(50, 42) if spec.scenario
}
"""Scenario name -> the ``txn_id`` it generated at the default ``n=50``, ``seed=42``.

``breaker_cluster`` resolves to the *first* of the six clustered transactions,
since every one of them shares that label; :data:`DEGRADED_ROUTE` identifies the
whole cluster by route.
"""
