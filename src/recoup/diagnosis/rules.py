"""Tier-1 deterministic failure-code rules (PRD section 11.1).

Most PSP failure codes are unambiguous. Insufficient funds, an expired card, a
fraud flag from the issuer — these do not need a model to interpret; they need a
lookup table. This module is that table: fast, free, and — because every branch
here is enumerable and testable — provably deterministic, which is the property
:class:`~recoup.diagnosis.engine.DiagnosisEngine` relies on to skip the LLM
entirely for the cases that do not need it (PRD section 11.2).

Rule order is priority order, not documentation order. A single failure message
can carry more than one signal at once — "payment blocked for suspected fraud,
declined by risk engine" contains both a fraud signal and a soft-decline signal —
and when that happens the more specific, higher-stakes cause must win. A
misrouted fraud case is not a shrug; it is money moved past a block that should
have stopped it. Fraud is therefore matched before every other rule, and the
generic soft-decline rule — which matches on the broadest, most overlap-prone
terms ("declined", "authentication") — is matched last, so it can only ever catch
what nothing more specific already claimed.
"""

from __future__ import annotations

from dataclasses import dataclass

from recoup.domain.enums import Cause
from recoup.domain.models import Diagnosis, FailureContext

__all__ = ["Rule", "RulesTable"]


@dataclass(frozen=True)
class Rule:
    """One entry in the Tier-1 table: a set of failure signatures and the cause
    they deterministically mean."""

    codes: frozenset[str]
    """Exact ``failure_code`` values this rule matches, compared case-insensitively."""

    patterns: tuple[str, ...]
    """Lowercase substrings checked against the failure code and message when no
    exact code matched, also compared case-insensitively."""

    cause: Cause

    rationale: str
    """Why this signature means this cause. :meth:`RulesTable.match` folds the
    specific code or pattern that actually fired into this text before it reaches
    the audit log — a rationale that only ever repeats the same fixed sentence for
    every match proves nothing an auditor can check against the underlying data."""


_RULES: tuple[Rule, ...] = (
    # Fraud first: see the module docstring for why this must never be shadowed.
    Rule(
        codes=frozenset(
            {
                "payment_frozen",
                "fraud_detected",
                "BAD_REQUEST_PAYMENT_FRAUDULENT",
                "risk_declined",
            }
        ),
        patterns=("fraud", "risk", "blocked", "frozen", "stolen"),
        cause=Cause.FRAUD_FLAGGED,
        rationale=(
            "Failure code or message names a fraud, risk or account-freeze "
            "signal. No money action is permitted; escalate to a human."
        ),
    ),
    Rule(
        codes=frozenset(
            {
                "card_expired",
                "invalid_card",
                "BAD_REQUEST_CARD_EXPIRED",
                "mandate_revoked",
                "subscription_halted",
            }
        ),
        patterns=("expired", "mandate", "revoked", "card is no longer valid"),
        cause=Cause.EXPIRED_INSTRUMENT,
        rationale=(
            "The payment instrument or mandate is expired, revoked or halted. "
            "No retry can succeed; the customer must act."
        ),
    ),
    Rule(
        codes=frozenset(
            {
                "gateway_error",
                "GATEWAY_ERROR",
                "SERVER_ERROR",
                "BAD_REQUEST_PAYMENT_TIMED_OUT",
            }
        ),
        patterns=(
            "gateway",
            "timeout",
            "timed out",
            "unavailable",
            "try again later",
            "issuer down",
            "bank down",
        ),
        cause=Cause.GATEWAY_DEGRADATION,
        rationale=(
            "The route, not the customer, looks unhealthy. Retryable with "
            "exponential backoff behind a circuit breaker."
        ),
    ),
    Rule(
        codes=frozenset(
            {
                "insufficient_funds",
                "BAD_REQUEST_PAYMENT_FAILED_INSUFFICIENT_BALANCE",
            }
        ),
        patterns=("insufficient", "low balance", "not enough"),
        cause=Cause.INSUFFICIENT_FUNDS,
        rationale=(
            "The instrument is valid but currently unfunded. Retryable, with "
            "timing intelligence rather than an immediate retry."
        ),
    ),
    # Soft decline last: the broadest rule, so it only catches what nothing more
    # specific above already claimed.
    Rule(
        codes=frozenset(
            {
                "payment_failed",
                "authentication_failed",
                "do_not_honour",
                "do_not_honor",
                "issuer_declined",
            }
        ),
        patterns=("declined", "do not honour", "do not honor", "authentication"),
        cause=Cause.SOFT_DECLINE,
        rationale=(
            "A transient issuer decline with no more specific signal present. "
            "Retryable once, with a short backoff."
        ),
    ),
)
"""Priority-ordered. See the module docstring for why the order is load-bearing."""

_CODE_INDEX: dict[str, Rule] = {}
for _rule in _RULES:
    for _code in _rule.codes:
        # setdefault, not assignment: if a code ever appeared in two rules, the
        # earlier (higher-priority) rule keeps it rather than the later one
        # silently taking over.
        _CODE_INDEX.setdefault(_code.lower(), _rule)


class RulesTable:
    """The Tier-1 lookup: a known failure code or message needs no model."""

    def match(self, ctx: FailureContext) -> Diagnosis | None:
        """Exact code match first, then pattern match, in rule priority order.

        Returns a :class:`~recoup.domain.models.Diagnosis` with ``confidence=1.0``
        and ``source="rules"``, or ``None`` if nothing in the table recognises
        this failure — the caller escalates to Tier 2.
        """
        code = ctx.failure_code.strip().lower()
        message = ctx.failure_message.strip().lower()

        exact = _CODE_INDEX.get(code)
        if exact is not None:
            return self._diagnosis(exact, f"exact failure code {ctx.failure_code!r}")

        for rule in _RULES:
            for pattern in rule.patterns:
                if pattern in code or pattern in message:
                    return self._diagnosis(rule, f"the pattern {pattern!r}")

        return None

    @staticmethod
    def _diagnosis(rule: Rule, matched_on: str) -> Diagnosis:
        return Diagnosis(
            cause=rule.cause,
            confidence=1.0,
            rationale=f"{rule.rationale} Matched by {matched_on}.",
            source="rules",
        )
