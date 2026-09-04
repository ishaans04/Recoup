"""The voice-call TwiML and callback routes (PRD §16.4, §14).

Twilio fetches the call's TwiML from ``/voice/twiml/{txn_id}``, posts the keypress to
``/voice/gather/{txn_id}``, and posts the final call status to
``/voice/status/{txn_id}``. Every branch writes an audit row, so the call's whole
course — spoken, answered or not, key pressed or not — is in the trail.

These are public endpoints that can trigger an SMS send, so they carry the same
security discipline as the Razorpay webhook (PRD §14): every request is checked
against Twilio's ``X-Twilio-Signature``, computed over the *public* URL and the
request parameters with the account auth token. An unauthenticated caller cannot
drive them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from pathlib import Path

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from recoup.channels.voice import render_hero_audio, twiml_gather, twiml_say
from recoup.channels.voice_script import build_script
from recoup.domain.enums import ActionType, Channel
from recoup.domain.models import Action, AuditEvent, WorkItem

_VOICE_AUDIO_CACHE = Path(".recoup_cache") / "voice"


def _audio_path(txn_id: str) -> Path:
    """The on-disk MP3 cache path for a transaction's premium (ElevenLabs) audio."""
    return _VOICE_AUDIO_CACHE / f"{txn_id}.mp3"


# Excluded from the OpenAPI schema: these are Twilio-facing callbacks, not part of
# the dashboard interface contract, so they never appear in the generated frontend
# types and the contract's route set stays exactly the dashboard's.
router = APIRouter(tags=["voice"], include_in_schema=False)

_XML = "application/xml"


def verify_twilio_signature(
    auth_token: str, url: str, params: dict[str, str], signature: str
) -> bool:
    """Twilio's request-signature check: HMAC-SHA1 over the URL and sorted params.

    Constant-time comparison, and ``False`` for a missing token or signature rather
    than a raise or an accidental pass — an unconfigured token is never permission to
    accept unsigned traffic.
    """
    if not auth_token or not signature:
        return False
    payload = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


async def _authenticate(request: Request) -> tuple[dict[str, str], bool]:
    """Return the request's form params and whether its Twilio signature verifies."""
    ctx = request.app.state.ctx
    token = ctx.settings.twilio_auth_token or ""
    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    public_base = (ctx.settings.public_base_url or "").rstrip("/")
    url = f"{public_base}{request.url.path}"
    signature = request.headers.get("X-Twilio-Signature", "")
    return params, verify_twilio_signature(token, url, params, signature)


def _forbidden() -> Response:
    return PlainTextResponse("invalid Twilio signature", status_code=403)


def _audit(request: Request, item: WorkItem, *, rationale: str, outcome: str) -> None:
    ctx = request.app.state.ctx
    ctx.runtime.audit.append(
        AuditEvent(
            timestamp=ctx.clock.now(),
            txn_id=item.txn_id,
            from_state=item.state,
            to_state=item.state,
            outcome=outcome,
            rationale=rationale,
        )
    )


@router.api_route("/voice/twiml/{txn_id}", methods=["GET", "POST"])
async def voice_twiml(request: Request, txn_id: str) -> Response:
    """Return the call's TwiML: speak the Hinglish script, then gather one keypress."""
    ctx = request.app.state.ctx
    item = ctx.runtime.repo.get(txn_id)
    if item is None:
        return Response(
            content=twiml_say("Sorry, we could not find this payment."), media_type=_XML
        )

    script = build_script(
        customer_name=item.customer.name,
        amount_paise=item.amount_paise,
        phone=item.customer.phone,
    )
    base = (ctx.settings.public_base_url or "").rstrip("/")

    # Premium (ElevenLabs) voice, opt-in and cost-disciplined (PRD §9.7): render the
    # line to an MP3 once, cache it, and point Twilio's <Play> at /voice/audio. Any
    # failure falls back to Twilio's free native <Say> — the call still happens.
    play_url: str | None = None
    if ctx.settings.use_premium_voice and ctx.settings.elevenlabs_api_key:
        audio = await render_hero_audio(
            script.intro,
            api_key=ctx.settings.elevenlabs_api_key,
            cache_path=_audio_path(txn_id),
        )
        if audio is not None and base:
            play_url = f"{base}/voice/audio/{txn_id}"

    xml = twiml_gather(script, gather_action=f"{base}/voice/gather/{txn_id}", play_url=play_url)
    return Response(content=xml, media_type=_XML)


@router.get("/voice/audio/{txn_id}")
async def voice_audio(request: Request, txn_id: str) -> Response:
    """Serve the cached ElevenLabs MP3 for a call (fetched by Twilio's ``<Play>``)."""
    path = _audio_path(txn_id)
    if not path.exists():
        return Response(status_code=404)
    return Response(content=path.read_bytes(), media_type="audio/mpeg")


@router.post("/voice/gather/{txn_id}")
async def voice_gather(request: Request, txn_id: str) -> Response:
    """Handle the keypress: 1 texts the payment link, 2 declines, no input is a no-answer."""
    params, ok = await _authenticate(request)
    if not ok:
        return _forbidden()

    ctx = request.app.state.ctx
    item = ctx.runtime.repo.get(txn_id)
    if item is None:
        return Response(
            content=twiml_say("Sorry, we could not find this payment."), media_type=_XML
        )

    script = build_script(
        customer_name=item.customer.name, amount_paise=item.amount_paise, phone=item.customer.phone
    )
    digit = params.get("Digits", "")

    if digit == "1":
        sms = ctx.runtime.registry.get(Channel.SMS)
        sent = False
        if sms is not None and sms.can_handle(item):
            action = Action(
                type=ActionType.CUSTOMER_NUDGE, channel=Channel.SMS, reason="voice keypress opt-in"
            )
            result = await sms.execute(item, action)
            sent = result.delivered
        _audit(
            request,
            item,
            rationale=f"voice keypress 1: payment link SMS {'sent' if sent else 'attempted'}",
            outcome="link sent" if sent else "link send failed",
        )
        return Response(content=twiml_say(script.confirm_sms), media_type=_XML)

    if digit == "2":
        _audit(request, item, rationale="voice keypress 2: customer declined", outcome="declined")
        return Response(content=twiml_say(script.decline), media_type=_XML)

    _audit(request, item, rationale="voice call: no keypress received", outcome="no input")
    return Response(content=twiml_say(script.no_input), media_type=_XML)


@router.post("/voice/status/{txn_id}")
async def voice_status(request: Request, txn_id: str) -> Response:
    """Record Twilio's final call-status callback (completed / busy / no-answer / failed)."""
    params, ok = await _authenticate(request)
    if not ok:
        return _forbidden()

    ctx = request.app.state.ctx
    item = ctx.runtime.repo.get(txn_id)
    if item is not None:
        status = params.get("CallStatus", "unknown")
        _audit(request, item, rationale=f"voice call status: {status}", outcome=status)
    return PlainTextResponse("ok")
