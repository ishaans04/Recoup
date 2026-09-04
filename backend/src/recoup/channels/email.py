"""The email nudge channel via Resend (PRD §8.7, §13.1).

The email sibling of :class:`~recoup.channels.sms.SmsChannel`, and it keeps the same
contract: an email delivers a payment link but recovers nothing by itself, and a
transport failure is a recorded ``delivered=False`` rather than a raise. It sends
both an HTML and a plain-text body so a text-only client still shows a usable message.
"""

from __future__ import annotations

import httpx

from recoup.channels.templates import render_nudge
from recoup.domain.enums import Channel
from recoup.domain.models import Action, ChannelResult, WorkItem
from recoup.gateways.base import PaymentGateway

__all__ = ["EmailChannel"]

_RESEND_URL = "https://api.resend.com/emails"


class EmailChannel:
    """Sends a recovery email through Resend's REST API."""

    def __init__(
        self,
        api_key: str,
        from_email: str,
        gateway: PaymentGateway,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._from = from_email
        self._gateway = gateway
        self._transport = transport
        self._timeout = timeout
        self._configured = bool(api_key and from_email)

    @property
    def name(self) -> Channel:
        return Channel.EMAIL

    def can_handle(self, item: WorkItem) -> bool:
        """True only when Resend is configured and the customer has an email."""
        return self._configured and bool((item.customer.email or "").strip())

    async def execute(self, item: WorkItem, action: Action) -> ChannelResult:
        """Fetch a payment link, send the email, and report delivery — never raising."""
        email = (item.customer.email or "").strip()
        try:
            link = await self._gateway.send_payment_link(item.txn_id)
        except Exception as exc:  # noqa: BLE001 - a link failure is a bounded non-delivery
            return ChannelResult(
                delivered=False,
                recovered=False,
                detail=f"email not sent: could not create a payment link ({type(exc).__name__})",
                channel=Channel.EMAIL,
            )

        message = render_nudge(
            customer_name=item.customer.name,
            amount_paise=item.amount_paise,
            payment_link=link,
            phone=item.customer.phone,
        )
        body = {
            "from": self._from,
            "to": [email],
            "subject": message.email_subject,
            "html": message.email_html,
            "text": message.email_text,
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    _RESEND_URL,
                    json=body,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return ChannelResult(
                delivered=False,
                recovered=False,
                detail=f"email not sent: Resend unreachable ({type(exc).__name__})",
                channel=Channel.EMAIL,
            )

        if response.status_code >= 400:
            return ChannelResult(
                delivered=False,
                recovered=False,
                detail=f"email not sent: Resend returned {response.status_code}",
                channel=Channel.EMAIL,
            )

        return ChannelResult(
            delivered=True,
            recovered=False,
            detail=f"recovery email sent to {email} with the payment link",
            provider_ref=_email_id(response),
            channel=Channel.EMAIL,
        )


def _email_id(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except (ValueError, TypeError):
        return None
    email_id = body.get("id") if isinstance(body, dict) else None
    return str(email_id) if email_id else None
