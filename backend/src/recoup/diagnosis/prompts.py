"""The Tier-2 classification prompt (PRD §11.1, §11.3).

Tier 1 (the rules table) already resolves every unambiguous failure code, so this
prompt is only ever shown the long tail Tier 1 could not place. It asks for strict
JSON — ``{"cause", "confidence", "rationale"}`` — with ``cause`` constrained to the
six :class:`~recoup.domain.enums.Cause` values verbatim, and it makes ``unknown`` an
explicitly correct answer: PRD §11.3 requires that uncertainty never resolve into an
unbounded money move, so an honest "I don't know" is a success, not a failure.

The rationale is written for a human reading an audit row, because that is exactly
where it lands. The prompt is kept short — the free tier's 6,000 tokens-per-minute
budget is real — and carries two few-shot examples drawn from genuinely ambiguous
cases (not ones Tier 1 already catches) so the model calibrates on the real tail.
"""

from __future__ import annotations

from recoup.domain.enums import Cause
from recoup.domain.models import FailureContext

__all__ = ["SYSTEM_PROMPT", "build_messages"]

# The six allowed causes, listed verbatim from the enum so the prompt cannot drift
# from the code the answer is validated against.
_CAUSE_GUIDE = {
    Cause.INSUFFICIENT_FUNDS: "the instrument is valid but unfunded (retry near payday)",
    Cause.GATEWAY_DEGRADATION: "the route/acquirer is unhealthy, not the customer (backoff retry)",
    Cause.SOFT_DECLINE: "a transient issuer decline worth one short retry",
    Cause.EXPIRED_INSTRUMENT: "an expired card or lapsed mandate; only the customer can fix it",
    Cause.FRAUD_FLAGGED: "a fraud/risk block; no money action is permitted",
    Cause.UNKNOWN: "none of the above fits, or the evidence is genuinely ambiguous",
}

_CAUSE_LINES = "\n".join(f'- "{cause.value}": {desc}' for cause, desc in _CAUSE_GUIDE.items())

SYSTEM_PROMPT = f"""You classify why a single payment failed, for an automated \
revenue-recovery system. You are the second tier: a deterministic rules table has \
already handled every obvious failure code, so you only see ambiguous cases.

Reply with ONLY a JSON object of exactly this shape, and nothing else:
{{"cause": <one allowed value>, "confidence": <0.0-1.0>, "rationale": <one sentence>}}

The allowed cause values, and nothing else, are:
{_CAUSE_LINES}

Rules:
- Choose "unknown" when the evidence is genuinely ambiguous. An honest "unknown" is \
correct — the system falls back to a safe, human-reviewed path. Never guess a \
specific cause to look decisive.
- confidence is your calibrated certainty in the chosen cause, from 0.0 to 1.0.
- rationale is one plain sentence a human auditor can read, naming the signal you used.
- Never output anything except the JSON object."""

# Few-shot examples: genuinely ambiguous tails, not rules-table hits.
_FEW_SHOT: tuple[tuple[str, str], ...] = (
    (
        "failure_code=BAD_REQUEST_ERROR; failure_message=The transaction could not be "
        "completed due to a temporary problem at the bank, please try after some time; "
        "method=upi; issuer=SBIN; failure_type=one_time",
        '{"cause": "gateway_degradation", "confidence": 0.78, "rationale": "Message '
        'blames a temporary bank-side problem on the route, not the customer."}',
    ),
    (
        "failure_code=BAD_REQUEST_ERROR; failure_message=Payment stopped by customer's "
        "bank; contact your bank for details; method=card; issuer=HDFC; failure_type=subscription",
        '{"cause": "unknown", "confidence": 0.35, "rationale": "A generic issuer stop with '
        'no signal distinguishing a soft decline, a block, or a lapsed mandate."}',
    ),
)


def _render_context(ctx: FailureContext) -> str:
    """The failure, rendered compactly for the model — no customer or merchant data."""
    return (
        f"failure_code={ctx.failure_code}; "
        f"failure_message={ctx.failure_message}; "
        f"method={ctx.method or 'unknown'}; "
        f"issuer={ctx.issuer or 'unknown'}; "
        f"failure_type={ctx.failure_type.value}"
    )


def build_messages(ctx: FailureContext) -> list[dict[str, str]]:
    """The chat messages for classifying ``ctx``: system, few-shot pairs, then the case."""
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for user_example, assistant_example in _FEW_SHOT:
        messages.append({"role": "user", "content": user_example})
        messages.append({"role": "assistant", "content": assistant_example})
    messages.append({"role": "user", "content": _render_context(ctx)})
    return messages
