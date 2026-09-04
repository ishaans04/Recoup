"""Application settings.

The governing rule here is that **every credential is optional**. The application
must construct, boot and pass its whole test suite with an empty ``.env`` and no
environment variables at all. A missing key is not an error — it selects a mock
implementation for that service (PRD section 13.3: the demo must survive a dead
network). Crashing on a missing Twilio token would mean the payment core could not
run without a telephony account, which is exactly the coupling the adapter layer
exists to prevent.

That choice has a cost worth naming: a typo in a key name yields silent mock mode
rather than a startup error. :meth:`Settings.missing_credentials` and
:meth:`Settings.describe_mode` exist so the ``/api/health`` endpoint and the
dashboard can report honestly which services are real and which are simulated,
instead of letting a mocked run be mistaken for a live one.

The caps are settings rather than constants because they are policy, and policy
per merchant differs. They are *not* optional and have no ``None`` state: there is
no configuration in which Recoup runs without a retry cap or an amount cap.
"""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings"]


class Settings(BaseSettings):
    """Configuration, read from the environment and an optional ``.env`` file.

    Field names are lowercase; ``pydantic-settings`` matches environment variables
    case-insensitively, so ``recoup_mode`` is set by ``RECOUP_MODE``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Operating mode ---------------------------------------------------- #

    recoup_mode: Literal["mock", "live"] = "mock"
    """``mock`` uses simulated adapters for every external service; ``live`` uses
    the real ones. Defaults to ``mock`` so that the safe mode is the one you get by
    doing nothing, and reaching a real payment API requires a deliberate act."""

    database_url: str = "sqlite:///./recoup.db"
    """SQLite by default (PRD section 9.6): zero setup, zero network failure points
    and a single inspectable file. The schema is the one Postgres would use, so the
    URL is all that changes in production."""

    # -- Diagnosis (phase 11) ---------------------------------------------- #

    groq_api_key: str | None = None
    """Tier-2 diagnosis. Absent, the engine uses the rules table alone and returns
    an `unknown` cause with a `fallback` source for anything it cannot match."""

    # -- Payments (phases 7 and 12) ---------------------------------------- #

    razorpay_key_id: str | None = None
    """Razorpay test-mode key id. Absent, the mock gateway is used."""

    razorpay_key_secret: str | None = None
    """Razorpay test-mode key secret. Absent, the mock gateway is used."""

    razorpay_webhook_secret: str | None = None
    """HMAC secret for webhook signature verification. Absent, only the internal
    demo-injection endpoint can create work items; the webhook route rejects
    everything, because an unverified webhook is not an acceptable source of
    money actions."""

    # -- Telephony and messaging (phases 13 and 14) ------------------------ #

    twilio_account_sid: str | None = None
    """Twilio account SID for SMS and voice. Absent, both are mocked."""

    twilio_auth_token: str | None = None
    """Twilio auth token. Absent, SMS and voice are mocked."""

    twilio_phone_number: str | None = None
    """The verified sending number. Absent, SMS and voice are mocked."""

    elevenlabs_api_key: str | None = None
    """Voice synthesis for the high-value call. Absent, Twilio's native
    text-to-speech is used, which is adequate and free."""

    public_base_url: str | None = None
    """The publicly reachable base URL (e.g. an ngrok URL) Twilio uses to fetch the
    voice-call TwiML and post status callbacks. Absent, the voice channel is not
    built and nudges fall through to SMS/email."""

    use_premium_voice: bool = False
    """Whether the high-value hero call uses ElevenLabs audio. Off by default (PRD
    §9.7): the free character quota must not be burned on test calls, so premium is
    a deliberate opt-in for the single staged call."""

    resend_api_key: str | None = None
    """Transactional email. Absent, the email channel is mocked."""

    # -- Policy caps (PRD section 12.2) ------------------------------------ #

    max_retries: int = Field(default=3, ge=0)
    """The retry cap. A work item that has already been retried this many times is
    escalated rather than retried again."""

    max_amount_paise: int = Field(default=5_000_000, ge=0)
    """The amount cap, in paise. 5,000,000 paise is Rs 50,000 — the figure the PRD
    names in section 12.2 and the one the demo's deliberate rejection exceeds."""

    min_llm_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    """The confidence floor for acting on a Tier-2 diagnosis. Below it, PRD section
    11.3 forbids guessing a money action: the item takes the safest bounded action
    or goes to a human."""

    @property
    def is_live(self) -> bool:
        """Whether the application is configured to talk to real services."""
        return self.recoup_mode == "live"

    def missing_credentials(self) -> tuple[str, ...]:
        """The credential fields that are unset, in declaration order.

        Every name returned here corresponds to a service that will be mocked. The
        health endpoint reports this so a mocked run cannot be mistaken for a live
        one — which matters because PRD section 13.4 requires the metrics on screen
        to be honest about what actually happened.
        """
        return tuple(
            name
            for name in (
                "groq_api_key",
                "razorpay_key_id",
                "razorpay_key_secret",
                "razorpay_webhook_secret",
                "twilio_account_sid",
                "twilio_auth_token",
                "twilio_phone_number",
                "elevenlabs_api_key",
                "resend_api_key",
            )
            if not getattr(self, name)
        )

    def describe_mode(self) -> str:
        """A one-line, human-readable summary of what is real and what is not."""
        missing = self.missing_credentials()
        if not missing:
            return f"mode={self.recoup_mode}; all credentials present"
        return f"mode={self.recoup_mode}; mocked services: {', '.join(missing)}"
