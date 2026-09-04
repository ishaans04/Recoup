"""Normalize a Razorpay webhook envelope into a :class:`WorkItem` (PRD section 8.1).

Everything downstream of ingestion — diagnosis, policy, the constraint gate,
recovery channels, the audit trail, the dashboard — speaks in
:class:`~recoup.domain.models.WorkItem`. None of it should ever need to know that
Razorpay's envelope looks like ``{event, account_id, payload: {<kind>: {entity:
{...}}}, created_at, id}``, or that the entity key varies by event type. This
module is the one place that shape is read.

Two identifiers live in the envelope and must never be conflated: the envelope's
own ``id`` is the webhook delivery's identity and becomes :attr:`WorkItem.event_id`
— the idempotency key PRD section 13.2 dedupes on. The nested entity's ``id`` (a
``pay_...``/``sub_...``/``inv_...`` Razorpay identifier) is the thing that failed
and becomes :attr:`WorkItem.txn_id`. Using one where the other belongs would either
break idempotency (two different failures sharing one dedupe key) or break the
ability to look a specific failure up by its PSP identifier.

Every check below raises before anything is constructed, let alone written to the
database — :func:`normalize` is called strictly before
:meth:`~recoup.storage.work_items.WorkItemRepo.create_if_absent`
(:mod:`recoup.ingestion.idempotency`), so a bad payload never leaves a partial work
item behind.
"""

from datetime import datetime
from typing import Any

from recoup.clock import IST, Clock
from recoup.domain.enums import FailureType
from recoup.domain.models import Customer, WorkItem

__all__ = ["MalformedPayload", "UnsupportedEvent", "normalize"]

_FRAUD_MARKERS = ("FRAUD", "RISK")
"""Substrings that, found in a failure code, indicate the PSP itself flagged the
transaction as suspicious rather than merely failed. Uppercased before comparison
so the check is case-insensitive."""

_UNKNOWN_CUSTOMER_NAME = "Unknown Customer"
"""Used when the entity carries no ``notes.customer_name``. PRD section 13.2 treats
missing *contact* (phone/email) as legal and expects Phase 5 to escalate on it via
:attr:`Customer.has_contact`; a missing *name* is the same kind of incompleteness in
a merchant's records and is handled the same way — normalize anyway, rather than
reject a real failure because a notes field was left blank."""


class UnsupportedEvent(Exception):
    """Raised for a webhook ``event`` outside the set this system recovers.

    Distinct from :class:`MalformedPayload`: the envelope is well-formed, but its
    event type is not one ingestion is built to turn into a work item.
    """


class MalformedPayload(Exception):
    """Raised when a required field is missing, or present with the wrong type.

    The message always names the specific field, so a rejected webhook is
    debuggable from the exception alone.
    """


# event -> (the key under payload.* that holds the relevant entity, the FailureType
# a work item derived from it carries).
_EVENT_ENTITY_KEY: dict[str, tuple[str, FailureType]] = {
    "payment.failed": ("payment", FailureType.ONE_TIME),
    "subscription.halted": ("subscription", FailureType.SUBSCRIPTION),
    "subscription.charged": ("payment", FailureType.SUBSCRIPTION),
    "invoice.expired": ("invoice", FailureType.INVOICE),
}


def _require_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MalformedPayload(f"{path} must be an object")
    return value


def _require_str(container: dict[str, Any], key: str, *, path: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MalformedPayload(f"{path} is required and must be a non-empty string")
    return value


def _require_int(container: dict[str, Any], key: str, *, path: str) -> int:
    value = container.get(key)
    # bool is a subclass of int; a webhook sending `true`/`false` here is a type
    # error, not an amount, so it must not slip through an isinstance(x, int) check.
    if not isinstance(value, int) or isinstance(value, bool):
        raise MalformedPayload(f"{path} is required and must be an integer")
    return value


def _optional_str(container: dict[str, Any], key: str) -> str | None:
    value = container.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise MalformedPayload(f"{key} must be a string when present")
    stripped = value.strip()
    return stripped or None


def _extract_entity(payload: dict[str, Any], entity_key: str) -> dict[str, Any]:
    payload_section = _require_dict(payload.get("payload"), path="payload")
    kind_section = _require_dict(payload_section.get(entity_key), path=f"payload.{entity_key}")
    return _require_dict(kind_section.get("entity"), path=f"payload.{entity_key}.entity")


def _extract_issuer(entity: dict[str, Any]) -> str | None:
    direct = _optional_str(entity, "issuer")
    if direct is not None:
        return direct
    card = entity.get("card")
    if isinstance(card, dict):
        card_issuer = _optional_str(card, "issuer")
        if card_issuer is not None:
            return card_issuer
    return _optional_str(entity, "bank")


def _extract_customer_name(entity: dict[str, Any]) -> str:
    notes = entity.get("notes")
    if isinstance(notes, dict):
        name = _optional_str(notes, "customer_name")
        if name is not None:
            return name
    return _UNKNOWN_CUSTOMER_NAME


def _is_fraud_flagged(entity: dict[str, Any], failure_code: str) -> bool:
    if bool(entity.get("fraud_flag")):
        return True
    if bool(entity.get("risk_flag")):
        return True
    upper_code = failure_code.upper()
    return any(marker in upper_code for marker in _FRAUD_MARKERS)


def _extract_created_at(payload: dict[str, Any], clock: Clock) -> datetime:
    raw = payload.get("created_at")
    if raw is None:
        return clock.now()
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise MalformedPayload("created_at must be a unix timestamp (integer seconds) when present")
    return datetime.fromtimestamp(raw, tz=IST)


def normalize(payload: dict[str, Any], *, clock: Clock) -> WorkItem:
    """Convert a raw Razorpay webhook envelope into a :class:`WorkItem`.

    Supports ``payment.failed``, ``subscription.halted``,
    ``subscription.charged`` (only when it reports a failed charge — a
    successful ``subscription.charged`` delivery is not a failure to recover
    from and raises :class:`UnsupportedEvent`), and ``invoice.expired``. Any
    other ``event`` raises :class:`UnsupportedEvent`.
    """
    if not isinstance(payload, dict):
        raise MalformedPayload("payload must be a JSON object")

    event = payload.get("event")
    if not isinstance(event, str) or not event:
        raise MalformedPayload("event is required and must be a non-empty string")
    if event not in _EVENT_ENTITY_KEY:
        raise UnsupportedEvent(f"unsupported event type: {event!r}")

    entity_key, failure_type = _EVENT_ENTITY_KEY[event]
    entity = _extract_entity(payload, entity_key)

    if event == "subscription.charged" and entity.get("status") != "failed":
        raise UnsupportedEvent(
            "subscription.charged does not report a failed charge "
            f"(status={entity.get('status')!r}); nothing to recover"
        )

    event_id = _require_str(payload, "id", path="id")
    merchant_id = _require_str(payload, "account_id", path="account_id")
    txn_id = _require_str(entity, "id", path=f"payload.{entity_key}.entity.id")
    amount_paise = _require_int(entity, "amount", path=f"payload.{entity_key}.entity.amount")
    failure_code = _require_str(
        entity, "error_code", path=f"payload.{entity_key}.entity.error_code"
    )
    failure_message = _require_str(
        entity, "error_description", path=f"payload.{entity_key}.entity.error_description"
    )
    method = _optional_str(entity, "method")
    issuer = _extract_issuer(entity)
    phone = _optional_str(entity, "contact")
    email = _optional_str(entity, "email")
    customer = Customer(name=_extract_customer_name(entity), phone=phone, email=email)
    fraud_flag = _is_fraud_flagged(entity, failure_code)
    created_at = _extract_created_at(payload, clock)

    return WorkItem(
        txn_id=txn_id,
        event_id=event_id,
        merchant_id=merchant_id,
        amount_paise=amount_paise,
        failure_code=failure_code,
        failure_message=failure_message,
        failure_type=failure_type,
        method=method,
        issuer=issuer,
        customer=customer,
        fraud_flag=fraud_flag,
        created_at=created_at,
    )
