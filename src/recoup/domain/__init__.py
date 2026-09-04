"""The shared domain vocabulary and models.

Everything in this package is imported by every other layer, so it depends on
nothing inside ``recoup`` itself. Keep it that way: a cycle here would make the
orchestrator, the gate and the audit log mutually inseparable.
"""

from recoup.domain.enums import (
    TERMINAL_STATES,
    ActionType,
    Cause,
    Channel,
    FailureType,
    State,
)
from recoup.domain.models import (
    Action,
    AuditEvent,
    ChannelResult,
    Confidence,
    Customer,
    Diagnosis,
    ExecutionResult,
    FailureContext,
    PaiseInt,
    RecoupModel,
    WorkItem,
)

__all__ = [
    "TERMINAL_STATES",
    "Action",
    "ActionType",
    "AuditEvent",
    "Cause",
    "Channel",
    "ChannelResult",
    "Confidence",
    "Customer",
    "Diagnosis",
    "ExecutionResult",
    "FailureContext",
    "FailureType",
    "PaiseInt",
    "RecoupModel",
    "State",
    "WorkItem",
]
