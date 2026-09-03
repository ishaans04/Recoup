"""Persistence: the SQLAlchemy schema, database-enforced audit-trail immutability,
and schema initialisation (PRD sections 8.6, 9.6 and 10).

This package grows through Phase 1 into the full boundary between the domain
model and the database: the transactional unit of work, the audit log, and the
work-item repository all land here next.
"""

from recoup.storage.db import create_engine_for, init_schema
from recoup.storage.tables import AuditEventRow, Base, WorkItemRow

__all__ = [
    "AuditEventRow",
    "Base",
    "WorkItemRow",
    "create_engine_for",
    "init_schema",
]
