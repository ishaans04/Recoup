"""The root-cause action selector: PRD section 10.3's policy table, executable.

This is where the product's central claim stops being rhetoric. Three failure
causes must produce three genuinely different :class:`~recoup.domain.models.Action`
objects — a scheduled retry, a customer nudge, a block — and this module is the
single place that decision is made. It decides **what** to do; it never decides
**whether** that is allowed. The constraint gate (phase 6) is the only authority
on that question, and this module does not check caps, does not block on its own
judgement beyond the policy table itself, and does not talk to a gateway, a phone
line or an inbox.

Two safety properties hold regardless of what the diagnosis says:

- A fraud-flagged transaction (``item.fraud_flag`` or
  :data:`~recoup.domain.enums.Cause.FRAUD_FLAGGED`) always yields
  :data:`~recoup.domain.enums.ActionType.NO_ACTION`. PRD sections 13.2 and 14 make
  this a hard block, not a suggestion.
- Uncertainty never resolves into a money action. A cause this table does not
  recognise (chiefly :data:`~recoup.domain.enums.Cause.UNKNOWN`) is escalated to a
  human, never guessed at.
"""

from __future__ import annotations

from recoup.clock import Clock
from recoup.domain.enums import ActionType, Cause, Channel
from recoup.domain.models import Action, Diagnosis, WorkItem
from recoup.policy.channel_policy import choose_channel_chain
from recoup.policy.timing import next_retry_at

__all__ = ["chain_for", "select_action"]

_RETRY_ACTION_TYPES = frozenset(
    {ActionType.SCHEDULED_RETRY, ActionType.BACKOFF_RETRY, ActionType.IMMEDIATE_RETRY}
)
"""Action types that carry a `scheduled_for`, computed via `next_retry_at`."""


def _with_diagnosis(item: WorkItem, diagnosis: Diagnosis) -> WorkItem:
    """A view of ``item`` carrying ``diagnosis``, for handing to channel_policy.

    ``select_action`` and ``chain_for`` both receive ``diagnosis`` as an explicit
    argument rather than trusting ``item.diagnosis`` — the orchestrator may call
    either before the diagnosis has been persisted onto the item's own field.
    :func:`~recoup.policy.channel_policy.choose_channel_chain` only takes a
    ``WorkItem``, so when the two disagree this hands it a copy with the field
    reconciled instead of asking that module to grow a second parameter it does
    not otherwise need.
    """
    if item.diagnosis == diagnosis:
        return item
    return item.model_copy(update={"diagnosis": diagnosis})


def _route(item: WorkItem, diagnosis: Diagnosis) -> tuple[ActionType, Channel, str]:
    """The action type, channel (or head-of-chain), and reason for ``diagnosis``.

    Factored out of :func:`select_action` so that :func:`chain_for` can ask the
    same question — "which channel does this cause route to?" — without needing a
    clock, since channel routing never depends on time.
    """
    cause = diagnosis.cause

    if item.fraud_flag or cause is Cause.FRAUD_FLAGGED:
        return (
            ActionType.NO_ACTION,
            Channel.HUMAN_QUEUE,
            f"fraud_flag={item.fraud_flag}, diagnosed cause={cause.value}: a "
            "fraud-flagged transaction is never acted on; blocked from every "
            "money action and routed to the human queue.",
        )

    if cause is Cause.INSUFFICIENT_FUNDS:
        return (
            ActionType.SCHEDULED_RETRY,
            Channel.PAYMENT_RETRY,
            "insufficient_funds: the instrument is valid but unfunded, so "
            "retrying now would only repeat the same failure; scheduling the "
            "retry for the next salary-cycle moment instead of 2am.",
        )

    if cause is Cause.GATEWAY_DEGRADATION:
        return (
            ActionType.BACKOFF_RETRY,
            Channel.PAYMENT_RETRY,
            "gateway_degradation: the route looks unhealthy, not the customer; "
            "retrying with exponential backoff rather than hammering a "
            "struggling endpoint.",
        )

    if cause is Cause.SOFT_DECLINE:
        if item.retry_count >= 1:
            return (
                ActionType.ESCALATE,
                Channel.HUMAN_QUEUE,
                f"soft_decline: already retried once (retry_count="
                f"{item.retry_count}); PRD section 10.3 makes a soft decline "
                "retryable only once, so a second one escalates to the human "
                "queue instead of retrying again.",
            )
        return (
            ActionType.IMMEDIATE_RETRY,
            Channel.PAYMENT_RETRY,
            "soft_decline: a transient issuer decline, worth exactly one short "
            "retry before this failure would otherwise repeat unchanged.",
        )

    if cause is Cause.EXPIRED_INSTRUMENT:
        chain = choose_channel_chain(_with_diagnosis(item, diagnosis))
        if not chain:
            return (
                ActionType.ESCALATE,
                Channel.HUMAN_QUEUE,
                "expired_instrument: no retry can succeed against an expired "
                "card or lapsed mandate, and the customer has no phone or "
                "email on file, so there is no channel left to nudge them on; "
                "escalating to the human queue with the missing contact "
                "information logged.",
            )
        return (
            ActionType.CUSTOMER_NUDGE,
            chain[0],
            "expired_instrument: no retry can succeed against an expired card "
            f"or lapsed mandate; nudging the customer to re-authenticate via "
            f"{chain[0].value}, the head of the {[c.value for c in chain]} "
            "fallback chain.",
        )

    # Cause.UNKNOWN, and any cause this policy table has not been extended to
    # handle, land here on purpose: uncertainty must never resolve into a money
    # action (PRD section 11.3), so the safe default is always the human queue.
    return (
        ActionType.ESCALATE,
        Channel.HUMAN_QUEUE,
        f"cause={cause.value}: neither tier of the diagnosis engine could "
        "resolve this to an actionable cause, so it is escalated to the human "
        "queue rather than guessed at.",
    )


def chain_for(item: WorkItem, diagnosis: Diagnosis) -> list[Channel]:
    """The full ordered channel chain to walk for this item and diagnosis.

    For :data:`~recoup.domain.enums.Cause.EXPIRED_INSTRUMENT` this is the
    contact- and value-aware nudge chain from
    :func:`~recoup.policy.channel_policy.choose_channel_chain` (voice/SMS/email,
    filtered to what the customer can actually receive). Every other cause routes
    to exactly one channel by policy — :data:`~recoup.domain.enums.Channel.PAYMENT_RETRY`
    for a retryable cause, :data:`~recoup.domain.enums.Channel.HUMAN_QUEUE` for a
    block or an escalation — so the chain is that single channel. Phase 13's
    router can call this unconditionally and walk whatever it returns, rather
    than special-casing which causes have a fallback chain at all.
    """
    if diagnosis.cause is Cause.EXPIRED_INSTRUMENT:
        return choose_channel_chain(_with_diagnosis(item, diagnosis))
    _, channel, _ = _route(item, diagnosis)
    return [channel]


def select_action(item: WorkItem, diagnosis: Diagnosis, *, clock: Clock) -> Action:
    """Propose the bounded intervention PRD section 10.3 maps ``diagnosis`` to.

    Implements the cause-to-action table exactly:

    | Cause                 | ActionType       | Channel                    |
    |-----------------------|------------------|-----------------------------|
    | insufficient_funds    | scheduled_retry  | payment_retry               |
    | gateway_degradation   | backoff_retry    | payment_retry               |
    | soft_decline           | immediate_retry  | payment_retry (once)        |
    | soft_decline (2nd+)   | escalate         | human_queue                 |
    | expired_instrument    | customer_nudge   | head of the fallback chain  |
    | expired_instrument, no contact | escalate | human_queue        |
    | fraud_flagged, or item.fraud_flag | no_action | human_queue      |
    | unknown / unrecognised | escalate         | human_queue                 |

    ``clock`` is only consulted for causes that schedule a retry; every other
    branch never reads the time, which keeps the escalate/block/nudge paths
    trivially deterministic in tests. ``attempt`` on the returned action is
    always ``item.retry_count`` — the number of attempts already made, not the
    one about to be made.
    """
    action_type, channel, reason = _route(item, diagnosis)

    scheduled_for = None
    if action_type in _RETRY_ACTION_TYPES:
        scheduled_for = next_retry_at(diagnosis.cause, item.retry_count, clock.now())

    return Action(
        type=action_type,
        channel=channel,
        scheduled_for=scheduled_for,
        attempt=item.retry_count,
        reason=reason,
    )
