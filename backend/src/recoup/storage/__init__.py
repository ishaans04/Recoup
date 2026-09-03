"""Persistence: the SQLAlchemy schema, database-enforced audit-trail immutability,
schema initialisation, the transactional unit of work, and the append-only audit
log (PRD sections 8.6, 9.6 and 10).

The work-item repository lands here next, built on the same
:func:`~recoup.storage.db.unit_of_work` primitive as :class:`~recoup.storage.audit.AuditLog`.
"""

from recoup.storage.audit import AuditLog
from recoup.storage.db import create_engine_for, init_schema, unit_of_work
from recoup.storage.tables import AuditEventRow, Base, WorkItemRow

__all__ = [
    "AuditEventRow",
    "AuditLog",
    "Base",
    "WorkItemRow",
    "create_engine_for",
    "init_schema",
    "unit_of_work",
]
