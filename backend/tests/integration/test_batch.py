"""End-to-end batch tests: the whole recovery loop, and honest metrics (PRD §13.4).

These are the proof that the milestone actually holds: 50 synthetic transactions
flow from raw webhook payloads through ingestion, diagnosis, policy, the constraint
gate, execution and the audit log to a set of terminal states, and the report read
back from the immutable trail is arithmetically honest — a genuine, non-perfect
recovery rate beside a populated, specifically-reasoned exception list.

The single most important test here is :func:`test_batch_is_not_perfect`: a 100%
recovery rate would mean the batch contained no genuinely unrecoverable
transactions, which is exactly the cherry-picking PRD §13.4 forbids.
"""

from __future__ import annotations

import dataclasses
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy import Engine

from recoup.batch.generator import (
    DEGRADED_ROUTE,
    OVER_CAP_AMOUNT_PAISE,
    SEEDED_SCENARIOS,
    build_gateway,
    generate_batch,
)
from recoup.batch.runner import BatchRunner
from recoup.clock import IST, SimulatedClock
from recoup.config import Settings
from recoup.domain.enums import Cause, State
from recoup.domain.models import ExecutionResult, WorkItem
from recoup.gateways.mock import MockGateway
from recoup.metrics import BatchReport, build_report
from recoup.runtime import RecoveryRuntime, build_recovery_runtime
from recoup.storage.audit import AuditLog
from recoup.storage.db import create_engine_for, init_schema
from recoup.storage.work_items import WorkItemRepo

_START = datetime(2026, 9, 4, 11, 0, 0, tzinfo=IST)
_N = 50
_SEED = 42


@dataclass
class _Run:
    """Everything a test needs to inspect one completed batch run."""

    report: BatchReport
    gateway: MockGateway
    executed: list[str]
    """The txn_id of every work item the executor was asked to execute, in order."""

    runtime: RecoveryRuntime
    clock: SimulatedClock


async def _run_batch(engine: Engine, *, n: int = _N, seed: int = _SEED) -> _Run:
    """Generate a batch, wire the runtime with an executor spy, and run it to completion."""
    clock = SimulatedClock(start=_START)
    payloads = generate_batch(n, seed=seed, clock=clock)
    gateway = build_gateway(clock, n=n, seed=seed)
    runtime = build_recovery_runtime(engine, clock, gateway)

    executed: list[str] = []
    original_execute = runtime.executor.execute

    async def spy_execute(gate_pass: object, item: WorkItem, action: object) -> ExecutionResult:
        executed.append(item.txn_id)
        return await original_execute(gate_pass, item, action)  # type: ignore[arg-type]

    runtime.executor.execute = spy_execute  # type: ignore[method-assign]

    runner = BatchRunner(
        runtime.ingestor,
        runtime.orchestrator,
        runtime.repo,
        runtime.audit,
        clock,
        runtime.breaker,
    )
    report = await runner.run(payloads, run_id="test-run")
    return _Run(report, gateway, executed, runtime, clock)


@contextmanager
def _fresh_engine() -> Iterator[Engine]:
    """A second private SQLite engine, for the reproducibility test's second run.

    Mirrors the conftest ``engine`` fixture (``tempfile`` rather than the machine's
    broken ``tmp_path``) so a test can run two fully independent batches."""
    with tempfile.TemporaryDirectory(prefix="recoup-batch-test-") as tmp_dir:
        db_path = f"{tmp_dir}/batch.db".replace("\\", "/")
        engine = create_engine_for(Settings(database_url=f"sqlite:///{db_path}"))
        init_schema(engine)
        try:
            yield engine
        finally:
            engine.dispose()


async def test_batch_of_50_reaches_terminal_state_for_every_item(engine: Engine) -> None:
    run = await _run_batch(engine)
    items = run.runtime.repo.list(limit=10_000)
    assert len(items) == _N
    stuck = [it.txn_id for it in items if it.state not in (State.RESOLVED, State.ESCALATED)]
    assert stuck == [], f"work items stuck mid-flight: {stuck}"


async def test_seeded_75000_txn_is_rejected_by_amount_cap_and_escalated(engine: Engine) -> None:
    run = await _run_batch(engine)
    over_cap_txn = SEEDED_SCENARIOS["over_cap"]

    item = run.runtime.repo.get(over_cap_txn)
    assert item is not None
    assert item.amount_paise == OVER_CAP_AMOUNT_PAISE
    assert item.state is State.ESCALATED

    rejection = next(
        (r for r in run.report.constraint_rejections if r.txn_id == over_cap_txn), None
    )
    assert rejection is not None
    assert rejection.rule_id == "amount_cap"
    assert "Rs 75,000" in rejection.reason and "Rs 50,000" in rejection.reason


async def test_fraud_flagged_txn_never_reaches_the_executor(engine: Engine) -> None:
    run = await _run_batch(engine)
    fraud_txn = SEEDED_SCENARIOS["fraud_flagged"]

    # The gate refuses a fraud-flagged action, so the executor is never invoked and
    # the gateway never sees a retry for it — proven on both spies at once.
    assert fraud_txn not in run.executed
    assert all(txn != fraud_txn for _, txn in run.gateway.calls)

    item = run.runtime.repo.get(fraud_txn)
    assert item is not None and item.state is State.ESCALATED


async def test_degraded_route_cluster_trips_the_breaker(engine: Engine) -> None:
    run = await _run_batch(engine)
    # The deliberately degraded route must appear in the breaker trips, tripped
    # (OPEN, or HALF_OPEN once its cooldown aged during the fast-forward).
    assert DEGRADED_ROUTE in run.report.breaker_trips
    assert run.report.breaker_trips[DEGRADED_ROUTE] in ("open", "half_open")

    # And the cluster's transactions did not recover: every one is an exception.
    cluster_exceptions = [
        exc for exc in run.report.exceptions if exc.cause is Cause.GATEWAY_DEGRADATION
    ]
    assert len(cluster_exceptions) >= 6


async def test_no_contact_item_appears_in_exceptions_with_a_specific_reason(
    engine: Engine,
) -> None:
    run = await _run_batch(engine)
    no_contact_txn = SEEDED_SCENARIOS["no_contact"]

    exc = next((e for e in run.report.exceptions if e.txn_id == no_contact_txn), None)
    assert exc is not None
    assert exc.final_state is State.ESCALATED
    # The reason must name *why* — the missing contact information — not a generic
    # "failed" (PRD §13.4).
    assert "no phone or email" in exc.reason.lower()


async def test_unknown_code_escalates_through_the_fallback(engine: Engine) -> None:
    run = await _run_batch(engine)
    unknown_txn = SEEDED_SCENARIOS["unknown_code"]

    exc = next((e for e in run.report.exceptions if e.txn_id == unknown_txn), None)
    assert exc is not None
    assert exc.cause is Cause.UNKNOWN
    assert run.report.diagnosis_sources.get("fallback", 0) >= 1


async def test_voice_candidate_nudge_settles_as_an_exception(engine: Engine) -> None:
    # A customer nudge collects no money at send time and, unlike a retry, is not
    # bounded by the retry cap. It must settle after one attempt as an honest
    # exception rather than looping forever (the nudge-loop fix).
    run = await _run_batch(engine)
    voice_txn = SEEDED_SCENARIOS["voice_candidate"]

    item = run.runtime.repo.get(voice_txn)
    assert item is not None and item.state is State.ESCALATED
    exc = next((e for e in run.report.exceptions if e.txn_id == voice_txn), None)
    assert exc is not None
    assert "nudge" in exc.reason.lower()


async def test_recovery_rate_equals_recovered_over_at_risk(engine: Engine) -> None:
    run = await _run_batch(engine)
    report = run.report

    # Recompute the rate independently from the raw totals; it must be exactly
    # recovered / at_risk, with nothing filtered out of the denominator.
    expected = report.total_recovered_paise / report.total_at_risk_paise
    assert report.recovery_rate == pytest.approx(expected)

    # And the recovered figure is the sum of exactly the resolved items' amounts.
    items = run.runtime.repo.list(limit=10_000)
    resolved_paise = sum(it.amount_paise for it in items if it.state is State.RESOLVED)
    at_risk_paise = sum(it.amount_paise for it in items)
    assert report.total_recovered_paise == resolved_paise
    assert report.total_at_risk_paise == at_risk_paise


async def test_batch_is_not_perfect(engine: Engine) -> None:
    # The load-bearing honesty test. A recovery rate of 100% (or 0%) or an empty
    # exception list would mean the synthetic batch is not a faithful mix of
    # recoverable and unrecoverable failures — the exact cherry-picking PRD §13.4
    # forbids. If this ever fails at 1.0, the fix is in the generator, never here.
    run = await _run_batch(engine)
    assert 0.0 < run.report.recovery_rate < 1.0
    assert len(run.report.exceptions) > 0


async def test_audit_log_has_a_row_for_every_transition_of_every_item(engine: Engine) -> None:
    run = await _run_batch(engine)
    items = run.runtime.repo.list(limit=10_000)

    for item in items:
        rows = run.runtime.audit.for_txn(item.txn_id)
        assert rows, f"{item.txn_id} has no audit trail"
        # The trail is a gap-free chain from the entry state to the item's final
        # state: the first row leaves DETECTED, each row picks up where the last
        # left off, and the last row lands on the item's current (terminal) state.
        assert rows[0].from_state is State.DETECTED
        for earlier, later in zip(rows, rows[1:], strict=False):
            assert later.from_state == earlier.to_state
        assert rows[-1].to_state == item.state


async def test_report_is_derived_from_the_audit_trail(engine: Engine) -> None:
    run = await _run_batch(engine)

    # Rebuild the report with a completely fresh reader over the same database. If
    # the numbers are truly derived from the immutable trail, the rebuild matches.
    fresh_repo = WorkItemRepo(engine)
    fresh_audit = AuditLog(engine)
    items = fresh_repo.list(limit=10_000)
    audit_by_txn = {it.txn_id: fresh_audit.for_txn(it.txn_id) for it in items}
    breaker_snapshot = {r: s.value for r, s in run.runtime.breaker.snapshot().items()}

    rebuilt = build_report(
        run.report.run_id,
        items,
        audit_by_txn,
        breaker_snapshot,
        started_at=run.report.started_at,
        finished_at=run.report.finished_at,
    )
    assert rebuilt == run.report


async def test_batch_is_reproducible_under_a_fixed_seed(engine: Engine) -> None:
    first = await _run_batch(engine)
    with _fresh_engine() as second_engine:
        second = await _run_batch(second_engine)

    # Same seed, same clock start -> identical reports. run_id is the only field a
    # caller sets, so normalise it and compare everything else, timestamps included
    # (the clock advances deterministically, so even finished_at matches).
    normalise = dataclasses.replace
    assert normalise(first.report, run_id="x") == normalise(second.report, run_id="x")


async def test_scheduled_retries_are_fast_forwarded(engine: Engine) -> None:
    # Insufficient-funds retries are scheduled days into the future (the salary
    # cycle). If the runner did not fast-forward the clock, they would stay parked
    # in SCHEDULED forever; that some recover proves the fast-forward works.
    run = await _run_batch(engine)
    insufficient = run.report.by_cause.get(Cause.INSUFFICIENT_FUNDS)
    assert insufficient is not None
    assert insufficient.recovered > 0

    items = run.runtime.repo.list(limit=10_000)
    assert not any(it.state is State.SCHEDULED for it in items)
