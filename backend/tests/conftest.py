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
from recoup.domain.enums import State
from recoup.domain.models import AuditEvent
from recoup.storage.db import create_engine_for, init_schema

CREATED_AT = datetime(2026, 9, 3, 14, 32, 5, tzinfo=IST)


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


__all__ = ["CREATED_AT", "make_audit_event"]
