"""The Hinglish voice recovery call via Twilio (PRD §9.7, §11.4, §16.4).

The demo hook: a high-value expired-mandate subscription gets a phone call, in
Hinglish, offering to text a payment link. Like every nudge it recovers nothing by
itself — the customer paying does — so ``execute`` reports ``recovered=False`` and
places the call, whose TwiML and outcome are served and recorded by the voice API
routes. It never raises: a Twilio failure is a recorded ``delivered=False`` and the
router falls through to SMS (PRD §13.1).

Two TTS paths carry the cost discipline of PRD §9.7. The default is Twilio's native
``<Say>`` (an Indian voice), which costs nothing extra and is used for all testing.
The ElevenLabs hero audio is opt-in behind ``use_premium_voice`` and is rendered
once and cached, so the small free character quota is never burned on a retry.
"""

from __future__ import annotations

import logging
from pathlib import Path
from xml.sax.saxutils import escape

import httpx

from recoup.channels.voice_script import VoiceScript
from recoup.domain.enums import Channel
from recoup.domain.models import Action, ChannelResult, WorkItem
from recoup.gateways.base import PaymentGateway
from recoup.policy.channel_policy import HIGH_VALUE_THRESHOLD_PAISE

__all__ = [
    "VoiceChannel",
    "render_hero_audio",
    "twiml_gather",
    "twiml_say",
]

_LOG = logging.getLogger("recoup.channels.voice")
_TWILIO_BASE = "https://api.twilio.com/2010-04-01"
_SAY_VOICE = "Polly.Aditi"  # a Twilio Indian voice that reads Hinglish acceptably
_ELEVENLABS_VOICE = "21m00Tcm4TlvDq8ikWAM"  # a default ElevenLabs voice id


def twiml_gather(script: VoiceScript, *, gather_action: str, play_url: str | None = None) -> str:
    """The call's TwiML: speak (or play) the script, then gather one keypress."""
    if play_url is not None:
        prompt = f"<Play>{escape(play_url)}</Play>"
    else:
        prompt = f'<Say voice="{_SAY_VOICE}">{escape(script.intro)}</Say>'
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Gather numDigits="1" action="{escape(gather_action)}" method="POST" timeout="6">'
        f"{prompt}"
        "</Gather>"
        f'<Say voice="{_SAY_VOICE}">{escape(script.no_input)}</Say>'
        "</Response>"
    )


def twiml_say(text: str) -> str:
    """A one-line spoken TwiML response (a confirmation or a sign-off)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response><Say voice="{_SAY_VOICE}">{escape(text)}</Say></Response>'
    )


class VoiceChannel:
    """Places an outbound recovery call through Twilio's REST API."""

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        gateway: PaymentGateway,
        *,
        public_base_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._sid = account_sid
        self._token = auth_token
        self._from = from_number
        self._gateway = gateway
        self._base_url = public_base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout
        self._configured = bool(account_sid and auth_token and from_number and public_base_url)

    @property
    def name(self) -> Channel:
        return Channel.VOICE

    def can_handle(self, item: WorkItem) -> bool:
        """True only for a configured, high-value item with a phone number.

        An independent second check on top of Phase 5's chain, which already reserves
        voice for high-value expired-instrument nudges — defence in depth, so voice
        is never placed for a low-value case even if the chain were ever miswired.
        """
        return (
            self._configured
            and bool((item.customer.phone or "").strip())
            and item.amount_paise >= HIGH_VALUE_THRESHOLD_PAISE
        )

    async def execute(self, item: WorkItem, action: Action) -> ChannelResult:
        """Place the call; report whether Twilio accepted it — never raising."""
        phone = (item.customer.phone or "").strip()
        data = {
            "To": phone,
            "From": self._from,
            "Url": f"{self._base_url}/voice/twiml/{item.txn_id}",
            "StatusCallback": f"{self._base_url}/voice/status/{item.txn_id}",
            "StatusCallbackEvent": "completed",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, auth=(self._sid, self._token), transport=self._transport
            ) as client:
                response = await client.post(
                    f"{_TWILIO_BASE}/Accounts/{self._sid}/Calls.json", data=data
                )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return ChannelResult(
                delivered=False,
                recovered=False,
                detail=f"call not placed: Twilio unreachable ({type(exc).__name__})",
                channel=Channel.VOICE,
            )

        if response.status_code >= 400:
            return ChannelResult(
                delivered=False,
                recovered=False,
                detail=f"call not placed: Twilio returned {response.status_code}",
                channel=Channel.VOICE,
            )

        return ChannelResult(
            delivered=True,
            recovered=False,
            detail=f"recovery call placed to {phone}",
            provider_ref=_call_sid(response),
            channel=Channel.VOICE,
        )


def _call_sid(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except (ValueError, TypeError):
        return None
    sid = body.get("sid") if isinstance(body, dict) else None
    return str(sid) if sid else None


async def render_hero_audio(
    text: str,
    *,
    api_key: str,
    cache_path: Path,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: float = 30.0,
) -> Path | None:
    """Render ``text`` to an MP3 via ElevenLabs, cached on disk. ``None`` on failure.

    A cache hit returns immediately and makes **no** API call, so the free character
    quota is spent at most once per distinct line (PRD §9.7). Any error degrades to
    ``None`` and the caller falls back to Twilio's native voice.
    """
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{_ELEVENLABS_VOICE}"
    body = {"text": text, "model_id": "eleven_multilingual_v2"}
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.post(
                url, json=body, headers={"xi-api-key": api_key, "accept": "audio/mpeg"}
            )
        if response.status_code >= 400:
            return None
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(response.content)
        return cache_path
    except (httpx.TimeoutException, httpx.TransportError, OSError):
        _LOG.warning("ElevenLabs render failed; using Twilio native voice")
        return None
