"""Tests for the two-tier diagnosis engine (PRD section 11).

The test that matters most in this file is
``test_known_code_resolved_by_rules_without_calling_llm``: it is the proof behind
the project's public claim that an unambiguous failure code never reaches the
model. Everything else here exists to make sure the two tiers compose correctly
and that uncertainty always collapses to a safe, auditable fallback rather than a
guess (PRD section 11.3).
"""

from __future__ import annotations

import pytest

from recoup.diagnosis.engine import DiagnosisEngine
from recoup.diagnosis.rules import RulesTable
from recoup.domain.enums import Cause, FailureType
from recoup.domain.models import Diagnosis, FailureContext
from tests.fakes import FakeLLM, make_work_item

# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _ctx(code: str, message: str, **overrides: object) -> FailureContext:
    """A minimal, valid FailureContext for exercising the rules table directly."""
    fields: dict[str, object] = {
        "failure_code": code,
        "failure_message": message,
        "failure_type": FailureType.SUBSCRIPTION,
        "amount_paise": 249_900,
        "method": "card",
        "issuer": "HDFC",
    }
    fields.update(overrides)
    return FailureContext(**fields)  # type: ignore[arg-type]


# Representative exact codes for each of PRD 5.1's five core failure classes.
EXACT_CODE_CASES = [
    pytest.param(
        "insufficient_funds",
        "Card has insufficient balance.",
        Cause.INSUFFICIENT_FUNDS,
        id="insufficient_funds",
    ),
    pytest.param(
        "gateway_error", "Upstream gateway failed.", Cause.GATEWAY_DEGRADATION, id="gateway_error"
    ),
    pytest.param(
        "card_expired", "The card on file has expired.", Cause.EXPIRED_INSTRUMENT, id="card_expired"
    ),
    pytest.param(
        "payment_frozen", "Account frozen pending review.", Cause.FRAUD_FLAGGED, id="payment_frozen"
    ),
    pytest.param(
        "payment_failed",
        "The issuer declined the payment.",
        Cause.SOFT_DECLINE,
        id="payment_failed",
    ),
]

# Representative pattern-only matches (the code itself is not in any exact set).
PATTERN_ONLY_CASES = [
    pytest.param(
        "XPAY_9001",
        "Card has low balance for this transaction.",
        Cause.INSUFFICIENT_FUNDS,
        id="pattern-low-balance",
    ),
    pytest.param(
        "XPAY_9002",
        "The request timed out talking to the acquirer.",
        Cause.GATEWAY_DEGRADATION,
        id="pattern-timed-out",
    ),
    pytest.param(
        "XPAY_9003",
        "This card is no longer valid for payments.",
        Cause.EXPIRED_INSTRUMENT,
        id="pattern-no-longer-valid",
    ),
    pytest.param(
        "XPAY_9004",
        "Transaction blocked pending fraud review.",
        Cause.FRAUD_FLAGGED,
        id="pattern-fraud-review",
    ),
    pytest.param(
        "XPAY_9005",
        "Payment declined by issuer, please retry later.",
        Cause.SOFT_DECLINE,
        id="pattern-declined",
    ),
]


# --------------------------------------------------------------------------- #
# Tier 1 — RulesTable
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("code,message,expected", EXACT_CODE_CASES)
def test_exact_code_maps_to_expected_cause(code: str, message: str, expected: Cause) -> None:
    diagnosis = RulesTable().match(_ctx(code, message))

    assert diagnosis is not None
    assert diagnosis.cause == expected
    assert diagnosis.confidence == 1.0
    assert diagnosis.source == "rules"
    assert diagnosis.rationale.strip() != ""


@pytest.mark.parametrize("code,message,expected", PATTERN_ONLY_CASES)
def test_pattern_only_message_maps_to_expected_cause(
    code: str, message: str, expected: Cause
) -> None:
    diagnosis = RulesTable().match(_ctx(code, message))

    assert diagnosis is not None
    assert diagnosis.cause == expected
    assert diagnosis.source == "rules"


def test_matching_is_case_insensitive_on_code() -> None:
    lower = RulesTable().match(_ctx("insufficient_funds", "unrelated message"))
    upper = RulesTable().match(_ctx("INSUFFICIENT_FUNDS", "unrelated message"))

    assert lower is not None
    assert upper is not None
    assert lower.cause == upper.cause == Cause.INSUFFICIENT_FUNDS


def test_matching_is_case_insensitive_on_pattern() -> None:
    diagnosis = RulesTable().match(_ctx("XPAY_UPPER", "INSUFFICIENT BALANCE ON CARD"))

    assert diagnosis is not None
    assert diagnosis.cause == Cause.INSUFFICIENT_FUNDS


def test_exact_code_match_beats_pattern_match() -> None:
    """``card_expired`` is an exact code for EXPIRED_INSTRUMENT. Its message here
    is deliberately stuffed with fraud-pattern words ("declined", "fraud",
    "blocked") that would win a pattern-only match. The exact code must still
    decide, proving the exact-code pass runs first and short-circuits before the
    message is ever pattern-matched."""
    diagnosis = RulesTable().match(
        _ctx("card_expired", "Payment declined - blocked due to suspected fraud by risk engine.")
    )

    assert diagnosis is not None
    assert diagnosis.cause == Cause.EXPIRED_INSTRUMENT


def test_fraud_pattern_is_never_shadowed_by_soft_decline() -> None:
    """A message carrying both a fraud signal and a soft-decline signal, with no
    exact code, must resolve to FRAUD_FLAGGED. A fraud case routed to
    SOFT_DECLINE would be retried instead of blocked and escalated — this is the
    rule-ordering property PRD section 11.1 depends on being genuinely true."""
    diagnosis = RulesTable().match(
        _ctx(
            "XPAY_UNRECOGNISED", "Payment declined - blocked due to suspected fraud by risk engine."
        )
    )

    assert diagnosis is not None
    assert diagnosis.cause == Cause.FRAUD_FLAGGED
    assert diagnosis.cause != Cause.SOFT_DECLINE


def test_no_match_returns_none() -> None:
    diagnosis = RulesTable().match(
        _ctx("XPAY_NEVER_SEEN", "A completely unrecognised failure occurred.")
    )

    assert diagnosis is None


def test_rationale_names_what_actually_matched() -> None:
    """The rationale is what an auditor reads; it must reflect the specific match,
    not a single sentence repeated for every failure that hits the same rule."""
    exact = RulesTable().match(_ctx("insufficient_funds", "unrelated"))
    pattern = RulesTable().match(_ctx("XPAY_1", "Card has low balance for this transaction."))

    assert exact is not None and "insufficient_funds" in exact.rationale
    assert pattern is not None and "low balance" in pattern.rationale


# --------------------------------------------------------------------------- #
# Two-tier engine — the single most important test in this phase
# --------------------------------------------------------------------------- #


async def test_known_code_resolved_by_rules_without_calling_llm() -> None:
    """PRD section 11.2's public claim: an unambiguous failure code is resolved
    by Tier 1 alone. This must be genuinely, provably true — asserted on the
    fake's call count, not inferred from the result alone."""
    llm = FakeLLM()
    engine = DiagnosisEngine(RulesTable(), llm)
    item = make_work_item(
        failure_code="insufficient_funds", failure_message="Card has insufficient balance."
    )

    diagnosis = await engine.diagnose(item)

    assert diagnosis.cause == Cause.INSUFFICIENT_FUNDS
    assert diagnosis.source == "rules"
    assert llm.call_count == 0
    assert engine.tier1_hits == 1
    assert engine.tier2_calls == 0


async def test_llm_none_still_diagnoses_known_codes() -> None:
    """No Groq key configured must not degrade Tier 1 at all."""
    engine = DiagnosisEngine(RulesTable(), llm=None)
    item = make_work_item(failure_code="card_expired", failure_message="Card expired.")

    diagnosis = await engine.diagnose(item)

    assert diagnosis.cause == Cause.EXPIRED_INSTRUMENT
    assert diagnosis.source == "rules"
    assert engine.tier1_hits == 1


async def test_llm_none_falls_back_for_unknown_codes() -> None:
    """The system must remain fully functional with an empty ``.env``: an
    unrecognised code with no LLM configured still produces a complete,
    specifically-reasoned diagnosis rather than crashing or hanging."""
    engine = DiagnosisEngine(RulesTable(), llm=None)
    item = make_work_item(
        failure_code="XPAY_UNRECOGNISED_1", failure_message="Something the table has never seen."
    )

    diagnosis = await engine.diagnose(item)

    assert diagnosis.cause == Cause.UNKNOWN
    assert diagnosis.source == "fallback"
    assert diagnosis.confidence == 0.0
    assert "XPAY_UNRECOGNISED_1" in diagnosis.rationale
    assert (
        "no llm" in diagnosis.rationale.lower() or "not configured" in diagnosis.rationale.lower()
    )
    assert engine.fallbacks == 1
    assert engine.tier1_hits == 0
    assert engine.tier2_calls == 0


async def test_unrecognised_code_escalates_to_llm_and_uses_confident_result() -> None:
    llm_result = Diagnosis(
        cause=Cause.GATEWAY_DEGRADATION,
        confidence=0.91,
        rationale="Model judged this a transient gateway issue from context clues.",
        source="llm",
    )
    llm = FakeLLM(result=llm_result)
    engine = DiagnosisEngine(RulesTable(), llm)
    item = make_work_item(
        failure_code="XPAY_UNRECOGNISED_2", failure_message="An unfamiliar upstream response."
    )

    diagnosis = await engine.diagnose(item)

    assert diagnosis == llm_result
    assert llm.call_count == 1
    assert engine.tier2_calls == 1
    assert engine.tier1_hits == 0
    assert engine.fallbacks == 0


async def test_low_confidence_llm_result_falls_back_with_specific_rationale() -> None:
    llm = FakeLLM(
        result=Diagnosis(
            cause=Cause.SOFT_DECLINE,
            confidence=0.42,
            rationale="Weak signal; issuer message was ambiguous.",
            source="llm",
        )
    )
    engine = DiagnosisEngine(RulesTable(), llm, min_confidence=0.7)
    item = make_work_item(
        failure_code="XPAY_UNRECOGNISED_3", failure_message="An ambiguous decline reason."
    )

    diagnosis = await engine.diagnose(item)

    assert diagnosis.cause == Cause.UNKNOWN
    assert diagnosis.source == "fallback"
    assert diagnosis.confidence == 0.42
    assert "0.42" in diagnosis.rationale
    assert "0.70" in diagnosis.rationale
    assert engine.fallbacks == 1


async def test_llm_returning_none_yields_fallback_not_exception() -> None:
    llm = FakeLLM(result=None)
    engine = DiagnosisEngine(RulesTable(), llm)
    item = make_work_item(
        failure_code="XPAY_UNRECOGNISED_4", failure_message="No structure the model could parse."
    )

    diagnosis = await engine.diagnose(item)

    assert diagnosis.cause == Cause.UNKNOWN
    assert diagnosis.source == "fallback"
    assert llm.call_count == 1
    assert engine.fallbacks == 1


async def test_llm_raising_still_yields_fallback() -> None:
    """LLMClient.classify is contractually forbidden from raising, but the engine
    must survive a non-compliant implementation rather than let one bad provider
    crash an entire batch (PRD section 13.1: degrade, never stop)."""
    llm = FakeLLM(raises=RuntimeError("provider connection reset"))
    engine = DiagnosisEngine(RulesTable(), llm)
    item = make_work_item(
        failure_code="XPAY_UNRECOGNISED_5", failure_message="Triggers a raise from the fake."
    )

    diagnosis = await engine.diagnose(item)

    assert diagnosis.cause == Cause.UNKNOWN
    assert diagnosis.source == "fallback"
    assert engine.fallbacks == 1
    assert engine.tier2_calls == 1


async def test_fraud_flag_on_work_item_overrides_code_and_skips_llm() -> None:
    llm = FakeLLM()
    engine = DiagnosisEngine(RulesTable(), llm)
    item = make_work_item(
        fraud_flag=True,
        failure_code="insufficient_funds",
        failure_message="Card has insufficient balance.",
    )

    diagnosis = await engine.diagnose(item)

    assert diagnosis.cause == Cause.FRAUD_FLAGGED
    assert diagnosis.source == "rules"
    assert llm.call_count == 0
    assert engine.tier1_hits == 1


@pytest.mark.parametrize(
    "build_engine_and_item",
    [
        lambda: (
            DiagnosisEngine(RulesTable(), FakeLLM()),
            make_work_item(failure_code="card_expired"),
        ),
        lambda: (
            DiagnosisEngine(RulesTable(), FakeLLM(result=None)),
            make_work_item(failure_code="XPAY_A", failure_message="obscure"),
        ),
        lambda: (
            DiagnosisEngine(RulesTable(), None),
            make_work_item(failure_code="XPAY_B", failure_message="obscure"),
        ),
        lambda: (
            DiagnosisEngine(RulesTable(), FakeLLM()),
            make_work_item(fraud_flag=True, failure_code="payment_failed"),
        ),
    ],
    ids=["rules-hit", "llm-none-result-fallback", "no-llm-configured-fallback", "fraud-override"],
)
async def test_every_diagnosis_path_carries_a_nonempty_rationale(build_engine_and_item) -> None:  # type: ignore[no-untyped-def]
    engine, item = build_engine_and_item()

    diagnosis = await engine.diagnose(item)

    assert diagnosis.rationale.strip() != ""


async def test_counters_increment_correctly_across_a_mixed_batch() -> None:
    llm = FakeLLM(
        results=[
            Diagnosis(
                cause=Cause.GATEWAY_DEGRADATION,
                confidence=0.9,
                rationale="Confident gateway read from context.",
                source="llm",
            ),
            Diagnosis(
                cause=Cause.SOFT_DECLINE,
                confidence=0.3,
                rationale="Weak signal, could not decide confidently.",
                source="llm",
            ),
        ]
    )
    engine = DiagnosisEngine(RulesTable(), llm)

    await engine.diagnose(make_work_item(failure_code="insufficient_funds"))
    await engine.diagnose(make_work_item(failure_code="card_expired"))
    await engine.diagnose(make_work_item(fraud_flag=True, failure_code="payment_failed"))
    await engine.diagnose(
        make_work_item(
            failure_code="XPAY_BATCH_1", failure_message="Unrecognised upstream text one."
        )
    )
    await engine.diagnose(
        make_work_item(
            failure_code="XPAY_BATCH_2", failure_message="Unrecognised upstream text two."
        )
    )

    assert engine.tier1_hits == 3
    assert engine.tier2_calls == 2
    assert engine.fallbacks == 1
    assert llm.call_count == 2
