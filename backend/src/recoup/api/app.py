"""The FastAPI application factory and its composition root (PRD §8.8, §9.5).

:func:`create_app` builds one :class:`AppContext` — the engine, a shared clock, the
event bus, the mode-selected gateway, the recovery runtime and the batch-run
registry — and mounts the webhook, REST and WebSocket routers against it. The
context is built eagerly (not only in the lifespan) so that an in-process test
driving the app through ``httpx.ASGITransport`` gets a fully wired service without
having to run the ASGI lifespan itself.

The service holds two runtimes over one database. The **live** runtime processes
webhooks and demo injections on real wall-clock time; a **batch** run builds its own
runtime around a :class:`~recoup.clock.SimulatedClock` it can fast-forward, sharing
the same engine, event bus and publisher so its frames stream to the dashboard like
any other. All database-mutating work is serialised behind one lock, so the single
SQLite file never sees two writers race.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine

from recoup.api.publisher import BusPublisher
from recoup.api.schemas import BatchMetricsOut
from recoup.batch.generator import build_gateway, generate_batch
from recoup.batch.runner import build_batch_runner
from recoup.clock import IST, SimulatedClock, SystemClock
from recoup.config import Settings
from recoup.diagnosis.factory import build_llm
from recoup.domain.enums import State
from recoup.events import EventBus
from recoup.gateways.base import PaymentGateway
from recoup.gateways.factory import build_gateway_for
from recoup.metrics import BatchReport
from recoup.runtime import RecoveryRuntime, build_recovery_runtime
from recoup.storage.audit import AuditLog
from recoup.storage.db import create_engine_for, init_schema
from recoup.storage.work_items import WorkItemRepo

__all__ = ["AppContext", "BatchRun", "create_app"]

_LOG = logging.getLogger("recoup.api")
_VERSION = "0.1.0"


@dataclass
class BatchRun:
    """The mutable state of one batch run, surfaced by ``GET /api/batch/{run_id}``."""

    run_id: str
    status: str
    size: int
    seed: int | None
    started_at: datetime
    processed: int = 0
    finished_at: datetime | None = None
    metrics: BatchMetricsOut | None = None


@dataclass
class AppContext:
    """Everything the routes need, wired once and shared for the app's lifetime."""

    settings: Settings
    engine: Engine
    clock: SystemClock
    bus: EventBus
    gateway: PaymentGateway
    publisher: BusPublisher
    runtime: RecoveryRuntime
    batch_runs: dict[str, BatchRun] = field(default_factory=dict)
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def run_batch(self, run_id: str, size: int, seed: int) -> None:
        """Run one batch to completion on its own simulated clock, then record it.

        Shares this context's engine, bus and publisher, so every transition the
        batch makes streams to connected dashboards; uses its own simulated clock and
        seeded gateway so it can fast-forward scheduled retries without warping live
        time. Serialised behind the write lock so it never races the webhook path.
        """
        run = self.batch_runs[run_id]
        sim_clock = SimulatedClock(start=self.clock.now())
        gateway = build_gateway(sim_clock, n=size, seed=seed)
        payloads = generate_batch(size, seed=seed, clock=sim_clock)

        def on_progress(done: int, total: int) -> None:
            run.processed = done
            counts = self.runtime.repo.count_by_state()
            self.bus.publish(
                "batch.progress",
                {
                    "run_id": run_id,
                    "processed": done,
                    "size": total,
                    "recovered": counts.get(State.RESOLVED, 0),
                    "escalated": counts.get(State.ESCALATED, 0),
                    "current_txn_id": None,
                },
            )

        try:
            async with self.write_lock:
                runner = build_batch_runner(
                    self.engine,
                    sim_clock,
                    gateway,
                    max_retries=self.settings.max_retries,
                    max_amount_paise=self.settings.max_amount_paise,
                    min_llm_confidence=self.settings.min_llm_confidence,
                    progress=on_progress,
                    sink=self.publisher,
                    llm=build_llm(self.settings, sim_clock),
                )
                report = await runner.run(payloads, run_id=run_id)
            run.status = "completed"
            run.processed = report.total_transactions
            run.finished_at = self.clock.now()
            run.metrics = batch_metrics_from_report(report)
        except Exception:  # noqa: BLE001 - a failed run is a recorded status, not a crash
            _LOG.exception("batch run %s failed", run_id)
            run.status = "failed"
            run.finished_at = self.clock.now()

        self.bus.publish("batch.completed", _batch_status_payload(run))


def batch_metrics_from_report(report: BatchReport) -> BatchMetricsOut:
    """Project the paise-weighted batch report onto the contract's count-based metrics.

    ``attempted`` is the number of actions actually executed (the sum of the report's
    per-channel counts); ``recovery_rate`` is ``recovered / attempted`` to two
    decimals, matching the live ``/api/metrics`` definition rather than the report's
    own paise-weighted rate.
    """
    attempted = sum(report.by_channel.values())
    recovery_rate = round(report.recovered_count / attempted, 2) if attempted else 0.0
    return BatchMetricsOut(
        total_failed=report.total_transactions,
        total_failed_paise=report.total_at_risk_paise,
        attempted=attempted,
        recovered=report.recovered_count,
        recovered_paise=report.total_recovered_paise,
        recovery_rate=recovery_rate,
        escalated=len(report.escalations),
        gate_rejections=len(report.constraint_rejections),
    )


def _batch_status_payload(run: BatchRun) -> dict[str, object]:
    """The ``GET /api/batch/{run_id}`` / ``batch.completed`` body for ``run``."""
    return {
        "run_id": run.run_id,
        "status": run.status,
        "size": run.size,
        "seed": run.seed,
        "processed": run.processed,
        "started_at": run.started_at.astimezone(IST).isoformat(),
        "finished_at": run.finished_at.astimezone(IST).isoformat() if run.finished_at else None,
        "metrics": run.metrics.model_dump(mode="json") if run.metrics is not None else None,
    }


def _build_context(settings: Settings) -> AppContext:
    engine = create_engine_for(settings)
    init_schema(engine)

    clock = SystemClock()
    bus = EventBus(clock)

    gateway = build_gateway_for(settings, clock)

    publisher = BusPublisher(bus, WorkItemRepo(engine), AuditLog(engine), clock)
    runtime = build_recovery_runtime(
        engine,
        clock,
        gateway,
        max_retries=settings.max_retries,
        max_amount_paise=settings.max_amount_paise,
        min_llm_confidence=settings.min_llm_confidence,
        webhook_secret=settings.razorpay_webhook_secret,
        sink=publisher,
        llm=build_llm(settings, clock),
        settings=settings,
    )
    return AppContext(
        settings=settings,
        engine=engine,
        clock=clock,
        bus=bus,
        gateway=gateway,
        publisher=publisher,
        runtime=runtime,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app with its composition context attached to ``app.state``."""
    resolved = settings or Settings()
    context = _build_context(resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            context.engine.dispose()

    app = FastAPI(
        title="Recoup",
        version=_VERSION,
        summary="Autonomous, money-safe revenue recovery for Razorpay merchants.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.ctx = context

    # Imported here rather than at module top to avoid a circular import: the routers
    # depend on this module's AppContext type.
    from recoup.api import routes, voice, webhooks, ws

    app.include_router(webhooks.router)
    app.include_router(routes.router)
    app.include_router(voice.router)
    app.include_router(ws.router)
    return app


def __getattr__(name: str) -> FastAPI:
    """Lazily build the module-level ``app`` for ``uvicorn recoup.api.app:app``.

    Defined as a module ``__getattr__`` (PEP 562) rather than a top-level
    ``app = create_app()`` so that merely importing this module — which the routers
    and the whole test suite do — never constructs an engine or touches a database.
    The application is built only when the attribute ``app`` is actually requested,
    which is what uvicorn does at startup.
    """
    if name == "app":
        return create_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
