"""Persistence: the SQLAlchemy schema for the two persisted stores (PRD sections
8.6, 9.6 and 10).

This package grows through Phase 1 into the full boundary between the domain
model and the database: the append-only enforcement, the transactional unit of
work, the audit log, and the work-item repository all land here.
"""

from recoup.storage.tables import AuditEventRow, Base, WorkItemRow

__all__ = ["AuditEventRow", "Base", "WorkItemRow"]
