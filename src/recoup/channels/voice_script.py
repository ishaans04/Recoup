"""The recovery call script, as structured data (PRD §16.4, §9.7).

Kept as a dataclass rather than inline strings so it is reviewable and testable in
one place. The call identifies the merchant and its purpose in the first sentence,
states the amount in lakh-grouped rupees, and offers a keypress choice — never a
recorded pressure tactic. Hinglish is the default for Indian numbers; English is the
same-rule fallback.

The core Hinglish line from PRD §16.4 —
*"Sir, aapka payment fail ho gaya hai, link bhejoon retry karne ke liye?"* — is used
only where a title is actually known. With no form of address given, a respectful
gender-neutral opening is used instead, because assuming "Sir"/"Ma'am" wrongly is
its own small disrespect.
"""

from __future__ import annotations

from dataclasses import dataclass

from recoup.channels.templates import choose_language
from recoup.money import format_inr_paise

__all__ = ["VoiceScript", "build_script"]

_MERCHANT = "Recoup"


@dataclass(frozen=True)
class VoiceScript:
    """One rendered call script: the opening, the keypress prompt, and each outcome line."""

    language: str
    opening: str
    gather_prompt: str
    no_input: str
    decline: str
    confirm_sms: str

    @property
    def intro(self) -> str:
        """The full spoken lead-in before the keypad gather."""
        return f"{self.opening} {self.gather_prompt}"


def build_script(
    *, customer_name: str, amount_paise: int, phone: str | None, title: str | None = None
) -> VoiceScript:
    """Render the call script for ``phone``'s language, carrying the amount."""
    amount = format_inr_paise(amount_paise)
    name = customer_name.strip() or "there"
    language = choose_language(phone)

    if language == "hinglish":
        if title:
            opening = (
                f"Namaste {title}, {_MERCHANT} se. Aapka {amount} ka payment fail ho "
                f"gaya hai. Link bhejoon retry karne ke liye?"
            )
        else:
            opening = (
                f"Namaste, {_MERCHANT} se. {name} ji, aapka {amount} ka payment fail "
                f"ho gaya hai. Hum aapko retry ke liye ek link bhej sakte hain."
            )
        gather_prompt = "Link SMS par paane ke liye ek dabaiye. Nahi chahiye to do dabaiye."
        no_input = "Koi input nahi mila. Baad mein aapko link SMS kar denge. Dhanyavaad."
        decline = "Theek hai, koi baat nahi. Dhanyavaad."
        confirm_sms = (
            "Bahut badhiya. Payment link aapke phone par SMS kar diya gaya hai. Dhanyavaad."
        )
    else:
        opening = (
            f"Hello {name}, this is {_MERCHANT}. Your {amount} payment did not go "
            f"through. We can send you a link to retry it."
        )
        gather_prompt = "Press 1 to get the link by SMS. Press 2 if you do not want it."
        no_input = "We did not receive any input. We will text you the link shortly. Thank you."
        decline = "No problem at all. Thank you."
        confirm_sms = "Great. The payment link has been sent to your phone by SMS. Thank you."

    return VoiceScript(
        language=language,
        opening=opening,
        gather_prompt=gather_prompt,
        no_input=no_input,
        decline=decline,
        confirm_sms=confirm_sms,
    )
