"""Engine construction, schema initialisation, and the transactional unit of work.

:func:`create_engine_for` centralises the one SQLite-specific connection tweak the
project needs, so it is set in exactly one place rather than at every call site
that happens to construct an engine.

:func:`init_schema` is what turns an empty database file into one with tables and
triggers. It is idempotent so the application, the test suite and a developer's
scratch script can all call it without coordinating who goes first.

:func:`unit_of_work` is the atomicity primitive the rest of the storage layer is
built on. PRD section 8.6's audit trail is only as trustworthy as the guarantee
that a work item never changes state without a matching audit row — and that
guarantee is real only if both writes commit, or neither does, as a single
database transaction. Phase 2's state machine wraps exactly one work-item
checkpoint and one audit append in a single call to this context manager.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from recoup.config import Settings
from recoup.storage.tables import Base

__all__ = ["create_engine_for", "init_schema", "unit_of_work"]


def create_engine_for(settings: Settings) -> Engine:
    """Build the :class:`~sqlalchemy.Engine` for ``settings.database_url``.

    For a SQLite URL, two things are set that a bare ``create_engine`` call would
    not do on its own:

    - ``check_same_thread=False``, because FastAPI's event loop and the batch
      runner both need to use the same engine from whatever thread they run on;
      pysqlite's default refuses a connection used outside the thread that opened
      it.
    - ``PRAGMA foreign_keys=ON`` on every new connection. SQLite ignores foreign
      key constraints unless this pragma is set per-connection — it is not a
      database-level setting — so it is attached to the engine's ``"connect"``
      event rather than left to whichever code happens to open first.

    Neither adjustment applies to a Postgres URL, which enforces foreign keys
    unconditionally and has no per-thread connection restriction; this function is
    a no-op beyond ``create_engine`` in that case.
    """
    is_sqlite = settings.database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(settings.database_url, connect_args=connect_args)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def init_schema(engine: Engine) -> None:
    """Create every table (and, for ``audit_events``, its triggers) if not present.

    ``checkfirst=True`` (the default for :meth:`~sqlalchemy.MetaData.create_all`)
    is what makes this idempotent: calling it against a database that already has
    the schema is a no-op rather than an error, so application startup, the test
    fixtures and a one-off admin script can all call it unconditionally.
    """
    Base.metadata.create_all(engine, checkfirst=True)


@contextmanager
def unit_of_work(engine: Engine) -> Iterator[Session]:
    """Yield a :class:`~sqlalchemy.orm.Session` scoped to a single transaction.

    Commits on a clean exit from the ``with`` block; rolls back and re-raises on
    any exception. Every write inside the block lands in one transaction, so a
    work-item checkpoint and its audit append either both persist or neither does
    — there is no state in which the audit trail is missing the row that explains
    a change that took effect.
    """
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
