"""Building the nudge channels from configuration (PRD §8.7, §13.1).

SMS needs a full Twilio triple (account SID, auth token, from-number); email needs a
Resend key. A channel is built only when its credentials are present, so a
deployment with, say, a Twilio account but no purchased number simply has no SMS
channel and the router falls through to email — no crash, no half-configured sender.
"""

from __future__ import annotations

from recoup.channels.base import RecoveryChannel
from recoup.channels.email import EmailChannel
from recoup.channels.sms import SmsChannel
from recoup.channels.voice import VoiceChannel
from recoup.config import Settings
from recoup.gateways.base import PaymentGateway

__all__ = ["build_nudge_channels"]

# Resend's shared sender works without a verified domain (test tier delivers to the
# account owner). Swap for a verified domain sender in production.
_DEFAULT_EMAIL_FROM = "Recoup <onboarding@resend.dev>"


def build_nudge_channels(settings: Settings, gateway: PaymentGateway) -> list[RecoveryChannel]:
    """The nudge channels whose credentials are configured, in preference order."""
    channels: list[RecoveryChannel] = []
    twilio_ready = bool(
        settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_phone_number
    )
    if twilio_ready and settings.public_base_url:
        # Voice needs a public URL for Twilio to fetch its TwiML; without one it is
        # simply not built and the chain falls through to SMS/email.
        channels.append(
            VoiceChannel(
                settings.twilio_account_sid,  # type: ignore[arg-type]  # twilio_ready guards None
                settings.twilio_auth_token,  # type: ignore[arg-type]
                settings.twilio_phone_number,  # type: ignore[arg-type]
                gateway,
                public_base_url=settings.public_base_url,
            )
        )
    if twilio_ready:
        channels.append(
            SmsChannel(
                settings.twilio_account_sid,  # type: ignore[arg-type]
                settings.twilio_auth_token,  # type: ignore[arg-type]
                settings.twilio_phone_number,  # type: ignore[arg-type]
                gateway,
            )
        )
    if settings.resend_api_key:
        channels.append(EmailChannel(settings.resend_api_key, _DEFAULT_EMAIL_FROM, gateway))
    return channels
