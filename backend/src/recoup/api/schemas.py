"""Pydantic request/response models mirroring the frozen interface contract.

`docs/interface-contract.md` is the boundary between this backend and the Next.js
dashboard, frozen since Phase 0. These models *are* that contract expressed in
code: FastAPI derives the OpenAPI schema from them, so Phase 10 generates its
TypeScript types straight from a running server and a drift between the two halves
breaks the frontend build rather than the demo.

Two contract rules are enforced here rather than left to callers:

**Every timestamp is Asia/Kolkata (+05:30).** The storage layer round-trips
datetimes through UTC, so a work item read back carries a ``+00:00`` offset. The
:data:`IstDatetime` type re-expresses every outbound datetime in IST at
serialisation time, so the wire always shows ``+05:30`` as the contract promises,
without the storage layer having to lie about what it stored.

**Money is integer paise, never a float.** Every monetary field is an ``int`` named
``*_paise``; the single float in the whole contract is ``recovery_rate``, which is a
ratio, not money.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from recoup.clock import IST
from recoup.domain.enums import ActionType, Cause, Channel, FailureType, State

__all__ = [
    "ActionOut",
    "AuditEventOut",
    "AuditStreamOut",
    "BatchMetricsOut",
    "BatchRunAcceptedOut",
    "BatchRunRequest",
    "BatchStatusOut",
    "ByCauseOut",
    "ByChannelOut",
    "CustomerIn",
    "CustomerOut",
    "DemoInjectRequest",
    "DemoInjectOut",
    "DiagnosisOut",
    "ErrorBody",
    "ErrorOut",
    "EscalationOut",
    "EscalationsOut",
    "HealthOut",
    "MetricsOut",
    "WebhookAcceptedOut",
    "WorkItemAuditOut",
    "WorkItemListOut",
    "WorkItemOut",
]

IstDatetime = Annotated[
    datetime,
    PlainSerializer(lambda d: d.astimezone(IST).isoformat(), return_type=str, when_used="json"),
]
"""A datetime re-expressed in Asia/Kolkata on the way out, so the wire is always +05:30."""


class _Contract(BaseModel):
    """Base for contract models: populate from ORM/domain attributes, reject extras."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")


# --- Shared object shapes (contract §2) --------------------------------------


class CustomerOut(_Contract):
    name: str
    phone: str | None = None
    email: str | None = None


class DiagnosisOut(_Contract):
    cause: Cause
    confidence: float
    rationale: str
    source: Literal["rules", "llm", "fallback"]


class ActionOut(_Contract):
    type: ActionType
    channel: Channel
    scheduled_for: IstDatetime | None = None
    attempt: int
    reason: str


class WorkItemOut(_Contract):
    txn_id: str
    event_id: str
    merchant_id: str
    amount_paise: int
    currency: Literal["INR"]
    failure_code: str
    failure_message: str
    failure_type: FailureType
    method: str | None = None
    issuer: str | None = None
    customer: CustomerOut
    fraud_flag: bool
    created_at: IstDatetime
    state: State
    retry_count: int
    diagnosis: DiagnosisOut | None = None
    action: ActionOut | None = None


class AuditEventOut(_Contract):
    id: int
    timestamp: IstDatetime
    txn_id: str
    from_state: State | None = None
    to_state: State
    diagnosis_cause: Cause | None = None
    diagnosis_confidence: float | None = None
    action_chosen: ActionType | None = None
    constraint_result: Literal["PASS", "FAIL"] | None = None
    constraint_reason: str | None = None
    outcome: str | None = None
    rationale: str


class ErrorBody(_Contract):
    code: str
    message: str
    detail: str | None = None


class ErrorOut(_Contract):
    error: ErrorBody


# --- REST responses (contract §3) --------------------------------------------


class HealthOut(_Contract):
    status: Literal["ok"]
    mode: Literal["mock", "live"]
    version: str
    time: IstDatetime
    database: str
    ws_connections: int


class WorkItemListOut(_Contract):
    items: list[WorkItemOut]
    next_cursor: str | None = None
    total: int


class WorkItemAuditOut(_Contract):
    txn_id: str
    events: list[AuditEventOut]


class AuditStreamOut(_Contract):
    events: list[AuditEventOut]
    last_id: int


class ByCauseOut(_Contract):
    cause: Cause
    count: int
    recovered: int
    recovered_paise: int


class ByChannelOut(_Contract):
    channel: Channel
    attempted: int
    recovered: int
    recovered_paise: int


class MetricsOut(_Contract):
    total_failed: int
    total_failed_paise: int
    attempted: int
    recovered: int
    recovered_paise: int
    recovery_rate: float
    escalated: int
    gate_rejections: int
    in_flight: int
    by_cause: list[ByCauseOut]
    by_channel: list[ByChannelOut]
    generated_at: IstDatetime


class EscalationOut(_Contract):
    txn_id: str
    merchant_id: str
    amount_paise: int
    customer_name: str
    cause: Cause | None = None
    reason: str
    constraint_result: Literal["PASS", "FAIL"] | None = None
    escalated_at: IstDatetime
    retry_count: int


class EscalationsOut(_Contract):
    escalations: list[EscalationOut]
    total: int


class BatchMetricsOut(_Contract):
    total_failed: int
    total_failed_paise: int
    attempted: int
    recovered: int
    recovered_paise: int
    recovery_rate: float
    escalated: int
    gate_rejections: int


class BatchRunAcceptedOut(_Contract):
    run_id: str
    size: int
    seed: int | None = None
    status: Literal["running", "completed", "failed"]
    started_at: IstDatetime


class BatchStatusOut(_Contract):
    run_id: str
    status: Literal["running", "completed", "failed"]
    size: int
    seed: int | None = None
    processed: int
    started_at: IstDatetime
    finished_at: IstDatetime | None = None
    metrics: BatchMetricsOut | None = None


class DemoInjectOut(_Contract):
    txn_id: str
    event_id: str
    state: State
    accepted_at: IstDatetime


class WebhookAcceptedOut(_Contract):
    accepted: bool
    txn_id: str | None = None
    duplicate: bool


# --- Request bodies ----------------------------------------------------------


class BatchRunRequest(_Contract):
    size: int = Field(default=50, ge=1, le=500)
    seed: int | None = None


class CustomerIn(_Contract):
    name: str
    phone: str | None = None
    email: str | None = None


class DemoInjectRequest(_Contract):
    scenario: str | None = None
    """A name from ``SEEDED_SCENARIOS`` (default: the Rs 75,000 over-cap case). When
    given, the other fields are ignored and the named scenario is injected."""

    amount_paise: int | None = Field(default=None, ge=0)
    failure_code: str | None = None
    failure_message: str | None = None
    failure_type: FailureType = FailureType.ONE_TIME
    method: str | None = None
    issuer: str | None = None
    fraud_flag: bool = False
    customer: CustomerIn | None = None
