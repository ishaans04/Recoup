"""Tests for :mod:`recoup.policy.channel_policy`.

Channel selection is itself intelligence (PRD §8.7): a high-value lapsed mandate
earns a voice call at the head of the chain, a cheaper one does not, and a channel
the customer cannot receive is never offered. A customer with no contact at all
yields an empty chain — the correct, complete answer the escalation path depends
on (PRD §13.2).
"""

from recoup.domain.enums import Channel
from recoup.domain.models import Customer
from recoup.policy.channel_policy import HIGH_VALUE_THRESHOLD_PAISE, choose_channel_chain
from tests.conftest import make_work_item

_FULL_CONTACT = Customer(name="Ananya Rao", phone="+919876543210", email="ananya@example.com")
_PHONE_ONLY = Customer(name="Ravi Kumar", phone="+919812345678", email=None)
_EMAIL_ONLY = Customer(name="Meera Nair", phone=None, email="meera@example.com")
_NO_CONTACT = Customer(name="Unknown Customer", phone=None, email=None)


def test_high_value_expired_mandate_with_phone_leads_with_voice() -> None:
    item = make_work_item(amount_paise=600_000, customer=_FULL_CONTACT)
    assert choose_channel_chain(item) == [Channel.VOICE, Channel.SMS, Channel.EMAIL]


def test_below_threshold_drops_voice() -> None:
    item = make_work_item(amount_paise=200_000, customer=_FULL_CONTACT)
    assert choose_channel_chain(item) == [Channel.SMS, Channel.EMAIL]


def test_threshold_is_inclusive_on_the_high_side() -> None:
    at = make_work_item(amount_paise=HIGH_VALUE_THRESHOLD_PAISE, customer=_FULL_CONTACT)
    below = make_work_item(amount_paise=HIGH_VALUE_THRESHOLD_PAISE - 1, customer=_FULL_CONTACT)
    assert choose_channel_chain(at)[0] == Channel.VOICE
    assert choose_channel_chain(below)[0] == Channel.SMS


def test_phone_only_high_value_offers_voice_and_sms_but_not_email() -> None:
    item = make_work_item(amount_paise=600_000, customer=_PHONE_ONLY)
    assert choose_channel_chain(item) == [Channel.VOICE, Channel.SMS]


def test_email_only_offers_email_regardless_of_value() -> None:
    item = make_work_item(amount_paise=600_000, customer=_EMAIL_ONLY)
    assert choose_channel_chain(item) == [Channel.EMAIL]


def test_no_contact_yields_empty_chain() -> None:
    item = make_work_item(amount_paise=600_000, customer=_NO_CONTACT)
    assert choose_channel_chain(item) == []


def test_blank_contact_strings_count_as_no_contact() -> None:
    blanks = Customer(name="X", phone="   ", email="")
    item = make_work_item(amount_paise=600_000, customer=blanks)
    assert choose_channel_chain(item) == []
