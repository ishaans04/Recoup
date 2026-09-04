"""Nudge message templates, English and Hinglish (PRD §8.7, §16.4).

A nudge tells a customer, plainly, what failed, what it costs, and the one action
that fixes it — the payment link. No manufactured urgency, no fake deadline: an
autonomous system that pressures customers is exactly what a merchant cannot afford
to put its name on. The merchant identity is always present so the message is not
mistaken for phishing.

Language is chosen per customer by an explicit, testable rule: an Indian mobile
number (``+91``) gets Hinglish — the register most of these customers actually read —
and everything else gets English.
"""

from __future__ import annotations

from dataclasses import dataclass

from recoup.money import format_inr_paise

__all__ = ["NudgeMessage", "choose_language", "render_nudge"]

_MERCHANT = "Recoup"


@dataclass(frozen=True)
class NudgeMessage:
    """One rendered nudge, in every form a channel might need."""

    language: str
    sms_body: str
    email_subject: str
    email_text: str
    email_html: str


def choose_language(phone: str | None) -> str:
    """``"hinglish"`` for an Indian (+91) mobile number, ``"english"`` otherwise."""
    normalised = (phone or "").replace(" ", "")
    return "hinglish" if normalised.startswith("+91") else "english"


def render_nudge(
    *, customer_name: str, amount_paise: int, payment_link: str, phone: str | None
) -> NudgeMessage:
    """Render the nudge for ``phone``'s language, carrying the amount and link."""
    amount = format_inr_paise(amount_paise)
    name = customer_name.strip() or "there"
    language = choose_language(phone)

    if language == "hinglish":
        sms = (
            f"{_MERCHANT}: Hi {name}, aapka {amount} ka payment fail ho gaya. "
            f"Yahan se retry karein: {payment_link}"
        )
        subject = f"{_MERCHANT}: aapka {amount} ka payment complete karein"
        text = (
            f"Hi {name},\n\n"
            f"Aapka {amount} ka payment complete nahi hua. Koi baat nahi — is link "
            f"se aap ise abhi retry kar sakte hain:\n{payment_link}\n\n"
            f"Kisi bhi madad ke liye reply karein.\n\n- {_MERCHANT}"
        )
    else:
        sms = (
            f"{_MERCHANT}: Hi {name}, your {amount} payment did not go through. "
            f"Retry it here: {payment_link}"
        )
        subject = f"{_MERCHANT}: complete your {amount} payment"
        text = (
            f"Hi {name},\n\n"
            f"Your {amount} payment did not complete. You can retry it now using "
            f"this link:\n{payment_link}\n\n"
            f"Reply to this email if you need any help.\n\n- {_MERCHANT}"
        )

    html = (
        f"<p>Hi {name},</p>"
        f"<p>Your <strong>{amount}</strong> payment did not complete. "
        f'You can retry it now: <a href="{payment_link}">{payment_link}</a>.</p>'
        f"<p>&mdash; {_MERCHANT}</p>"
    )
    return NudgeMessage(
        language=language,
        sms_body=sms,
        email_subject=subject,
        email_text=text,
        email_html=html,
    )
