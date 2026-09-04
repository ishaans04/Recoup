"""Tests for the nudge templates (PRD §8.7, §16.4)."""

from __future__ import annotations

from recoup.channels.templates import choose_language, render_nudge

_LINK = "https://rzp.io/i/abcd12"


def test_language_selection_follows_the_documented_rule() -> None:
    assert choose_language("+919876543210") == "hinglish"
    assert choose_language("+14155550123") == "english"
    assert choose_language(None) == "english"


def test_hinglish_renders_name_amount_and_link() -> None:
    msg = render_nudge(
        customer_name="Asha", amount_paise=7_500_000, payment_link=_LINK, phone="+919876543210"
    )
    assert msg.language == "hinglish"
    for fragment in ("Asha", "Rs 75,000", _LINK, "Recoup"):
        assert fragment in msg.sms_body
        assert fragment in msg.email_text


def test_english_renders_name_amount_and_link() -> None:
    msg = render_nudge(
        customer_name="John", amount_paise=120_500, payment_link=_LINK, phone="+14155550123"
    )
    assert msg.language == "english"
    for fragment in ("John", "Rs 1,205", _LINK):
        assert fragment in msg.sms_body


def test_sms_body_fits_one_gsm7_segment_for_a_representative_case() -> None:
    msg = render_nudge(
        customer_name="Asha", amount_paise=7_500_000, payment_link=_LINK, phone="+919876543210"
    )
    assert len(msg.sms_body) <= 160  # a single GSM-7 segment


def test_email_has_both_html_and_text_bodies() -> None:
    msg = render_nudge(
        customer_name="Asha", amount_paise=249900, payment_link=_LINK, phone="+919876543210"
    )
    assert _LINK in msg.email_html
    assert "<a" in msg.email_html
    assert _LINK in msg.email_text
