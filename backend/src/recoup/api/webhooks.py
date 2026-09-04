"""The Razorpay webhook endpoint — a security boundary (PRD §14, contract §3.11).

Two properties make this route trustworthy, and both are load-bearing:

**The signature is verified against the raw bytes, before anything is parsed.** The
handler reads ``await request.body()`` and hands those exact bytes to
:meth:`~recoup.ingestion.idempotency.Ingestor.ingest_raw`. FastAPI is never allowed
to parse the body into a model first, because verifying a signature against a
re-serialised parse of attacker-controlled input is not verifying the bytes that
arrived.

**A duplicate delivery is a success, not an error.** A webhook redelivered with an
``event_id`` already seen returns ``200`` with ``duplicate: true`` and does not start
a second recovery — returning an error would make Razorpay retry the delivery
forever. A genuinely new event returns ``202`` and is processed to a settled or
parked state before the response returns, so the audit trail is ready the moment the
caller (or the dashboard behind it) looks.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from recoup.api.errors import error_response
from recoup.api.processing import drive_until_settled
from recoup.api.schemas import WebhookAcceptedOut
from recoup.ingestion.idempotency import InvalidSignature
from recoup.ingestion.normalize import MalformedPayload, UnsupportedEvent

router = APIRouter(tags=["webhooks"])

_SIGNATURE_HEADER = "X-Razorpay-Signature"


@router.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request) -> JSONResponse:
    """Verify, normalise, idempotently store and process one Razorpay webhook."""
    ctx = request.app.state.ctx
    body = await request.body()
    signature = request.headers.get(_SIGNATURE_HEADER)

    try:
        async with ctx.write_lock:
            result = ctx.runtime.ingestor.ingest_raw(body, signature)
            if result.created:
                await drive_until_settled(ctx.runtime.orchestrator, ctx.clock, result.item)
    except InvalidSignature:
        # The body is discarded unparsed; nothing is written (contract §3.11).
        return error_response(401, "invalid_signature", "Webhook signature verification failed.")
    except (MalformedPayload, UnsupportedEvent) as exc:
        return error_response(400, "invalid_request", str(exc))

    payload = WebhookAcceptedOut(
        accepted=True, txn_id=result.item.txn_id, duplicate=not result.created
    )
    status_code = 202 if result.created else 200
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))
