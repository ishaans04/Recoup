"""Shared fixtures for the whole test suite.

The one property this fixture protects: **no test ever touches the developer's
real ``recoup.db``.** Every database-backed test gets its own SQLite file created
fresh and discarded with the test.
"""

import tempfile
from collections.abc import Iterator
from datetime import datetime

import pytest
from sqlalchemy import Engine

from recoup.clock import IST
from recoup.config import Settings
from recoup.domain.enums import FailureType, State
from recoup.domain.models import AuditEvent, Customer, WorkItem
from recoup.storage.db import create_engine_for, init_schema

CREATED_AT = datetime(2026, 9, 3, 14, 32, 5, tzinfo=IST)

_CREDENTIAL_ENV_VARS = (
    "GROQ_API_KEY",
    "RAZORPAY_KEY_ID",
    "RAZORPAY_KEY_SECRET",
    "RAZORPAY_WEBHOOK_SECRET",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "RESEND_API_KEY",
    "ELEVENLABS_API_KEY",
    "PUBLIC_BASE_URL",
    "USE_PREMIUM_VOICE",
    "RECOUP_MODE",
)


@pytest.fixture(autouse=True)
def _credential_free_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the whole suite with no real credentials — the single hard guarantee that
    testing never uses an API key or the Twilio phone number.

    Every test builds :class:`~recoup.config.Settings` with the ``.env`` file
    disabled and every credential environment variable cleared, so `Settings()`
    resolves to `mock` mode with no keys and the mock adapters fill in for every
    external service. Runs automatically before every test (autouse), ahead of the
    fixtures that construct settings, so a real `.env` on the developer's machine can
    never leak a live key into a test run.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for var in _CREDENTIAL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def engine() -> Iterator[Engine]:
    """A fresh, schema-initialised SQLite engine backed by a private temp file.

    Deliberately not pytest's built-in ``tmp_path``: that fixture provisions its
    scratch directories under a shared, numbered ``pytest-of-<user>`` tree that
    pytest itself manages the lifecycle of, and on this machine that tree has
    become unreadable/unwritable (a stale directory left with permissions this
    account can no longer touch — confirmed independently of this project, since
    even ``icacls`` on it fails with "Access is denied"). Using
    :func:`tempfile.TemporaryDirectory` instead asks Windows for an ordinary
    private temp directory directly, with no shared pytest-managed tree in the
    path, which sidesteps that machine-specific breakage entirely while keeping
    the same guarantee ``tmp_path`` would have given: a fresh directory per test,
    deleted when the test ends.

    A file rather than ``sqlite:///:memory:`` on purpose beyond that: this is
    exactly the engine :func:`~recoup.storage.db.create_engine_for` builds in
    production (same ``check_same_thread=False`` connect arg, same foreign-key
    pragma), and a file backing lets independent :class:`~sqlalchemy.orm.Session`
    objects behave like independent connections — which later transaction-isolation
    tests in this suite rely on. A shared ``:memory:`` database would need a
    ``StaticPool`` funnelling every session through one physical connection, which
    would make two "independent" sessions see each other's uncommitted writes.
    """
    with tempfile.TemporaryDirectory(prefix="recoup-test-") as tmp_dir:
        db_path = f"{tmp_dir}/recoup-test.db".replace("\\", "/")
        settings = Settings(database_url=f"sqlite:///{db_path}")
        test_engine = create_engine_for(settings)
        init_schema(test_engine)
        try:
            yield test_engine
        finally:
            test_engine.dispose()


def make_audit_event(**overrides: object) -> AuditEvent:
    """A realistic, insertable audit event; override only the field under test."""
    fields: dict[str, object] = {
        "timestamp": CREATED_AT,
        "txn_id": "pay_QjK9x2LmN4TzAb",
        "to_state": State.DETECTED,
        "rationale": "Webhook payment.failed accepted; work item created.",
    }
    fields.update(overrides)
    return AuditEvent(**fields)  # type: ignore[arg-type]


def make_work_item(**overrides: object) -> WorkItem:
    """A realistic work item; override only the field under test.

    Mirrors ``tests/unit/test_models.py``'s helper of the same name and the same
    fixture identifiers, so a row built here and one built there describe the same
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


__all__ = ["CREATED_AT", "make_audit_event", "make_work_item"]
