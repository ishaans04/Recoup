"""Test doubles shared across the test suite.

Currently: a configurable double for :class:`~recoup.diagnosis.base.LLMClient`
and a factory for a realistic :class:`~recoup.domain.models.WorkItem`, so tests
in this phase and later ones build valid work items without repeating the same
field boilerplate.
"""

from __future__ import annotations

from datetime import datetime

from recoup.clock import IST
from recoup.diagnosis.base import LLMClient
from recoup.domain.enums import FailureType
from recoup.domain.models import Customer, Diagnosis, FailureContext, WorkItem

__all__ = ["CREATED_AT", "FakeLLM", "make_work_item"]

CREATED_AT = datetime(2026, 9, 3, 14, 32, 5, tzinfo=IST)


class FakeLLM:
    """A configurable :class:`~recoup.diagnosis.base.LLMClient` double.

    Configure at most one of ``result`` (a fixed :class:`Diagnosis`, or ``None``,
    returned on every call — including a deliberately low-confidence one),
    ``results`` (a list returned one per call in order, for a mixed batch where
    successive Tier-2 calls should get different verdicts; once exhausted, further
    calls return ``None``), or ``raises`` (an exception raised on every call, to
    prove :class:`~recoup.diagnosis.engine.DiagnosisEngine` survives a provider
    that violates the "never raises" contract). With none set, every call returns
    ``None`` — the "the model produced nothing usable" case.

    Records ``call_count`` and the :class:`FailureContext` each call received, so
    a test can assert both how many times Tier 2 was reached and, when it
    matters, what it was actually asked to classify.
    """

    def __init__(
        self,
        result: Diagnosis | None = None,
        raises: Exception | None = None,
        *,
        results: list[Diagnosis | None] | None = None,
    ) -> None:
        if results is not None and result is not None:
            raise ValueError("configure at most one of result or results")
        self._result = result
        self._results = list(results) if results is not None else None
        self._raises = raises
        self.call_count = 0
        self.received: list[FailureContext] = []

    async def classify(self, ctx: FailureContext) -> Diagnosis | None:
        self.call_count += 1
        self.received.append(ctx)
        if self._raises is not None:
            raise self._raises
        if self._results is not None:
            return self._results.pop(0) if self._results else None
        return self._result


# A static assertion, at import time, that FakeLLM actually satisfies the
# protocol it is meant to stand in for — a signature drift here would otherwise
# only surface as a confusing mypy error deep inside a test.
_: type[LLMClient] = FakeLLM


def make_work_item(**overrides: object) -> WorkItem:
    """A realistic work item; override only the field under test.

    Mirrors ``tests/conftest.py``'s helper of the same name (which in turn
    mirrors ``tests/unit/test_models.py``'s) and the same fixture identifiers, so
    a work item built here and one built in another test module describe the same
    kind of transaction.
    """
    fields: dict[str, object] = {
        "txn_id": "pay_QjK9x2LmN4TzAb",
        "event_id": "evt_8fH2kQpR7sVdWx",
        "merchant_id": "acc_MerchantDemo01",
        "amount_paise": 249900,
        "failure_code": "BAD_REQUEST_ERROR",
        "failure_message": "Your card has insufficient balance to complete this payment.",
        "failure_type": FailureType.SUBSCRIPTION,
        "method": "card",
        "issuer": "HDFC",
        "customer": Customer(
            name="Ananya Rao", phone="+919876543210", email="ananya.rao@example.com"
        ),
        "created_at": CREATED_AT,
    }
    fields.update(overrides)
    return WorkItem(**fields)  # type: ignore[arg-type]
