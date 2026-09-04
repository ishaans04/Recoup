"""Tests for the Twilio SMS channel (PRD §8.7, §13.1). HTTP mocked with respx."""

from __future__ import annotations

from urllib.parse import unquote

import httpx
import respx

from recoup.channels.sms import SmsChannel
from recoup.domain.enums import ActionType, Channel
from recoup.domain.models import Action, Customer
from tests.conftest import make_work_item

_SID = "AC_test_sid"
_MESSAGES_URL = f"https://api.twilio.com/2010-04-01/Accounts/{_SID}/Messages.json"
_LINK = "https://rzp.io/i/demo42"


class _LinkGateway:
    """A minimal gateway that only needs to hand back a payment link."""

    async def send_payment_link(self, txn_id: str) -> str:
        return _LINK


def _channel(from_number: str = "+15005550006") -> SmsChannel:
    return SmsChannel(_SID, "token", from_number, _LinkGateway())  # type: ignore[arg-type]


def _nudge() -> Action:
    return Action(type=ActionType.CUSTOMER_NUDGE, channel=Channel.SMS, reason="expired instrument")


@respx.mock
async def test_successful_send_reports_delivered_with_the_provider_ref() -> None:
    route = respx.post(_MESSAGES_URL).mock(
        return_value=httpx.Response(201, json={"sid": "SM123", "status": "queued"})
    )
    item = make_work_item(customer=Customer(name="Asha", phone="+919876543210"))
    result = await _channel().execute(item, _nudge())
    assert result.delivered is True
    assert result.recovered is False
    assert result.provider_ref == "SM123"
    assert result.channel is Channel.SMS
    # The payment link from the gateway is in the body Twilio received.
    assert _LINK in unquote(route.calls.last.request.content.decode())


@respx.mock
async def test_transport_failure_returns_not_delivered_without_raising() -> None:
    respx.post(_MESSAGES_URL).mock(side_effect=httpx.ConnectError("no network"))
    item = make_work_item(customer=Customer(name="Asha", phone="+919876543210"))
    result = await _channel().execute(item, _nudge())
    assert result.delivered is False
    assert "sms not sent" in result.detail


@respx.mock
async def test_4xx_from_twilio_is_not_delivered() -> None:
    respx.post(_MESSAGES_URL).mock(return_value=httpx.Response(400, json={"message": "bad"}))
    item = make_work_item(customer=Customer(name="Asha", phone="+919876543210"))
    result = await _channel().execute(item, _nudge())
    assert result.delivered is False


def test_can_handle_requires_credentials_and_a_phone() -> None:
    with_phone = make_work_item(customer=Customer(name="Asha", phone="+919876543210"))
    without_phone = make_work_item(customer=Customer(name="Asha", phone=None, email="a@b.com"))
    assert _channel().can_handle(with_phone) is True
    assert _channel().can_handle(without_phone) is False
    # No from-number configured -> not usable, even with a phone on file.
    assert _channel(from_number="").can_handle(with_phone) is False
