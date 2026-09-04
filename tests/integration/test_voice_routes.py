"""Integration tests for the voice TwiML/callback routes (PRD §16.4, §14).

Driven in-process through ``httpx.ASGITransport``. No real call or SMS is placed —
the keypress test swaps a spy into the registry, so nothing leaves the process.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from recoup.api.app import create_app
from recoup.config import Settings
from recoup.domain.enums import Channel
from recoup.domain.models import Action, ChannelResult, Customer, WorkItem
from tests.conftest import make_work_item

_TOKEN = "twilio_test_token"
_BASE = "https://demo.ngrok.io"
_TXN = "pay_voice1"


class _SpySms:
    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def name(self) -> Channel:
        return Channel.SMS

    def can_handle(self, item: WorkItem) -> bool:
        return True

    async def execute(self, item: WorkItem, action: Action) -> ChannelResult:
        self.calls.append(item.txn_id)
        return ChannelResult(delivered=True, recovered=False, detail="spy sms", channel=Channel.SMS)


@pytest.fixture
def voice_app() -> Iterator[FastAPI]:
    with tempfile.TemporaryDirectory(prefix="recoup-voice-") as tmp_dir:
        db_path = f"{tmp_dir}/voice.db".replace("\\", "/")
        settings = Settings(
            _env_file=None,  # hermetic: never read the real .env
            database_url=f"sqlite:///{db_path}",
            twilio_account_sid="AC_test",
            twilio_auth_token=_TOKEN,
            twilio_phone_number="+15005550006",
            public_base_url=_BASE,
        )
        app = create_app(settings)
        app.state.ctx.runtime.repo.create_if_absent(
            make_work_item(
                txn_id=_TXN,
                event_id="evt_voice1",
                amount_paise=4_500_000,
                customer=Customer(name="Asha", phone="+919876543210"),
            )
        )
        try:
            yield app
        finally:
            app.state.ctx.engine.dispose()


@pytest_asyncio.fixture
async def client(voice_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=voice_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


def _sign(path: str, params: dict[str, str]) -> str:
    payload = f"{_BASE}{path}" + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(_TOKEN.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def _audit_outcomes(app: FastAPI, txn_id: str) -> list[str]:
    return [r.outcome or "" for r in app.state.ctx.runtime.audit.for_txn(txn_id)]


async def test_twiml_route_returns_the_hinglish_script(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/voice/twiml/{_TXN}")
    assert response.status_code == 200
    body = response.text
    assert "<Gather" in body
    assert "fail ho gaya" in body  # Hinglish
    assert "Rs 45,000" in body
    # Default (non-premium) voice uses Twilio's free native <Say>, not ElevenLabs.
    assert "<Say" in body
    assert "<Play>" not in body


async def test_premium_voice_twiml_plays_the_elevenlabs_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Premium voice on, with the audio already cached, so no ElevenLabs call is made
    # and no real credential is used. The TwiML must <Play> the cached MP3, and the
    # audio route must serve it.
    with tempfile.TemporaryDirectory(prefix="recoup-voice-cache-") as cache_dir:
        cache = Path(cache_dir)
        monkeypatch.setattr("recoup.api.voice._VOICE_AUDIO_CACHE", cache)
        (cache / f"{_TXN}.mp3").write_bytes(b"ID3-fake-mp3-bytes")

        with tempfile.TemporaryDirectory(prefix="recoup-voice-db-") as db_dir:
            settings = Settings(
                _env_file=None,
                database_url=f"sqlite:///{db_dir}/v.db".replace("\\", "/"),
                twilio_account_sid="AC_test",
                twilio_auth_token=_TOKEN,
                twilio_phone_number="+15005550006",
                public_base_url=_BASE,
                elevenlabs_api_key="fake-elevenlabs-key",
                use_premium_voice=True,
            )
            app = create_app(settings)
            app.state.ctx.runtime.repo.create_if_absent(
                make_work_item(
                    txn_id=_TXN,
                    event_id="evt_voice1",
                    amount_paise=4_500_000,
                    customer=Customer(name="Asha", phone="+919876543210"),
                )
            )
            transport = httpx.ASGITransport(app=app)
            try:
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    twiml = (await client.get(f"/voice/twiml/{_TXN}")).text
                    assert "<Play>" in twiml
                    assert f"/voice/audio/{_TXN}" in twiml

                    audio = await client.get(f"/voice/audio/{_TXN}")
                    assert audio.status_code == 200
                    assert audio.headers["content-type"].startswith("audio/mpeg")
                    assert audio.content == b"ID3-fake-mp3-bytes"
            finally:
                app.state.ctx.engine.dispose()


async def test_voice_audio_returns_404_when_not_rendered(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"/voice/audio/{_TXN}")).status_code == 404


async def test_keypress_1_triggers_payment_link_sms(
    client: httpx.AsyncClient, voice_app: FastAPI
) -> None:
    spy = _SpySms()
    voice_app.state.ctx.runtime.registry._channels[Channel.SMS] = spy  # type: ignore[assignment]
    path = f"/voice/gather/{_TXN}"
    params = {"Digits": "1"}
    response = await client.post(
        path, data=params, headers={"X-Twilio-Signature": _sign(path, params)}
    )
    assert response.status_code == 200
    assert spy.calls == [_TXN]  # the SMS channel was invoked
    assert "link sent" in _audit_outcomes(voice_app, _TXN)


async def test_keypress_2_records_a_decline_and_sends_nothing(
    client: httpx.AsyncClient, voice_app: FastAPI
) -> None:
    spy = _SpySms()
    voice_app.state.ctx.runtime.registry._channels[Channel.SMS] = spy  # type: ignore[assignment]
    path = f"/voice/gather/{_TXN}"
    params = {"Digits": "2"}
    response = await client.post(
        path, data=params, headers={"X-Twilio-Signature": _sign(path, params)}
    )
    assert response.status_code == 200
    assert spy.calls == []
    assert "declined" in _audit_outcomes(voice_app, _TXN)


async def test_no_input_records_no_answer(client: httpx.AsyncClient, voice_app: FastAPI) -> None:
    path = f"/voice/gather/{_TXN}"
    params: dict[str, str] = {}
    response = await client.post(
        path, data=params, headers={"X-Twilio-Signature": _sign(path, params)}
    )
    assert response.status_code == 200
    assert "no input" in _audit_outcomes(voice_app, _TXN)


async def test_status_callback_records_the_final_outcome(
    client: httpx.AsyncClient, voice_app: FastAPI
) -> None:
    path = f"/voice/status/{_TXN}"
    params = {"CallStatus": "completed"}
    response = await client.post(
        path, data=params, headers={"X-Twilio-Signature": _sign(path, params)}
    )
    assert response.status_code == 200
    assert "completed" in _audit_outcomes(voice_app, _TXN)


async def test_voice_routes_reject_unsigned_requests(client: httpx.AsyncClient) -> None:
    # No X-Twilio-Signature header at all: the endpoint must refuse to act.
    response = await client.post(f"/voice/gather/{_TXN}", data={"Digits": "1"})
    assert response.status_code == 403
