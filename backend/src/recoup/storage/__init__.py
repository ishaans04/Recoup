"""Persistence: the SQLAlchemy schema, database-enforced audit-trail immutability,
schema initialisation, and the transactional unit of work (PRD sections 8.6, 9.6
and 10).

This package grows through Phase 1 into the full boundary between the domain
model and the database: the audit log and the work-item repository land here
next, both built on :func:`~recoup.storage.db.unit_of_work`.
"""

from recoup.storage.db import create_engine_for, init_schema, unit_of_work
from recoup.storage.tables import AuditEventRow, Base, WorkItemRow

__all__ = [
    "AuditEventRow",
    "Base",
    "WorkItemRow",
    "create_engine_for",
    "init_schema",
    "unit_of_work",
]
