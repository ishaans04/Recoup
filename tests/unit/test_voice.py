"""Tests for the voice channel, script and TTS (PRD §9.7, §16.4). No real call placed."""

from __future__ import annotations

import tempfile
from pathlib import Path
from xml.etree import ElementTree

import httpx
import respx
from sqlalchemy import Engine

from recoup.channels.base import ChannelRegistry
from recoup.channels.router import ChannelRouter
from recoup.channels.sms import SmsChannel
from recoup.channels.voice import VoiceChannel, render_hero_audio, twiml_gather, twiml_say
from recoup.channels.voice_script import build_script
from recoup.clock import SimulatedClock
from recoup.config import Settings
from recoup.domain.enums import ActionType, Channel
from recoup.domain.models import Action, Customer
from recoup.policy.channel_policy import choose_channel_chain
from tests.conftest import CREATED_AT, make_work_item

_SID = "AC_voice_sid"
_CALLS_URL = f"https://api.twilio.com/2010-04-01/Accounts/{_SID}/Calls.json"
_MESSAGES_URL = f"https://api.twilio.com/2010-04-01/Accounts/{_SID}/Messages.json"
_BASE = "https://demo.ngrok.io"


class _LinkGateway:
    async def send_payment_link(self, txn_id: str) -> str:
        return "https://rzp.io/i/voice"


def _voice(from_number: str = "+15005550006") -> VoiceChannel:
    return VoiceChannel(_SID, "token", from_number, _LinkGateway(), public_base_url=_BASE)  # type: ignore[arg-type]


def _high_value_item():
    return make_work_item(
        amount_paise=4_500_000, customer=Customer(name="Asha", phone="+919876543210")
    )


def _nudge() -> Action:
    return Action(type=ActionType.CUSTOMER_NUDGE, channel=Channel.VOICE, reason="expired mandate")


@respx.mock
async def test_execute_places_a_call_and_returns_the_sid() -> None:
    respx.post(_CALLS_URL).mock(return_value=httpx.Response(201, json={"sid": "CA123"}))
    result = await _voice().execute(_high_value_item(), _nudge())
    assert result.delivered is True
    assert result.recovered is False
    assert result.provider_ref == "CA123"
    assert result.channel is Channel.VOICE


@respx.mock
async def test_twilio_failure_returns_not_delivered_without_raising() -> None:
    respx.post(_CALLS_URL).mock(return_value=httpx.Response(500, text="err"))
    result = await _voice().execute(_high_value_item(), _nudge())
    assert result.delivered is False
    assert "call not placed" in result.detail


def test_can_handle_only_high_value_with_phone_and_credentials() -> None:
    high = _high_value_item()
    low = make_work_item(amount_paise=100_000, customer=Customer(name="A", phone="+919876543210"))
    no_phone = make_work_item(amount_paise=4_500_000, customer=Customer(name="A", email="a@b.com"))
    assert _voice().can_handle(high) is True
    assert _voice().can_handle(low) is False
    assert _voice().can_handle(no_phone) is False
    assert _voice(from_number="").can_handle(high) is False


def test_high_value_expired_mandate_selects_voice_first() -> None:
    # Through Phase 5's policy, a high-value item with a phone leads with voice.
    item = _high_value_item()
    chain = choose_channel_chain(item)
    assert chain[0] is Channel.VOICE
    assert Channel.SMS in chain  # email absent for this customer, so it is not in the chain


def test_twiml_is_well_formed_and_carries_the_hinglish_line_amount_and_merchant() -> None:
    script = build_script(customer_name="Asha", amount_paise=4_500_000, phone="+919876543210")
    xml = twiml_gather(script, gather_action=f"{_BASE}/voice/gather/pay_1")
    root = ElementTree.fromstring(xml)  # raises if not well-formed
    assert root.tag == "Response"
    assert "fail ho gaya" in xml  # the Hinglish core line
    assert "Rs 45,000" in xml  # lakh-grouped amount
    assert "Recoup" in xml  # merchant identity


def test_twiml_say_is_well_formed() -> None:
    ElementTree.fromstring(twiml_say("Dhanyavaad."))


@respx.mock
async def test_voice_failure_falls_back_to_sms(engine: Engine) -> None:
    # Voice fails; the router audits it and continues to SMS, which delivers.
    respx.post(_CALLS_URL).mock(return_value=httpx.Response(500, text="busy"))
    respx.post(_MESSAGES_URL).mock(return_value=httpx.Response(201, json={"sid": "SM9"}))

    registry = ChannelRegistry()
    registry.register(_voice())
    registry.register(SmsChannel(_SID, "token", "+15005550006", _LinkGateway()))  # type: ignore[arg-type]
    from recoup.storage.audit import AuditLog

    audit = AuditLog(engine)
    router = ChannelRouter(registry, audit, SimulatedClock(start=CREATED_AT))

    item = _high_value_item()
    result = await router.deliver(item, _nudge(), [Channel.VOICE, Channel.SMS, Channel.EMAIL])
    assert result.delivered is True
    assert result.channel is Channel.SMS
    attempts = [r for r in audit.for_txn(item.txn_id) if "nudge attempt" in r.rationale]
    assert [a.to_state for a in attempts]  # both attempts audited
    assert "voice" in attempts[0].rationale and "sms" in attempts[1].rationale


def test_premium_voice_is_off_by_default() -> None:
    assert Settings().use_premium_voice is False


@respx.mock
async def test_cached_audio_is_not_regenerated() -> None:
    route = respx.post(url__regex=r"https://api\.elevenlabs\.io/.*").mock(
        return_value=httpx.Response(200, content=b"MP3DATA")
    )
    with tempfile.TemporaryDirectory(prefix="recoup-voice-") as tmp_dir:
        cache = Path(tmp_dir) / "hero.mp3"
        cache.write_bytes(b"already rendered")  # a prior render
        result = await render_hero_audio("line", api_key="k", cache_path=cache)
        assert result == cache
        assert route.call_count == 0  # a cache hit spends no ElevenLabs quota
