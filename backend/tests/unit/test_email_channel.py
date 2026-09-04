"""Tests for the Resend email channel (PRD §8.7, §13.1). HTTP mocked with respx."""

from __future__ import annotations

import httpx
import respx

from recoup.channels.email import EmailChannel
from recoup.domain.enums import ActionType, Channel
from recoup.domain.models import Action, Customer
from tests.conftest import make_work_item

_RESEND_URL = "https://api.resend.com/emails"
_LINK = "https://rzp.io/i/demo99"


class _LinkGateway:
    async def send_payment_link(self, txn_id: str) -> str:
        return _LINK


def _channel(api_key: str = "re_test_key") -> EmailChannel:
    return EmailChannel(api_key, "Recoup <onboarding@resend.dev>", _LinkGateway())  # type: ignore[arg-type]


def _nudge() -> Action:
    return Action(
        type=ActionType.CUSTOMER_NUDGE, channel=Channel.EMAIL, reason="expired instrument"
    )


@respx.mock
async def test_successful_send_reports_delivered_with_the_provider_ref() -> None:
    route = respx.post(_RESEND_URL).mock(return_value=httpx.Response(200, json={"id": "email_1"}))
    item = make_work_item(customer=Customer(name="Asha", email="asha@example.com"))
    result = await _channel().execute(item, _nudge())
    assert result.delivered is True
    assert result.recovered is False
    assert result.provider_ref == "email_1"
    assert result.channel is Channel.EMAIL
    assert _LINK in route.calls.last.request.content.decode()


@respx.mock
async def test_transport_failure_returns_not_delivered_without_raising() -> None:
    respx.post(_RESEND_URL).mock(side_effect=httpx.ConnectTimeout("slow"))
    item = make_work_item(customer=Customer(name="Asha", email="asha@example.com"))
    result = await _channel().execute(item, _nudge())
    assert result.delivered is False
    assert "email not sent" in result.detail


def test_can_handle_requires_credentials_and_an_email() -> None:
    with_email = make_work_item(customer=Customer(name="Asha", email="asha@example.com"))
    without_email = make_work_item(
        customer=Customer(name="Asha", phone="+919876543210", email=None)
    )
    assert _channel().can_handle(with_email) is True
    assert _channel().can_handle(without_email) is False
    assert _channel(api_key="").can_handle(with_email) is False
