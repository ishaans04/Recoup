"""The batch runner: the whole recovery loop, driven headlessly (PRD §5.1, §7.4).

This is where every layer built in Phases 0-7 runs together for the first time.
:func:`build_batch_runner` is the composition root — it wires the storage layer,
the diagnosis engine, the action selector, the constraint gate, the executor, the
mock gateway, the circuit breaker and the orchestrator into one object — and
:meth:`BatchRunner.run` drives a list of webhook payloads through it to a set of
terminal states, then derives an honest report from the audit trail.

Two design points carry the phase's guarantees:

**One clock, shared.** The :class:`~recoup.clock.SimulatedClock` is injected into
the gateway, the breaker, the retry-timing policy and this runner. A single
:meth:`~recoup.clock.SimulatedClock.advance` therefore moves time for all of them
at once, which is what lets the runner fast-forward a month to a salary-cycle retry
*and* age the breaker's cooldown in the same step. A runner that constructed its
own clock would desynchronise from the breaker and the schedule would never resolve.

**The report is read back from the log, not accumulated in memory.** Driving the
loop writes audit rows; the report is then rebuilt by reading those rows. Deriving
the numbers from the immutable trail is what makes them trustworthy (PRD §13.4) and
proves the trail is complete enough to reconstruct the entire run.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import Engine

from recoup.clock import SimulatedClock
from recoup.diagnosis.base import LLMClient
from recoup.domain.enums import State
from recoup.domain.models import AuditEvent, WorkItem
from recoup.events import EventSink
from recoup.fsm.orchestrator import Orchestrator
from recoup.gateways.base import PaymentGateway
from recoup.gateways.circuit_breaker import CircuitBreaker
from recoup.ingestion.idempotency import Ingestor
from recoup.metrics import BatchReport, build_report
from recoup.runtime import build_recovery_runtime
from recoup.storage.audit import AuditLog
from recoup.storage.work_items import WorkItemRepo

__all__ = ["BatchRunner", "build_batch_runner"]

ProgressCallback = Callable[[int, int], None]


class BatchRunner:
    """Drives ingested payloads through the recovery loop to terminal states."""

    _MAX_ROUNDS = 64
    """Fast-forward passes before the runner gives up. Each pass drives every live
    item to its next park or to terminal; a well-formed batch settles in a handful.
    The cap exists only so a routing bug surfaces as an unsettled item in the report
    rather than as a hang."""

    _MAX_STEPS_PER_ROUND = 16
    """Transitions one item may take within a single pass before it must park or
    settle. One retry cycle (execute -> re-choose -> re-gate -> re-park) is four
    transitions, so this bounds a single item's progress per fast-forward without
    ever cutting a legitimate cycle short."""

    def __init__(
        self,
        ingestor: Ingestor,
        orchestrator: Orchestrator,
        repo: WorkItemRepo,
        audit: AuditLog,
        clock: SimulatedClock,
        breaker: CircuitBreaker,
        progress: ProgressCallback | None = None,
    ) -> None:
        self._ingestor = ingestor
        self._orchestrator = orchestrator
        self._repo = repo
        self._audit = audit
        self._clock = clock
        self._breaker = breaker
        self._progress = progress

    async def run(
        self, payloads: list[dict[str, object]], *, run_id: str | None = None
    ) -> BatchReport:
        """Ingest every payload, drive each item to terminal, and report from the trail.

        ``run_id`` defaults to a timestamp derived from the clock, so a report is
        self-identifying even when the caller does not name the run.
        """
        started_at = self._clock.now()
        resolved_run_id = run_id or f"batch-{started_at.strftime('%Y%m%dT%H%M%S')}"

        order: list[str] = []
        current: dict[str, WorkItem] = {}
        for payload in payloads:
            result = self._ingestor.ingest_payload(payload)
            item = result.item
            # A duplicate event_id returns the already-stored item; dedupe the order
            # list too so a repeated payload is driven and reported exactly once.
            if item.txn_id not in current:
                order.append(item.txn_id)
            current[item.txn_id] = item

        total = len(order)
        self._emit_progress(0, total)

        settled = 0
        for _ in range(self._MAX_ROUNDS):
            earliest_parked: datetime | None = None
            all_terminal = True

            for txn_id in order:
                item = current[txn_id]
                if item.is_terminal:
                    continue
                item = await self._drive_until_parked_or_terminal(item)
                current[txn_id] = item
                if item.is_terminal:
                    continue
                all_terminal = False
                due = self._parked_until(item)
                if due is not None and (earliest_parked is None or due < earliest_parked):
                    earliest_parked = due

            settled = self._report_progress(order, current, settled, total)
            if all_terminal:
                break
            if earliest_parked is not None and self._clock.now() < earliest_parked:
                self._clock.advance(earliest_parked - self._clock.now())
            elif earliest_parked is None:
                # Nothing terminal, nothing parked to wait for: no fast-forward would
                # change anything, so stop and let the report surface the stuck items
                # rather than spinning to the round cap.
                break

        finished_at = self._clock.now()
        return self._report_from_trail(resolved_run_id, order, started_at, finished_at)

    async def _drive_until_parked_or_terminal(self, item: WorkItem) -> WorkItem:
        """Advance one item until it is terminal or parked in a not-yet-due SCHEDULED.

        Not :meth:`~recoup.fsm.orchestrator.Orchestrator.run_to_completion`: that
        method treats a SCHEDULED item whose time has not arrived as non-convergence
        and would raise, whereas parking-then-fast-forwarding is exactly the
        behaviour PRD §11.4 requires. So the runner drives one transition at a time
        and hands parked items back to :meth:`run` to fast-forward.
        """
        state_item = item
        for _ in range(self._MAX_STEPS_PER_ROUND):
            if state_item.is_terminal:
                return state_item
            if self._parked_until(state_item) is not None:
                return state_item
            state_item = await self._orchestrator.advance(state_item)
        return state_item

    def _parked_until(self, item: WorkItem) -> datetime | None:
        """The future time ``item`` is parked until, or ``None`` if it is not parked.

        A work item is parked only when it is in SCHEDULED with a ``scheduled_for``
        still ahead of the clock; a SCHEDULED item whose time has arrived is due,
        not parked, and must be advanced rather than waited on.
        """
        if item.state is not State.SCHEDULED:
            return None
        action = item.action
        if action is None or action.scheduled_for is None:
            return None
        if self._clock.now() < action.scheduled_for:
            return action.scheduled_for
        return None

    def _report_progress(
        self, order: list[str], current: dict[str, WorkItem], settled: int, total: int
    ) -> int:
        """Emit a progress tick if the settled count grew; return the new count."""
        now_settled = sum(1 for txn_id in order if current[txn_id].is_terminal)
        if now_settled != settled:
            self._emit_progress(now_settled, total)
        return now_settled

    def _emit_progress(self, done: int, total: int) -> None:
        if self._progress is not None:
            self._progress(done, total)

    def _report_from_trail(
        self, run_id: str, order: list[str], started_at: datetime, finished_at: datetime
    ) -> BatchReport:
        """Rebuild the report by reading work items and audit rows back from storage."""
        work_items: list[WorkItem] = []
        audit_by_txn: dict[str, list[AuditEvent]] = {}
        for txn_id in order:
            stored = self._repo.get(txn_id)
            if stored is None:  # pragma: no cover - an ingested item is always stored
                continue
            work_items.append(stored)
            audit_by_txn[txn_id] = self._audit.for_txn(txn_id)

        breaker_snapshot = {
            route: status.value for route, status in self._breaker.snapshot().items()
        }
        return build_report(
            run_id,
            work_items,
            audit_by_txn,
            breaker_snapshot,
            started_at=started_at,
            finished_at=finished_at,
        )


def build_batch_runner(
    engine: Engine,
    clock: SimulatedClock,
    gateway: PaymentGateway,
    *,
    max_retries: int = 3,
    max_amount_paise: int = 5_000_000,
    min_llm_confidence: float = 0.7,
    progress: ProgressCallback | None = None,
    sink: EventSink | None = None,
    llm: LLMClient | None = None,
) -> BatchRunner:
    """Compose the whole recovery stack around one engine, clock and gateway.

    The same wiring Phase 9's API will need, kept in one place. The circuit breaker
    is shared between the constraint gate (which asks whether a route is open) and
    the retry channel (which records outcomes against it), and the clock is shared
    with the gateway, the breaker and the retry-timing policy — sharing those two
    instances is what makes the breaker a closed loop and the fast-forward coherent.

    ``llm`` is deliberately ``None`` here: Phase 8 runs on the rules tier alone, so
    the batch is fully functional with an empty ``.env`` (Phase 11 injects Groq).
    """
    runtime = build_recovery_runtime(
        engine,
        clock,
        gateway,
        max_retries=max_retries,
        max_amount_paise=max_amount_paise,
        min_llm_confidence=min_llm_confidence,
        sink=sink,
        llm=llm,
    )
    return BatchRunner(
        runtime.ingestor,
        runtime.orchestrator,
        runtime.repo,
        runtime.audit,
        clock,
        runtime.breaker,
        progress,
    )
