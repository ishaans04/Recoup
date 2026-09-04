"""The REST surface (contract §3): work items, audit, metrics, escalations, batch, demo.

Every path, query parameter, field name and status code here is fixed by
`docs/interface-contract.md`. Responses are declared with the Phase-9 Pydantic
schemas so the OpenAPI document is exact and the dashboard's generated types cannot
silently drift from what the server actually returns.

The reads derive everything from storage; the two writes — starting a batch and
injecting a demo failure — go through the same ingestion and gate the real webhook
path does, so the guardrail moment on stage (PRD §16.5) is the real gate saying no,
never a shortcut.
"""

from __future__ import annotations

import asyncio
import copy
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from recoup.api.app import AppContext, BatchRun
from recoup.api.errors import error_response
from recoup.api.metrics_view import compute_escalations, compute_metrics
from recoup.api.processing import drive_until_settled
from recoup.api.schemas import (
    AuditEventOut,
    AuditStreamOut,
    BatchRunAcceptedOut,
    BatchRunRequest,
    BatchStatusOut,
    DemoInjectOut,
    DemoInjectRequest,
    EscalationsOut,
    HealthOut,
    MetricsOut,
    WorkItemAuditOut,
    WorkItemListOut,
    WorkItemOut,
)
from recoup.batch.generator import SEEDED_SCENARIOS, generate_batch
from recoup.clock import Clock
from recoup.domain.enums import Cause, State
from recoup.domain.models import WorkItem
from recoup.storage.work_items import encode_cursor

router = APIRouter(prefix="/api", tags=["api"])

__all__ = ["router"]

_SCAN_LIMIT = 100_000


def _ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


# --- Health ------------------------------------------------------------------


@router.get("/health", response_model=HealthOut)
def health(request: Request) -> HealthOut:
    ctx = _ctx(request)
    try:
        ctx.runtime.repo.count_by_state()
        database = "ok"
    except Exception:  # noqa: BLE001 - health reports a bad database rather than raising
        database = "error"
    return HealthOut(
        status="ok",
        mode=ctx.settings.recoup_mode,
        version="0.1.0",
        time=ctx.clock.now(),
        database=database,
        ws_connections=ctx.bus.subscriber_count,
    )


# --- Work items --------------------------------------------------------------


def _paginate(
    items: list[WorkItem], cursor: str | None, limit: int
) -> tuple[list[WorkItem], str | None]:
    """Client-side keyset pagination over an already-sorted (newest-first) list.

    The dataset is demo-scale, so filtering and paging in memory keeps repeatable
    ``state``/``cause`` filters consistent without pushing multi-value predicates
    into SQL. The cursor is the same opaque token the storage layer emits.
    """
    start = 0
    if cursor:
        for index, item in enumerate(items):
            if encode_cursor(item) == cursor:
                start = index + 1
                break
    page = items[start : start + limit]
    has_more = start + limit < len(items)
    next_cursor = encode_cursor(page[-1]) if (has_more and page) else None
    return page, next_cursor


@router.get("/workitems", response_model=WorkItemListOut)
def list_workitems(
    request: Request,
    state: Annotated[list[State] | None, Query()] = None,
    cause: Annotated[list[Cause] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> WorkItemListOut:
    ctx = _ctx(request)
    rows = ctx.runtime.repo.list(limit=_SCAN_LIMIT)

    state_set = set(state) if state else None
    cause_set = set(cause) if cause else None
    filtered = [
        item
        for item in rows
        if (state_set is None or item.state in state_set)
        and (
            cause_set is None or (item.diagnosis is not None and item.diagnosis.cause in cause_set)
        )
    ]

    page, next_cursor = _paginate(filtered, cursor, limit)
    return WorkItemListOut(
        items=[WorkItemOut.model_validate(item) for item in page],
        next_cursor=next_cursor,
        total=len(filtered),
    )


@router.get("/workitems/{txn_id}", response_model=WorkItemOut, responses={404: {}})
def get_workitem(request: Request, txn_id: str) -> WorkItemOut | JSONResponse:
    ctx = _ctx(request)
    item = ctx.runtime.repo.get(txn_id)
    if item is None:
        return error_response(
            404, "work_item_not_found", f"No work item exists with txn_id {txn_id}."
        )
    return WorkItemOut.model_validate(item)


@router.get("/workitems/{txn_id}/audit", response_model=WorkItemAuditOut, responses={404: {}})
def get_workitem_audit(request: Request, txn_id: str) -> WorkItemAuditOut | JSONResponse:
    ctx = _ctx(request)
    if ctx.runtime.repo.get(txn_id) is None:
        return error_response(
            404, "work_item_not_found", f"No work item exists with txn_id {txn_id}."
        )
    events = [AuditEventOut.model_validate(e) for e in ctx.runtime.audit.for_txn(txn_id)]
    return WorkItemAuditOut(txn_id=txn_id, events=events)


# --- Audit stream ------------------------------------------------------------


@router.get("/audit", response_model=AuditStreamOut)
def audit_stream(
    request: Request,
    since_id: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> AuditStreamOut:
    ctx = _ctx(request)
    rows = ctx.runtime.audit.list_since(since_id, limit=limit)
    events = [AuditEventOut.model_validate(e) for e in rows]
    last_id = events[-1].id if events else since_id
    return AuditStreamOut(events=events, last_id=last_id)


# --- Metrics and escalations -------------------------------------------------


@router.get("/metrics", response_model=MetricsOut)
def metrics(request: Request) -> MetricsOut:
    ctx = _ctx(request)
    return compute_metrics(ctx.runtime.repo, ctx.runtime.audit, ctx.clock)


@router.get("/escalations", response_model=EscalationsOut)
def escalations(request: Request) -> EscalationsOut:
    ctx = _ctx(request)
    entries = compute_escalations(ctx.runtime.repo, ctx.runtime.audit)
    return EscalationsOut(escalations=entries, total=len(entries))


# --- Batch -------------------------------------------------------------------


@router.post("/batch/run", status_code=202, response_model=BatchRunAcceptedOut)
async def run_batch(request: Request, body: BatchRunRequest) -> BatchRunAcceptedOut:
    ctx = _ctx(request)
    seed = body.seed if body.seed is not None else 42
    started_at = ctx.clock.now()
    run_id = f"run_{started_at:%Y%m%d%H%M%S}{len(ctx.batch_runs):04d}"
    ctx.batch_runs[run_id] = BatchRun(
        run_id=run_id, status="running", size=body.size, seed=seed, started_at=started_at
    )
    # Returns immediately; the run streams batch.progress and batch.completed itself.
    asyncio.create_task(ctx.run_batch(run_id, body.size, seed))
    return BatchRunAcceptedOut(
        run_id=run_id, size=body.size, seed=seed, status="running", started_at=started_at
    )


@router.get("/batch/{run_id}", response_model=BatchStatusOut, responses={404: {}})
def get_batch(request: Request, run_id: str) -> BatchStatusOut | JSONResponse:
    ctx = _ctx(request)
    run = ctx.batch_runs.get(run_id)
    if run is None:
        return error_response(404, "batch_run_not_found", f"No batch run with id {run_id}.")
    return BatchStatusOut(
        run_id=run.run_id,
        status=run.status,  # type: ignore[arg-type]  # one of running/completed/failed
        size=run.size,
        seed=run.seed,
        processed=run.processed,
        started_at=run.started_at,
        finished_at=run.finished_at,
        metrics=run.metrics,
    )


# --- Demo injection ----------------------------------------------------------


@router.post("/demo/inject", status_code=201, response_model=DemoInjectOut, responses={400: {}})
async def demo_inject(request: Request, body: DemoInjectRequest) -> DemoInjectOut | JSONResponse:
    ctx = _ctx(request)
    try:
        payload = _demo_payload(body, ctx.clock)
    except KeyError as exc:
        return error_response(400, "invalid_request", f"Unknown demo scenario: {exc}.")

    accepted_at = ctx.clock.now()
    async with ctx.write_lock:
        result = ctx.runtime.ingestor.ingest_payload(payload)
        await drive_until_settled(ctx.runtime.orchestrator, ctx.clock, result.item)

    return DemoInjectOut(
        txn_id=result.item.txn_id,
        event_id=result.item.event_id,
        state=State.DETECTED,
        accepted_at=accepted_at,
    )


def _demo_payload(body: DemoInjectRequest, clock: Clock) -> dict[str, Any]:
    """A Razorpay-shaped payload for a demo injection, with a fresh unique identity.

    A ``scenario`` name (default: the Rs 75,000 over-cap case) reuses that seeded
    scenario's shape; otherwise a custom failure is built from the request fields.
    Either way the ``event_id`` and ``txn_id`` are made unique per injection, so
    repeatedly hitting "Inject" on stage creates a fresh work item every time rather
    than deduplicating against the last one.
    """
    unique = clock.now().strftime("%Y%m%d%H%M%S%f")
    txn_id = f"pay_demo_{unique}"
    event_id = f"evt_demo_{unique}"

    if body.amount_paise is not None:
        customer = body.customer
        entity: dict[str, Any] = {
            "id": txn_id,
            "amount": body.amount_paise,
            "currency": "INR",
            "status": "failed",
            "method": body.method,
            "error_code": body.failure_code or "BAD_REQUEST_ERROR",
            "error_description": body.failure_message or "Payment failed.",
            "notes": {"customer_name": customer.name if customer else "Demo Customer"},
        }
        if body.issuer is not None:
            entity["card"] = {"issuer": body.issuer}
        if customer is not None and customer.phone:
            entity["contact"] = customer.phone
        if customer is not None and customer.email:
            entity["email"] = customer.email
        if body.fraud_flag:
            entity["fraud_flag"] = True
        return {
            "entity": "event",
            "account_id": "acc_MerchantDemo01",
            "event": "payment.failed",
            "contains": ["payment"],
            "id": event_id,
            "payload": {"payment": {"entity": entity}},
            "created_at": int(clock.now().timestamp()),
        }

    scenario = body.scenario or "over_cap"
    target_txn = SEEDED_SCENARIOS[scenario]  # KeyError -> 400 above
    payloads = generate_batch(50, seed=42, clock=clock)
    base = copy.deepcopy(next(p for p in payloads if _entity_id(p) == target_txn))
    base["id"] = event_id
    _set_entity_id(base, txn_id)
    return base


def _entity_key(payload: dict[str, Any]) -> str:
    return str(next(iter(payload["payload"])))


def _entity_id(payload: dict[str, Any]) -> str:
    entity_id: str = payload["payload"][_entity_key(payload)]["entity"]["id"]
    return entity_id


def _set_entity_id(payload: dict[str, Any], txn_id: str) -> None:
    payload["payload"][_entity_key(payload)]["entity"]["id"] = txn_id
