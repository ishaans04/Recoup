# Changelog

All notable changes to **Recoup** are recorded here, phase by phase.

This file is the drift check: every phase entry states what was built and which
[prd.md](prd.md) sections it satisfies. If a phase entry cannot cite a PRD section,
the work was out of scope.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project is pre-release; versions are phase numbers.

---

## [Unreleased]

### Phase 0 — Project foundation & domain vocabulary
_Status: complete_

Satisfies PRD §9 (stack), §10.1 (WorkItem), §10.2 (AuditEvent), §9.4 (frozen
Next.js ↔ FastAPI contract), §17 (first-hour tasks).

Phase 0 produces no business behaviour. It produces the toolchain, the shared
vocabulary and every cross-layer interface the remaining phases build against.

#### Added

- `docs/interface-contract.md` — **frozen**. Every REST path, the WebSocket
  envelope and resume protocol, and a concrete JSON example for each payload.
  Endpoint paths, field names, enum values and the envelope do not change;
  additive changes are appended in the commit that introduces them.
- `docs/plans/implementation-plan.md` — the phase-by-phase build plan.
- `backend/` — `uv` package `recoup`, `src/` layout, Python 3.13. ruff
  (E, F, I, UP, B, SIM, line length 100), mypy strict over `src/recoup`, pytest
  in asyncio auto mode.
- `recoup.domain.enums` — `State`, `Cause`, `ActionType`, `Channel`,
  `FailureType`, `TERMINAL_STATES`. These strings are contract: they are written
  verbatim into the audit log and rendered verbatim by the dashboard.
- `recoup.domain.models` — `WorkItem`, `AuditEvent`, `Diagnosis`, `Action`,
  `Customer`, `FailureContext`, `ChannelResult`, `ExecutionResult`. Money is
  strict non-negative integer paise; datetimes must be timezone-aware;
  `rationale` is non-empty on both `Diagnosis` and `AuditEvent`.
- `recoup.clock` — `Clock` protocol, `SystemClock`, `SimulatedClock`. Nothing in
  the codebase calls `datetime.now()` directly, so salary-cycle retries (§11.4)
  and breaker cooldowns (§13.1) are testable and demonstrable.
- `recoup.config` — `Settings`. Every credential optional; the application boots
  and the suite passes with an empty `.env`. `RECOUP_MODE` defaults to `mock`.
  Caps default to `max_retries=3`, `max_amount_paise=5_000_000`,
  `min_llm_confidence=0.7` (§12.2, §11.3).
- Cross-layer protocols: `gateways.base.PaymentGateway` + `GatewayTxn`,
  `channels.base.RecoveryChannel` + a complete `ChannelRegistry`,
  `diagnosis.base.LLMClient`, `constraints.base.BreakerState` + `NullBreaker`.
- `frontend/` — Next.js 16 App Router, TypeScript, Tailwind v4. Dark console
  shell with a link light that polls `GET /api/health`, and
  `src/lib/types.ts`, a hand-written mirror of the frozen contract.
- `.env.example` — every key, annotated with the phase that needs it.
- `.gitattributes` — LF normalisation.
- 143 unit tests in `backend/tests/unit/`.

#### Decisions

- `ExecutionResult` and `ChannelResult` are kept as distinct types despite having
  the same shape today. A channel reports delivery and recovery separately; the
  executor reports a whole gated, recorded attempt and names the channel used.
- `tzdata` added as a runtime dependency: Windows and slim Linux images ship no
  IANA time zone database, so `ZoneInfo("Asia/Kolkata")` raises without it.
- `FailureContext.route` normalises case and whitespace, so `card:HDFC` and
  `card:hdfc` are one circuit-breaker route rather than two.
- The frontend loads no web font and does not follow `prefers-color-scheme`.

---

### Phase 1 — Persistence & the physically append-only audit trail
_Status: complete_

Satisfies PRD §8.6 (audit trail), §9.6 (audit store), §10.1 (`WorkItem`
persistence), §10.2 (`AuditEvent` persistence), §14 (full auditability, no
duplicate money actions).

Phase 1 makes §8.6's claim — "append-only. Never updated, never deleted — only
inserted" — mechanically true rather than a coding convention: the database
itself refuses an `UPDATE` or a `DELETE` on `audit_events`, and a test issues
both directly in SQL and watches them fail.

#### Added

- `recoup.storage.tables` — SQLAlchemy 2.0 declarative tables `work_items` and
  `audit_events`, using only column types Postgres and SQLite share
  (`String`, `JSON`, `DateTime(timezone=True)`, `Boolean`, `Integer`,
  `BigInteger`) so `database_url` is the entire production migration (§9.6).
  `work_items.event_id` carries a database `UNIQUE` constraint — the
  idempotency guarantee of §8.1/§13.2 enforced by the schema, not only by
  application code. `state` and `created_at` are indexed for the dashboard's
  filter and default ordering; `audit_events.txn_id` is indexed for
  per-transaction lookup, and its `id` primary key already serves as the
  ascending index the `since_id` WebSocket cursor needs.
- `UTCDateTime` — a `TypeDecorator` wrapping `DateTime(timezone=True)` that
  normalises to UTC on write and reattaches UTC on read. Needed because
  pysqlite silently drops the offset on the way out; without it a work item's
  `created_at` round-trips naive from SQLite and is rejected by `WorkItem`'s
  own aware-datetime validator — a difference between the two dialects §9.6
  promises does not exist.
- Append-only enforcement: two SQLite triggers (`audit_events_no_update`,
  `audit_events_no_delete`) that `RAISE(ABORT, 'audit_events is append-only')`,
  attached via `sqlalchemy.event.listen(AuditEventRow.__table__,
  "after_create", DDL(...))` so they exist the instant the table does. The
  Postgres equivalent — a `plpgsql` trigger function plus a `REVOKE UPDATE,
  DELETE ... FROM PUBLIC` — is written to the same contract and guarded to the
  `postgresql` dialect; this project has no Postgres instance to run it
  against, so it is exercised by review, not by the test suite.
- `recoup.storage.db` — `create_engine_for(settings)` (SQLite gets
  `check_same_thread=False` plus a per-connection `PRAGMA foreign_keys=ON`),
  `init_schema(engine)` (idempotent `create_all`), and
  `unit_of_work(engine)` — a context manager yielding one transactional
  `Session`: commits on a clean exit, rolls back and re-raises on any
  exception. This is the atomicity primitive behind §8.6's completeness
  claim — Phase 2's state machine wraps one work-item checkpoint and one
  audit append in a single call, so a state change can never persist without
  the row that explains it.
- `recoup.storage.audit.AuditLog` — the only writer to `audit_events`.
  `append(event, session=None) -> int` returns the assigned id, joining a
  caller-supplied session's transaction or opening its own; `list_since(since_id,
  limit=100) -> list[AuditEvent]` powers the WebSocket backfill; `for_txn(txn_id)
  -> list[AuditEvent]` is the per-transaction history the dashboard renders. The
  class exposes no `update` or `delete` method — a test introspects it to prove
  that, not just assert it.
- `recoup.storage.work_items.WorkItemRepo` — `create_if_absent(item,
  session=None) -> tuple[WorkItem, bool]`, idempotent on `event_id` by
  attempting the insert inside a `SAVEPOINT` and re-reading on a unique-constraint
  violation rather than checking-then-inserting, so it is correct under
  concurrent duplicate deliveries (§8.1, §13.2); `get(txn_id) -> WorkItem |
  None`; `save(item, session=None) -> WorkItem`, a full checkpoint of every
  mutable field; `list(state=, cause=, limit=50, cursor=None) -> list[WorkItem]`,
  keyset-paginated on `(created_at, txn_id)` newest first so a page cannot
  skip or repeat rows under concurrent inserts, the way an `OFFSET` page
  would; `count_by_state() -> dict[State, int]` for the Phase 10 dashboard.
- 34 new unit tests in `backend/tests/unit/` (`test_audit_immutability.py`,
  `test_audit_log.py`, `test_work_items.py`, `test_unit_of_work.py`), plus a
  shared `backend/tests/conftest.py` engine fixture — 177 unit tests total.

#### Decisions

- The `engine` fixture uses `tempfile.TemporaryDirectory` rather than
  pytest's built-in `tmp_path`. On this development machine,
  `tmp_path`'s shared `%TEMP%\pytest-of-<user>` tree has become
  unreadable/unwritable by this account (confirmed independently of this
  project — even `icacls` on it fails with "Access is denied"), so every
  `tmp_path`-based test errored at fixture setup. A private temp directory
  requested directly sidesteps that machine-specific breakage while keeping
  the same guarantee: a fresh directory per test, discarded with it.
- The SQLite engine backing each test is file-based, not `sqlite:///:memory:`.
  A shared in-memory database needs a `StaticPool` funnelling every session
  through one physical connection, which would make two "independent"
  sessions see each other's uncommitted writes and falsify the
  transaction-isolation tests in `test_unit_of_work.py` and `test_audit_log.py`.
- `amount_paise` is stored as `BigInteger`, not `Integer`. The domain model
  places no upper bound on an amount — only the constraint gate's
  `max_amount_paise` does, and that is policy, not a type limit — so the
  column should not silently wrap a value `WorkItem` would accept.
- `create_if_absent`'s duplicate-`event_id` path rolls back only its own
  `SAVEPOINT` (`Session.begin_nested()`), not the whole caller-supplied
  transaction. A dedicated test proves an unrelated write earlier in the same
  transaction survives a sibling duplicate-insert attempt.

---

### Phase 2 — The state machine & orchestrator
_Status: complete_

Satisfies PRD §4 (recovery is a state machine, not a chatbot), §7.4 (the
single-transaction lifecycle), §8.2 (the orchestrator never calls external
services directly), §12.2 (the stopping rule).

Phase 2 is the skeleton the whole recovery loop runs on. Its value is not that
transitions happen but that **illegal transitions are impossible and every legal
transition is atomically audited** — the two properties that separate Recoup from
an LLM agent loop.

#### Added

- `recoup.fsm.states` — `LEGAL_TRANSITIONS`, the exhaustive closed edge set of
  PRD §7.4, plus `is_terminal` and `legal_next`. Exhaustive over `State`: a state
  added later without a transition rule fails the exhaustiveness test rather than
  silently becoming an unreachable dead end. The `EXECUTED → ACTION_CHOSEN` retry
  edge is permitted unconditionally; the constraint gate (Phase 6) decides how
  many times it is walked, so no policy (a retry cap, a time, an amount) leaks
  into the pure state table.
- `recoup.fsm.machine.StateMachine.transition` — the one place a work item's
  state may change. Validates before mutating (terminal check first — §12.2's
  stopping rule; then the legal-transition check — §7.4; then a non-empty
  rationale — §8.6), then checkpoints the work item and appends its audit row
  inside one `unit_of_work`, so a state change can never persist without the row
  that explains it. `retry_count` increments only on `EXECUTED → ACTION_CHOSEN`;
  the method returns a fresh `WorkItem` rather than mutating the caller's
  instance, so a rejected transition can never leave a half-applied object in a
  caller's hands. `IllegalTransition` and `TerminalStateError` both name the
  states involved.
- `recoup.fsm.orchestrator.Orchestrator` — drives one audited transition per
  `advance()` call through three injected collaborators (`diagnose`,
  `select_action`, `check_and_execute`), and so imports nothing from
  `recoup.gateways`, `recoup.channels` or `recoup.diagnosis` (§8.2) — a property
  an AST test enforces, not just the docstring. `run_to_completion` is bounded:
  an item that will not settle raises rather than looping. `GateOutcome` and
  `OrchestratorDeps` define the shapes Phase 6 supplies for real.
- 27 new unit tests (`test_fsm_states.py`, `test_state_machine.py`,
  `test_orchestrator.py`) — 204 unit tests total.

#### Decisions

- One `check_and_execute` result is threaded across the two separately-audited
  `CONSTRAINT_CHECKED` and `EXECUTED` transitions via a small process-local cache
  keyed by `txn_id`, rather than through the `WorkItem` (whose model is closed
  with `extra="forbid"` and carries no scratch field). The durable record of what
  the gate decided is already the `constraint_result`/`constraint_reason`/`outcome`
  written to the audit log by each transition, so nothing about the trail's
  completeness depends on this cache surviving a restart.
- A bug in the salvaged orchestrator — the gate outcome was re-cached on the
  deferred (`SCHEDULED`) path but not on the executed path, so the `EXECUTED` step
  could not find it — was caught by the new happy-path test and fixed by
  re-caching the outcome before the `CONSTRAINT_CHECKED → EXECUTED` transition.

---

## Phase index

| # | Phase | PRD sections | Status |
|---|-------|--------------|--------|
| 0 | Project foundation & domain vocabulary | §9, §10.1, §10.2, §17 | complete |
| 1 | Persistence & append-only audit trail | §8.6, §9.6, §10.2, §14 | complete |
| 2 | State machine & orchestrator | §4, §7.4, §8.2 | complete |
| 3 | Ingestion: signature, normalization, idempotency | §8.1, §13.2, §14 | pending |
| 4 | Diagnosis engine: Tier-1 rules + two-tier composition | §11, §13.2 | pending |
| 5 | Action selector, retry timing, channel policy | §10.3, §11.4, §8.7 | pending |
| 6 | Constraints gate & escalation | §12 | pending |
| 7 | Payment gateway adapter, mock & circuit breaker | §8.4, §9.3, §11.4, §13.1 | pending |
| 8 | End-to-end batch & honest metrics | §5.1, §7.4, §13.4, §15.1 | pending |
| 9 | FastAPI: webhooks, REST, WebSocket | §8.1, §8.8, §9.5, §14 | pending |
| 10 | Next.js dashboard | §8.8, §9.4, §12.4, §15.1 | pending |
| 11 | Groq LLM Tier-2 diagnosis | §9.2, §11.1, §13.1 | pending |
| 12 | Razorpay live adapter | §9.3, §13.1 | pending |
| 13 | SMS & email nudge channels | §8.7, §9.8, §13.1 | pending |
| 14 | Hinglish voice recovery call | §9.7, §11.4, §16.4 | pending |
| 15 | Demo hardening, replay & documentation | §13.3, §13.4, §15, §16 | pending |
