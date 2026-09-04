"""The SMS nudge channel via Twilio (PRD §8.7, §13.1).

An SMS does not itself recover money — the customer paying the link does — so
``execute`` always reports ``recovered=False`` and lets ``delivered`` say whether the
text was sent. It never raises: a transport failure is a recorded ``delivered=False``
with the reason in ``detail``, because a failed nudge is a bounded, audited outcome
the router falls through, not an exception that loses the work item.

Only this channel and its siblings talk to Twilio; the payment link comes from the
gateway, so the SMS carries a real re-collection URL rather than a hardcoded one.
"""

from __future__ import annotations

import httpx

from recoup.channels.templates import render_nudge
from recoup.domain.enums import Channel
from recoup.domain.models import Action, ChannelResult, WorkItem
from recoup.gateways.base import PaymentGateway

__all__ = ["SmsChannel"]

_TWILIO_BASE = "https://api.twilio.com/2010-04-01"


class SmsChannel:
    """Sends a recovery SMS through Twilio's REST API."""

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        gateway: PaymentGateway,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._sid = account_sid
        self._token = auth_token
        self._from = from_number
        self._gateway = gateway
        self._transport = transport
        self._timeout = timeout
        self._configured = bool(account_sid and auth_token and from_number)

    @property
    def name(self) -> Channel:
        return Channel.SMS

    def can_handle(self, item: WorkItem) -> bool:
        """True only when Twilio is configured and the customer has a phone number."""
        return self._configured and bool((item.customer.phone or "").strip())

    async def execute(self, item: WorkItem, action: Action) -> ChannelResult:
        """Fetch a payment link, send the SMS, and report delivery — never raising."""
        phone = (item.customer.phone or "").strip()
        try:
            link = await self._gateway.send_payment_link(item.txn_id)
        except Exception as exc:  # noqa: BLE001 - a link failure is a bounded non-delivery
            return ChannelResult(
                delivered=False,
                recovered=False,
                detail=f"sms not sent: could not create a payment link ({type(exc).__name__})",
                channel=Channel.SMS,
            )

        message = render_nudge(
            customer_name=item.customer.name,
            amount_paise=item.amount_paise,
            payment_link=link,
            phone=phone,
        ).sms_body

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, auth=(self._sid, self._token), transport=self._transport
            ) as client:
                response = await client.post(
                    f"{_TWILIO_BASE}/Accounts/{self._sid}/Messages.json",
                    data={"To": phone, "From": self._from, "Body": message},
                )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return ChannelResult(
                delivered=False,
                recovered=False,
                detail=f"sms not sent: Twilio unreachable ({type(exc).__name__})",
                channel=Channel.SMS,
            )

        if response.status_code >= 400:
            return ChannelResult(
                delivered=False,
                recovered=False,
                detail=f"sms not sent: Twilio returned {response.status_code}",
                channel=Channel.SMS,
            )

        sid = _message_sid(response)
        return ChannelResult(
            delivered=True,
            recovered=False,
            detail=f"recovery SMS sent to {phone} with the payment link",
            provider_ref=sid,
            channel=Channel.SMS,
        )


def _message_sid(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except (ValueError, TypeError):
        return None
    sid = body.get("sid") if isinstance(body, dict) else None
    return str(sid) if sid else None
