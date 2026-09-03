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

### Phase 3 — Ingestion: signature verification, normalization, idempotency
_Status: complete_

Satisfies PRD §8.1 (webhook ingestion, live and batch on one code path), §13.2
(duplicate-delivery deduplication), §14 (no unsigned payload processed).

The front door, and a security boundary. HTTP transport is deferred to Phase 9;
this phase is the pure, fully unit-testable logic behind it — no server or
Razorpay account required.

#### Added

- `recoup.ingestion.signature` — `verify_razorpay_signature(body, header, secret)`
  compares an HMAC-SHA256 hex digest of the **raw body** with `hmac.compare_digest`
  (no timing side-channel), rejecting an empty/`None` secret or a
  non-hex/`None` header with `False` rather than raising or validating.
  `compute_razorpay_signature` lets tests produce genuine signatures without an
  account and is reused by Phase 12 for live deliveries.
- `recoup.ingestion.normalize` — `normalize(payload, clock)` reads Razorpay's
  envelope in the one place the system ever does, producing a `WorkItem`. Keeps
  the envelope `id` (`event_id`, the idempotency key) distinct from the entity
  `id` (`txn_id`); copies amounts as paise without dividing; rejects `bool` where
  an `int` is required; extracts `method`/`issuer` for the breaker route key;
  treats missing customer contact as legal (Phase 5 escalates on it). Raises
  `MalformedPayload`/`UnsupportedEvent` before constructing anything.
- `recoup.ingestion.idempotency.Ingestor` — `ingest_raw(body, header)` verifies
  the signature **before** parsing JSON (unauthenticated bytes are never parsed),
  and rejects when no secret is configured rather than skipping the check;
  `ingest_payload(payload)` is the trusted batch/replay path, sharing the same
  `normalize` + `create_if_absent` code as the HTTP path so live and batch runs
  are identical (§8.1). Deduplication rides Phase 1's database-enforced `event_id`
  uniqueness.
- Seven Razorpay-shaped webhook fixtures in `recoup/batch/fixtures/` spanning
  insufficient funds, gateway error, expired card, halted subscription, expired
  invoice, fraud-flagged and unknown-code — reused by Phases 8, 9 and 12.
- 70 new unit tests (`test_signature.py`, `test_normalize.py`,
  `test_ingestion.py`) — 247 unit tests total.

#### Decisions

- A missing customer *name* is filled with a placeholder rather than rejected,
  mirroring §13.2's treatment of missing *contact*: an incomplete merchant record
  should not make a real failure un-ingestable.
- `subscription.charged` normalizes only when it reports a failed charge; a
  successful one raises `UnsupportedEvent` — it is not a failure to recover from.

---

### Phase 4 — The diagnosis engine: Tier-1 rules & two-tier composition
_Status: complete_

Satisfies PRD §11 (the intelligence layer — root-cause diagnosis), §13.1 (degrade
when the LLM is unavailable), §13.2 (a malformed model output never triggers a
money action).

The whole two-tier engine — confidence routing and every LLM failure mode — is
built and tested here against a fake. Phase 11 only swaps a real Groq client in
behind the existing `LLMClient` protocol, so the moat is finished and provably
correct before a single API key exists.

#### Added

- `recoup.diagnosis.rules.RulesTable` — Tier 1. Maps known Razorpay failure codes
  to a `Cause` (confidence 1.0, source `rules`) via exact-code match first, then
  case-insensitive pattern match against code and message. Rule ordering
  guarantees a fraud signal is never shadowed by the broader soft-decline rule —
  a misrouted fraud case would be *acted on* instead of blocked, so a dedicated
  test pins the ordering. Covers all five PRD §5.1 classes.
- `recoup.diagnosis.engine.DiagnosisEngine` — the two-tier composition.
  `diagnose(item)` resolves a known fraud flag first (a hard block never depends
  on the PSP also sending a fraud-shaped code), then Tier 1 (returning without
  ever calling the LLM — the PRD §11.2 property, asserted on the fake's call
  count), then Tier 2 only for the unrecognised tail, then a safe fallback. A
  `None`/absent LLM, a raised exception, or a sub-threshold confidence all become
  `Cause.UNKNOWN` with a *specific* rationale (§11.3). `FailureContext` strips all
  customer, merchant and identifier data before either tier sees it. Counters
  (`tier1_hits`, `tier2_calls`, `fallbacks`) feed the Phase 8 batch report.
- `backend/tests/fakes.py` — `FakeLLM` (fixed result, per-call `results` queue,
  raising, or `None`) plus a shared `make_work_item` factory.
- 29 new unit tests (`test_diagnosis.py`) — 276 unit tests total.

#### Decisions

- Salvaged test bugs, fixed: `test_llm_none_falls_back...` lowercased the haystack
  but not the needle (`"no LLM"` vs `"no llm"`); the mixed-batch test needed a
  `results` queue on `FakeLLM` that did not exist yet. Both were caught by running
  the suite; the fake gained a `results` parameter (at most one of
  `result`/`results`) and the assertion was corrected.
- Formatting: the salvaged files were lint-clean (`ruff check`) but not
  formatter-clean (`ruff format`). Only the Phase 4 files were formatted, to keep
  this phase's diff scoped; a tree-wide `ruff format` and a `--check` CI gate are
  deferred to Phase 15's hygiene sweep.

---

### Phase 5 — Action selector, retry timing & channel policy
_Status: complete_

Satisfies PRD §10.3 (the cause-to-action table), §11.4 (timing intelligence),
§8.7 (channel selection as intelligence), §13.2 (missing-contact handling).

Where the product thesis becomes code: three different causes must produce three
genuinely different interventions. This layer decides **what** to do; it never
decides **whether** it is allowed — that authority belongs to Phase 6's gate
alone.

#### Added

- `recoup.policy.timing` — pure, clock-free retry scheduling. `next_retry_at`
  schedules an insufficient-funds retry for the next salary-cycle moment (this
  month's last day or next month's 1st, whichever is sooner — correct across
  28/29/30/31-day months and year rollover), gateway degradation with capped
  exponential backoff and deterministic jitter, and a soft decline with a short
  fixed delay. Every result is clamped into the 10:00–20:00 IST retry window;
  `is_within_retry_window` and `clamp_to_retry_window` are exposed and tested.
  A non-retryable cause raises rather than inventing a schedule.
- `recoup.policy.channel_policy.choose_channel_chain` — the ordered nudge chain
  from value (high-value lapsed mandate + phone → voice leads) and reachability
  (a channel the customer cannot receive is never offered). No contact yields an
  empty chain, the answer the escalation path distinguishes from a failed nudge.
- `recoup.policy.selector` — `select_action` implements PRD §10.3 exactly, and
  `chain_for` exposes the full fallback chain for Phase 13's router. Two safety
  properties hold regardless of diagnosis: a fraud flag always yields
  `NO_ACTION`, and an unrecognised cause escalates rather than being guessed.
- 70 new unit tests (`test_timing.py`, `test_channel_policy.py`,
  `test_selector.py`) — 346 unit tests total.

#### Decisions

- The Phase 5 agent died before writing any tests, so all three test files were
  written fresh against the salvaged (correct) source. The brief's example "from
  the 29th → 1st of next month" was imprecise: "whichever salary moment is sooner"
  makes the 29th of a 30-day month schedule the 30th, not next month's 1st. Tests
  pin the mathematically correct behaviour.
- `select_action` and `chain_for` take `diagnosis` as an explicit argument rather
  than reading `item.diagnosis`, because the orchestrator may call them before the
  diagnosis is persisted onto the item.

---

### Phase 6 — The constraints gate (the credibility layer)
_Status: complete_

Satisfies PRD §12 in full (the policy gate pattern, the enforced constraints,
centralization, the visible rejection), plus §14 (bounded autonomy, human
escalation) and §8.6 (every evaluation recorded).

The single most important phase for the pitch. It turns PRD §12.3's claim — "with
exactly one gate, it's provable" — from an organizing principle into a mechanical
fact enforced by an unforgeable token and an AST test that fails the build if a
second door is ever opened.

#### Added

- `recoup.money` — `format_inr_paise` / `group_indian`, lakh-grouped rupee
  rendering (`Rs 75,000`, `Rs 1,20,500`). Reused by Phase 8's report.
- `recoup.constraints.rules` — one pure `ConstraintRule` per PRD §12.2 row
  (`retry_cap`, `amount_cap`, `fraud_block`, `terminal_stop`, `circuit_open`,
  `channel_available`), each returning a `RuleVerdict(passed, rule_id, reason)`.
  A rule that does not apply to an action still runs and returns a passing verdict
  that says so, so the audit log records that every constraint was considered. The
  amount-cap breach renders exactly `amount_cap: Rs 75,000 > Rs 50,000` (§12.4,
  §16.5). `default_rules(...)` assembles the set; `circuit_open` binds a
  `BreakerState` (defaulting to `NullBreaker`, replaced by Phase 7).
- `recoup.constraints.gate.ConstraintGate` — evaluates **every** rule (so a
  refusal shows all its causes at once) and mints a `GatePass` only when all pass.
  The pass carries an HMAC over `txn_id | action_fingerprint | checked_at`, keyed
  by a per-process secret held name-mangled and never logged. `verify` rejects a
  forged token, a pass minted for another transaction or another action, and a
  stale pass, raising `GateBypassError`.
- `recoup.execution.executor.ActionExecutor` — verifies the pass as its first
  statement, then resolves and runs a channel; the **only** module that imports
  `recoup.channels`. `recoup.execution.pipeline.GatePipeline` composes gate and
  executor into the orchestrator's `check_and_execute`, producing one of four
  `GateOutcome`s: refuse, escalate-by-policy, defer, execute.
- `tests/architecture/test_single_door.py` — AST tests that fail the build if any
  module outside the executor imports the channels package, or if `GatePass` is
  constructed outside the gate. Plus `tests/integration/test_gate_orchestration.py`,
  driving over-cap and fraud items to `ESCALATED` through the real, fully-composed
  stack with a spy channel proving nothing ran.
- 43 new tests (`test_money.py`, `test_constraints.py`, `test_executor.py`,
  2 architecture, 2 integration) — 389 tests total.

#### Decisions

- The amount cap applies to retries **and** nudges (a nudge sends a payment link
  for the full amount), but not to `NO_ACTION`/`ESCALATE`, which move no money.
- The pipeline realigns an action's `attempt` to the item's `retry_count` before
  gating, so a reused action on the retry loop gets a fresh fingerprint and (in
  Phase 7) a fresh idempotency key rather than silently deduplicating.
- `circuit_open` builds its route key through `FailureContext.route`, byte-for-byte
  the key Phase 7's breaker and retry channel count against, so the gate and the
  breaker can never disagree about what a route is.

---

### Phase 7 — Payment gateway adapter, mock & circuit breaker
_Status: complete_

Satisfies PRD §8.4 (the adapter and its mockability), §9.3 (swappable PSP behind
the port), §11.4 and §13.1 (the circuit breaker), and feeds §8.7 (the retry
channel behind the recovery-channel interface).

Two things at once: the adapter boundary that lets a real PSP be swapped in without
touching core logic, proven by a shared conformance suite; and a genuine
three-state circuit breaker that stops Recoup hammering a degraded route.

#### Added

- `recoup.gateways.circuit_breaker.CircuitBreaker` — canonical
  `CLOSED`/`OPEN`/`HALF_OPEN`, keyed per `method:issuer` route so one degraded
  issuer never bars healthy banks. Ages on the injected clock (never wall time),
  so the Phase 8 fast-forward resolves cooldowns; `is_open` is `False` in
  `HALF_OPEN` so one trial call probes recovery; `snapshot()` feeds the dashboard.
  Satisfies `BreakerState`, dropping into the gate where `NullBreaker` sat.
- `recoup.gateways.mock.MockGateway` — a `PaymentGateway` with three levers a real
  gateway lacks: per-transaction scripting (`succeeds_on_attempt`), on-demand route
  degradation (trips the breaker without a real outage, §8.4), and a recorded call
  log. Idempotent by key and deterministic under its seed, so batches reproduce.
- `recoup.channels.retry.PaymentRetryChannel` — re-presents a failed payment and
  feeds every outcome to the breaker. Its idempotency key is a pure function of txn
  and attempt (a crash-and-retry cannot double-charge); a gateway exception is
  caught, recorded as a breaker failure, and returned as a bounded non-recovery.
- `tests/contract/test_payment_gateway.py` — the shared conformance suite,
  parameterized over gateway implementations. Phase 12 adds `RazorpayGateway` to
  the one factory dict and reruns it unchanged.
- 29 new tests (`test_circuit_breaker.py`, `test_retry_channel.py`,
  `test_mock_gateway.py`, 6 contract) — 418 tests total.

#### Decisions

- The salvaged breaker was complete and correct but never linted; a nested-`if` in
  its cooldown aging was flattened to satisfy `ruff`, no behaviour change.
- `MockGateway.calls` deliberately excludes idempotent replays, so a test asserting
  "exactly one charge despite two execute calls" reads directly off the call log.

---

## Phase index

| # | Phase | PRD sections | Status |
|---|-------|--------------|--------|
| 0 | Project foundation & domain vocabulary | §9, §10.1, §10.2, §17 | complete |
| 1 | Persistence & append-only audit trail | §8.6, §9.6, §10.2, §14 | complete |
| 2 | State machine & orchestrator | §4, §7.4, §8.2 | complete |
| 3 | Ingestion: signature, normalization, idempotency | §8.1, §13.2, §14 | complete |
| 4 | Diagnosis engine: Tier-1 rules + two-tier composition | §11, §13.2 | complete |
| 5 | Action selector, retry timing, channel policy | §10.3, §11.4, §8.7 | complete |
| 6 | Constraints gate & escalation | §12 | complete |
| 7 | Payment gateway adapter, mock & circuit breaker | §8.4, §9.3, §11.4, §13.1 | complete |
| 8 | End-to-end batch & honest metrics | §5.1, §7.4, §13.4, §15.1 | pending |
| 9 | FastAPI: webhooks, REST, WebSocket | §8.1, §8.8, §9.5, §14 | pending |
| 10 | Next.js dashboard | §8.8, §9.4, §12.4, §15.1 | pending |
| 11 | Groq LLM Tier-2 diagnosis | §9.2, §11.1, §13.1 | pending |
| 12 | Razorpay live adapter | §9.3, §13.1 | pending |
| 13 | SMS & email nudge channels | §8.7, §9.8, §13.1 | pending |
| 14 | Hinglish voice recovery call | §9.7, §11.4, §16.4 | pending |
| 15 | Demo hardening, replay & documentation | §13.3, §13.4, §15, §16 | pending |
