"""Contact-aware recovery channel selection (PRD sections 8.7 and 13.1).

Once the policy has decided a customer needs to be nudged, *how* to reach them is
its own decision, not an afterthought. A Rs 50,000 lapsed mandate deserves a
human-sounding phone call before it ever falls back to a text message; a Rs 200
one-time checkout does not. PRD section 16.4 puts that hero call on stage
specifically because the fallback chain, not just the top channel, is what makes
the nudge resilient — SMS and email failures happen constantly (undelivered,
bounced, spam-filtered), and PRD section 13.1 requires that a failed nudge on one
channel still tries the next rather than being recorded as a dead end.

This module answers exactly one question — given this item's value and this
customer's known contact methods, what ordered chain of channels should be tried?
— and nothing about *why* a nudge was chosen belongs here; that is
:mod:`recoup.policy.selector`'s job.
"""

from __future__ import annotations

from recoup.domain.enums import Channel
from recoup.domain.models import WorkItem

__all__ = ["HIGH_VALUE_THRESHOLD_PAISE", "choose_channel_chain"]

HIGH_VALUE_THRESHOLD_PAISE = 500_000
"""Rs 5,000. At or above this amount, a lapsed mandate earns the voice channel."""


def _has_text(value: str | None) -> bool:
    """Whether an optional contact field carries a usable, non-blank value."""
    return bool((value or "").strip())


def choose_channel_chain(item: WorkItem) -> list[Channel]:
    """The ordered fallback chain to try for nudging ``item``'s customer.

    The chain is built from two independent signals:

    - **Value.** At or above :data:`HIGH_VALUE_THRESHOLD_PAISE`, with a phone on
      file, voice leads the chain — PRD section 16.4's hero-call path. Below the
      threshold, or with no phone, voice is never attempted.
    - **Reachability.** A channel that cannot reach this customer is never
      returned, regardless of value: :class:`~recoup.domain.enums.Channel.VOICE`
      and :class:`~recoup.domain.enums.Channel.SMS` require a phone number;
      :class:`~recoup.domain.enums.Channel.EMAIL` requires an email address.

    A customer with neither a phone nor an email produces an empty list. That is
    the correct, complete answer — not a bug to route around — because the
    dashboard and the escalation path (PRD section 13.2) both need to be able to
    tell "no viable channel" apart from "channel chosen but it failed."
    """
    has_phone = _has_text(item.customer.phone)
    has_email = _has_text(item.customer.email)
    high_value = item.amount_paise >= HIGH_VALUE_THRESHOLD_PAISE

    if high_value and has_phone:
        candidate = [Channel.VOICE, Channel.SMS, Channel.EMAIL]
    elif has_phone:
        candidate = [Channel.SMS, Channel.EMAIL]
    else:
        candidate = [Channel.EMAIL]

    def _reachable(channel: Channel) -> bool:
        if channel in (Channel.VOICE, Channel.SMS):
            return has_phone
        if channel is Channel.EMAIL:
            return has_email
        return True

    return [channel for channel in candidate if _reachable(channel)]
