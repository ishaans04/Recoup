"""Persistence: the SQLAlchemy schema, database-enforced audit-trail immutability,
the transactional unit of work, the append-only audit log, and the work-item
repository (PRD sections 8.6, 9.6 and 10).

Everything downstream — the state machine in Phase 2 onward — writes through
:class:`AuditLog` and :class:`WorkItemRepo` rather than touching a table directly,
so this package is the entire boundary between the domain model and the database.
"""

from recoup.storage.audit import AuditLog
from recoup.storage.db import create_engine_for, init_schema, unit_of_work
from recoup.storage.tables import AuditEventRow, Base, WorkItemRow
from recoup.storage.work_items import WorkItemRepo, encode_cursor

__all__ = [
    "AuditEventRow",
    "AuditLog",
    "Base",
    "WorkItemRepo",
    "WorkItemRow",
    "create_engine_for",
    "encode_cursor",
    "init_schema",
    "unit_of_work",
]
