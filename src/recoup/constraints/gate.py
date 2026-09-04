"""The constraint gate: the single door every money action passes through (PRD §12).

PRD §12.3's claim — "a single choke-point is the entire safety argument... with
exactly one gate, it's provable" — is made mechanical here, not merely organised.
Two mechanisms carry it:

1. :meth:`ConstraintGate.check` evaluates **every** rule (so the audit log records
   every reason, not just the first refusal) and mints a :class:`GatePass` *only*
   when all pass. The pass carries an HMAC token that only this method can compute,
   because only this object holds the signing secret.
2. :class:`~recoup.execution.executor.ActionExecutor` refuses to run without a pass
   whose token verifies. There is no path from "an action was proposed" to "a
   channel ran" that does not pass through :meth:`check` — and an AST test
   (``tests/architecture/test_single_door.py``) fails the build if a second path is
   ever introduced.

The secret is generated per process and never leaves this object — not through a
public attribute, ``repr``, or log line — so a pass cannot be forged from outside,
and a pass minted for one transaction or action cannot be replayed against another.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from recoup.clock import Clock
from recoup.constraints.rules import ConstraintRule, RuleVerdict
from recoup.domain.models import Action, WorkItem

__all__ = ["ConstraintGate", "GateBypassError", "GatePass", "GateVerdict"]


class GateBypassError(Exception):
    """Raised when an action reaches execution without a valid gate pass.

    A forged token, a token minted for a different transaction or a different
    action, or a token older than the gate's freshness window all raise this. It is
    never caught and turned into a soft failure — a bypass attempt is a bug or an
    attack, and either way the action must not run.
    """


@dataclass(frozen=True)
class GatePass:
    """Proof that a specific action, for a specific work item, passed every rule.

    Unforgeable outside the gate: ``token`` is an HMAC over the other three fields
    keyed by the gate's per-process secret. It is single-purpose — bound to one
    ``txn_id`` and one ``action_fingerprint`` — and short-lived, so it authorises
    exactly the action it was minted for and only for a brief window after.
    """

    txn_id: str
    action_fingerprint: str
    checked_at: datetime
    token: str


@dataclass(frozen=True)
class GateVerdict:
    """The result of running the gate over one proposed action.

    Carries every rule's verdict (not only the failing ones) so the audit log can
    show the whole check, and a :class:`GatePass` iff ``result == "PASS"``.
    """

    result: Literal["PASS", "FAIL"]
    reason: str
    failed_rule_ids: tuple[str, ...]
    verdicts: tuple[RuleVerdict, ...]
    gate_pass: GatePass | None = field(default=None)


def action_fingerprint(action: Action) -> str:
    """A stable digest of the parts of an action that authorise it to run.

    Type, channel, attempt and schedule together identify *what* would happen, so a
    pass minted for a nudge cannot authorise a retry, and a pass minted for attempt
    0 cannot authorise attempt 3. The reason string is excluded — it is prose for
    humans, not part of the action's identity.
    """
    scheduled = action.scheduled_for.isoformat() if action.scheduled_for is not None else "none"
    raw = f"{action.type.value}|{action.channel.value}|{action.attempt}|{scheduled}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ConstraintGate:
    """Runs the rule set and mints unforgeable passes. The only door for money actions."""

    def __init__(
        self,
        rules: Sequence[ConstraintRule],
        *,
        clock: Clock,
        secret: bytes | None = None,
        max_pass_age_seconds: int = 60,
    ) -> None:
        self._rules = tuple(rules)
        self._clock = clock
        # Per-process secret, generated if not supplied. Held privately: name-mangled
        # so it is not an ordinary attribute, and never rendered or logged.
        self.__secret = secret if secret is not None else secrets.token_bytes(32)
        self._max_pass_age_seconds = max_pass_age_seconds

    def check(self, action: Action, item: WorkItem) -> GateVerdict:
        """Evaluate every rule; mint a pass iff all pass.

        Every rule runs regardless of earlier failures, so ``verdicts`` is the full
        record and ``reason`` joins every failing rule's reason — the visible "no"
        PRD §12.4 wants shows all of its causes at once, not just the first.
        """
        verdicts = tuple(rule.evaluate(action, item) for rule in self._rules)
        failed = [v for v in verdicts if not v.passed]

        if failed:
            return GateVerdict(
                result="FAIL",
                reason="; ".join(v.reason for v in failed),
                failed_rule_ids=tuple(v.rule_id for v in failed),
                verdicts=verdicts,
                gate_pass=None,
            )

        checked_at = self._clock.now()
        fingerprint = action_fingerprint(action)
        gate_pass = GatePass(
            txn_id=item.txn_id,
            action_fingerprint=fingerprint,
            checked_at=checked_at,
            token=self._mint(item.txn_id, fingerprint, checked_at),
        )
        passed_reason = f"all {len(verdicts)} constraints passed"
        return GateVerdict(
            result="PASS",
            reason=passed_reason,
            failed_rule_ids=(),
            verdicts=verdicts,
            gate_pass=gate_pass,
        )

    def verify(self, gate_pass: GatePass, action: Action, item: WorkItem) -> None:
        """Raise :class:`GateBypassError` unless ``gate_pass`` genuinely authorises
        running ``action`` for ``item`` right now.

        Checks, in order: the token is this gate's HMAC over the pass's own fields
        (not forged); the pass was minted for this transaction; for this exact
        action; and within the freshness window (not replayed later).
        """
        expected = self._mint(gate_pass.txn_id, gate_pass.action_fingerprint, gate_pass.checked_at)
        if not hmac.compare_digest(expected, gate_pass.token):
            raise GateBypassError("gate pass token is invalid (forged or tampered)")
        if gate_pass.txn_id != item.txn_id:
            raise GateBypassError(f"gate pass was minted for {gate_pass.txn_id}, not {item.txn_id}")
        if gate_pass.action_fingerprint != action_fingerprint(action):
            raise GateBypassError("gate pass does not authorise this action")
        age = (self._clock.now() - gate_pass.checked_at).total_seconds()
        if age > self._max_pass_age_seconds or age < 0:
            raise GateBypassError(
                f"gate pass is stale ({age:.0f}s old, max {self._max_pass_age_seconds}s)"
            )

    def _mint(self, txn_id: str, fingerprint: str, checked_at: datetime) -> str:
        message = f"{txn_id}|{fingerprint}|{checked_at.isoformat()}".encode()
        return hmac.new(self.__secret, message, hashlib.sha256).hexdigest()
