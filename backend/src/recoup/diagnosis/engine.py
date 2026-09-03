"""The two-tier diagnosis engine (PRD sections 11.1 and 11.3).

:class:`DiagnosisEngine` is the composition the rest of the system calls: Tier 1
(:class:`~recoup.diagnosis.rules.RulesTable`) first, Tier 2
(:class:`~recoup.diagnosis.base.LLMClient`) only for what Tier 1 could not place,
and a safe fallback whenever neither tier produced something worth acting on.

PRD section 11.3 is emphatic that uncertainty must never resolve into an
unbounded money move: a missing LLM, a failed classification and a low-confidence
classification all collapse to the same thing here — ``Cause.UNKNOWN`` with
``source="fallback"`` — which Phase 5's policy and Phase 6's gate route to the
safest bounded action or straight to a human. This module never guesses a cause
to keep a batch moving.
"""

from __future__ import annotations

from recoup.diagnosis.base import LLMClient
from recoup.diagnosis.rules import RulesTable
from recoup.domain.enums import Cause
from recoup.domain.models import Diagnosis, FailureContext, WorkItem

__all__ = ["DiagnosisEngine"]


class DiagnosisEngine:
    """Rules first, LLM second, a safe fallback always available.

    Exposes three running counters — :attr:`tier1_hits`, :attr:`tier2_calls` and
    :attr:`fallbacks` — so a batch run can report how often the LLM was actually
    needed. That number is itself a pitch point (PRD section 11.2): the fewer Tier
    2 calls a batch needed, the stronger the claim that most failures do not
    require a model to interpret.
    """

    def __init__(
        self,
        rules: RulesTable,
        llm: LLMClient | None,
        min_confidence: float = 0.7,
    ) -> None:
        """Compose the two tiers.

        ``llm`` is ``None`` when no provider credential is configured (PRD section
        13.1 / :attr:`~recoup.config.Settings.groq_api_key`) — the engine must
        still produce a complete diagnosis for every known code and a safe
        fallback for everything else, so the whole system is functional with an
        empty ``.env``.
        """
        self._rules = rules
        self._llm = llm
        self._min_confidence = min_confidence
        self.tier1_hits = 0
        """Diagnoses decided without calling the LLM: a rules-table match, or the
        fraud short-circuit below. The number Phase 8's batch report shows off."""

        self.tier2_calls = 0
        """How many times the LLM was actually invoked."""

        self.fallbacks = 0
        """Diagnoses that resolved to ``Cause.UNKNOWN`` because neither tier could
        decide confidently."""

    async def diagnose(self, item: WorkItem) -> Diagnosis:
        """Diagnose one work item.

        Order, exactly (PRD sections 11.1 and 11.3):

        1. A fraud flag already known on the work item wins outright, before any
           code is even looked at — a hard block should not depend on the PSP
           having also sent a fraud-shaped failure code.
        2. Tier 1: the rules table. A match returns immediately; the LLM is never
           called. This is the property PRD section 11.2 is built to prove — an
           ``insufficient_funds`` code does not need a model — so it must be
           genuinely true, not merely likely, which is why it is asserted on the
           fake's call count in the test suite rather than only on the result.
        3. Tier 2: the LLM, only reached when Tier 1 found nothing and a client is
           configured.
        4. Safe fallback: no LLM configured, no result, an exception from the
           client, or a confidence below ``min_confidence`` — every one of these
           becomes ``Cause.UNKNOWN`` with a rationale specific enough to explain
           why, never a bare "unknown".
        """
        if item.fraud_flag:
            self.tier1_hits += 1
            return Diagnosis(
                cause=Cause.FRAUD_FLAGGED,
                confidence=1.0,
                rationale=(
                    "Work item carries a fraud flag set by the PSP or merchant; "
                    "that overrides the failure code and any Tier-2 judgement — "
                    "a known fraud signal is never re-litigated by a model."
                ),
                source="rules",
            )

        ctx = self._context_for(item)

        ruled = self._rules.match(ctx)
        if ruled is not None:
            self.tier1_hits += 1
            return ruled

        llm = self._llm
        if llm is None:
            self.fallbacks += 1
            return self._fallback(
                confidence=0.0,
                reason=(
                    f"No rule matched failure code {item.failure_code!r} and no "
                    "LLM is configured (no Groq API key set)."
                ),
            )

        self.tier2_calls += 1
        diagnosis = await self._classify_safely(llm, ctx)

        if diagnosis is None:
            self.fallbacks += 1
            return self._fallback(
                confidence=0.0,
                reason=(
                    f"No rule matched failure code {item.failure_code!r}, and "
                    "the Tier-2 LLM returned no usable diagnosis."
                ),
            )

        if diagnosis.confidence < self._min_confidence:
            self.fallbacks += 1
            return self._fallback(
                confidence=diagnosis.confidence,
                reason=(
                    f"LLM confidence {diagnosis.confidence:.2f} is below the "
                    f"{self._min_confidence:.2f} threshold required to act on it."
                ),
            )

        return diagnosis

    @staticmethod
    async def _classify_safely(llm: LLMClient, ctx: FailureContext) -> Diagnosis | None:
        """Call the LLM, treating an unexpected raise the same as a ``None``.

        :class:`~recoup.diagnosis.base.LLMClient` is contractually forbidden from
        raising — every failure mode is defined to collapse to ``None`` inside the
        implementation itself. This ``try`` is a defense-in-depth backstop on top
        of that contract, not a relaxation of it: PRD section 13.1 requires the
        system to degrade rather than stop when an external service misbehaves,
        and one non-compliant provider must not be able to take an entire batch
        down with it. Phase 11's Groq client must still satisfy the contract on
        its own terms; this only guarantees the engine survives if it ever does not.
        """
        try:
            return await llm.classify(ctx)
        except Exception:
            return None

    @staticmethod
    def _context_for(item: WorkItem) -> FailureContext:
        """Narrow a :class:`WorkItem` to the :class:`FailureContext` Tier 1 and
        Tier 2 both consume — no customer, no merchant, no identifiers, so
        personal data never reaches the rules table or an LLM prompt."""
        return FailureContext(
            failure_code=item.failure_code,
            failure_message=item.failure_message,
            method=item.method,
            issuer=item.issuer,
            failure_type=item.failure_type,
            amount_paise=item.amount_paise,
        )

    @staticmethod
    def _fallback(confidence: float, reason: str) -> Diagnosis:
        return Diagnosis(
            cause=Cause.UNKNOWN,
            confidence=confidence,
            rationale=reason,
            source="fallback",
        )
