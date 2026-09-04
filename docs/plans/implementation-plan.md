# Recoup — Phase-Wise Implementation Plan

**Spec:** [prd.md](../../prd.md) — read it alongside this plan. Every phase below cites the PRD section it implements.

---

## Context

`c:\Users\inder\OneDrive\Desktop\Recoup` currently contains exactly one file: [prd.md](../../prd.md). Nothing has been built. Not a git repo yet.

The PRD specifies **Recoup**: an autonomous revenue-recovery agent for Razorpay merchants that detects failed payments/renewals, diagnoses *why* each failed, and executes a **bounded** recovery workflow. Its defining property is restraint — an LLM diagnoses, a deterministic state machine decides, a single constraint gate guards every money action, and an append-only audit log proves it.

The build risk this plan is shaped around: it is tempting to build this as one LLM-agent blob and bolt guardrails on afterwards. That produces a system where "every money action is bounded and gated" is a slogan you cannot prove. This plan inverts that — the gate, the audit trail, and the state machine are built **first**, as enforced invariants (DB triggers, unforgeable gate tokens, architecture tests), before any external service is wired in.

**Intended outcome:** a working v0 where the full detect→diagnose→decide→execute→govern loop runs headlessly over 50+ synthetic transactions by Phase 8, gets a live dashboard by Phase 10, and then has real Groq/Razorpay/Twilio credentials swapped in behind interfaces that already exist and are already tested.

### Decisions confirmed with the user

| Decision | Choice | Consequence for this plan |
|---|---|---|
| Timeline | Open-ended, build it properly | Full TDD, real test suite, production-shaped structure, Postgres-ready schema |
| Orchestrator | **Plain Python FSM** (not LangGraph) | PRD §9.1 fallback path taken. ~200 lines, zero deps, checkpointing is a SQLite write. Reinforces the "no magic, bounded" pitch |
| Credentials | None yet — user supplies per phase | Every external service is a Protocol + a fake/mock built in Stage A; the real implementation lands in Stage C behind a **CREDENTIAL GATE** where the build pauses for keys |
| Frontend | **Next.js + WebSocket** | Full dashboard as specced in PRD §8.8 |

---

## Architecture

Seven layers (PRD §7.2), each behind an interface, assembled by a deterministic orchestrator:

```
Ingestion → Orchestrator (FSM) → Diagnosis (rules → LLM) → Action Selector
                                                                  ↓
                              Audit Log  ←──────────────  Constraints Gate
                              (append-only,                 (mints GatePass)
                               DB-enforced)                        ↓
                                                          Action Executor
                                                    (requires a valid GatePass)
                                                                  ↓
                                              Recovery Channels: retry / voice / SMS / email
```

**Two invariants are enforced mechanically, not by convention** — these are the plan's core engineering bets:

1. **The audit log is physically append-only.** SQLite `BEFORE UPDATE`/`BEFORE DELETE` triggers `RAISE(ABORT)` on `audit_events`. Immutability is demonstrable by trying to break it in a test.
2. **The gate is the only door.** `ActionExecutor.execute()` requires a `GatePass` — a frozen dataclass carrying an HMAC token that only `ConstraintGate.check()` can mint. There is no code path to execution without a gate verdict. Backed by an AST architecture test asserting no module outside the executor imports `channels.*`.

**Tech stack:** Python 3.13 (via uv) · FastAPI · SQLAlchemy 2.0 + SQLite · Pydantic v2 · pytest · Next.js 15 (App Router, TypeScript, Tailwind, shadcn/ui) · Groq · Razorpay · Twilio · ElevenLabs

### Phase order vs PRD §17

PRD §17's priority list (ingestion+audit → orchestrator → diagnosis → gate → retry adapter → dashboard → SMS/email → voice) is preserved. Two deliberate changes:

1. **Each external service is split in two** — its Protocol + fake lands in Stage A at the PRD's priority position; its real implementation lands in Stage C behind a credential gate. This is what lets the build proceed with an empty `.env`.
2. **Phase 8 (end-to-end batch) is inserted before the dashboard.** PRD §17 says "keep the system shippable at every checkpoint"; proving the loop headlessly first means the dashboard is displaying a system already known to work, rather than being the place bugs are discovered.

PRD §17's cut-line discipline still holds: cut from the bottom (Phase 14 voice first, per §9.7).

---

## Execution Protocol (binding on every phase)

1. **No third-party attribution, anywhere.** No co-author trailers and no tool-generated attribution lines in commit messages, code comments, docs, README, or PR bodies. Commits are authored solely by `ishaans04 <sharmaishaaan04@gmail.com>`. This overrides any default commit-trailer behaviour.
2. **Local working-context notes are gitignored and never committed.** They are scratch context only.
3. **No stubs, no placeholder scaffolding.** Each phase ships complete, working, tested code. `TODO`, `pass  # later`, `NotImplementedError` in a shipping path, and empty bodies are defects that fail review.
4. **Meaningful commits only.** Conventional Commits (`feat(scope):`, `test:`, `docs:`, `refactor:`, `chore:`). Every commit is independently coherent and explains *why* in its body. No "wip"/"fix"/"update". **Target: 60+ genuine commits.** Per-phase targets are listed on each phase.
5. **Re-read the docs before starting each phase:** `prd.md` (binding authority), `changelog.md`, `docs/interface-contract.md`. Never start a phase from memory.
6. **Update `changelog.md` as the final commit of every phase**, citing the PRD sections satisfied. This is the anti-drift check.
7. **prd.md is the binding authority.** Where this plan and the PRD disagree, the PRD wins and the plan gets corrected.

### Commit budget per phase (total 67)

| Phase | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Commits | 4 | 4 | 4 | 4 | 5 | 4 | 5 | 5 | 5 | 5 | 6 | 3 | 3 | 3 | 3 | 4 |

---

## Global Constraints

Every phase's requirements implicitly include these. Copied from the PRD.

- **Money safety:** the LLM never calls a payment API, never chooses to move money, never overrides a limit (PRD §4.1). Its only output is a `Diagnosis`.
- **Single gate:** `ConstraintGate.check()` is the only path to executing any action (PRD §12.1). Never scatter `if` statements.
- **Hard caps:** `retry_count ≤ 3`, `amount ≤ ₹50,000`, `fraud_flag == false` required. Any breach → `ESCALATED` → human queue (PRD §12.2).
- **Append-only audit:** `audit_events` rows are inserted, never updated, never deleted (PRD §8.6).
- **Idempotency:** dedupe on `event_id`; a webhook delivered twice never triggers two recovery attempts (PRD §8.1).
- **Signature verification:** no unsigned webhook payload is processed, ever (PRD §14).
- **No secrets in code:** env vars only. `.env` is gitignored; `.env.example` is committed (PRD §14).
- **Test mode only:** no production credentials, no real money movement (PRD §5.2).
- **Honest metrics:** every batch report includes the full exception list with reasons. Never cherry-pick (PRD §13.4).
- **Boots without credentials:** the app must start and the full test suite must pass with an empty `.env`. Missing keys degrade to mock/fake implementations, never crash.
- **Currency:** all amounts stored as **integer paise** (`amount_paise`), never floats. Display converts to ₹.

### Deliberate extensions to the PRD (conscious, not drift)

- **`SCHEDULED` state added** to PRD §10.1's state list. Required by PRD §11.4 (salary-cycle retry timing) and §13.1 (circuit breaker parks work items in a waiting state). Without it there is nowhere to hold a work item between "action chosen" and "time to execute".
- **`Clock` protocol** (`SystemClock` / `SimulatedClock`). Salary-cycle retries are real dates in the future and cannot be demoed in real time. Every time-dependent component takes a clock.

---

## File Structure

```
Recoup/
├── prd.md                          # the spec (exists)
├── README.md                       # setup + demo runbook
├── .env.example                    # every key, annotated with the phase that needs it
├── docs/
│   ├── interface-contract.md       # REST + WS shapes — frozen in Phase 0
│   └── plans/                      # copy of this plan
├── backend/
│   ├── pyproject.toml
│   ├── src/recoup/
│   │   ├── config.py               # pydantic-settings; RECOUP_MODE=mock|live
│   │   ├── clock.py                # Clock protocol, SystemClock, SimulatedClock
│   │   ├── domain/                 # enums.py, models.py (WorkItem, AuditEvent, Action, Diagnosis)
│   │   ├── storage/                # db.py, tables.py, work_items.py, audit.py
│   │   ├── fsm/                    # states.py (transition table), machine.py, orchestrator.py
│   │   ├── ingestion/              # signature.py, normalize.py, idempotency.py
│   │   ├── diagnosis/              # base.py, rules.py, engine.py, prompts.py, groq_client.py
│   │   ├── policy/                 # selector.py (cause→action), timing.py, channel_policy.py
│   │   ├── constraints/            # rules.py, gate.py  ← THE single door
│   │   ├── execution/              # executor.py (requires GatePass)
│   │   ├── gateways/               # base.py, mock.py, razorpay.py, circuit_breaker.py
│   │   ├── channels/               # base.py, retry.py, sms.py, email.py, voice.py, router.py
│   │   ├── batch/                  # generator.py, runner.py, fixtures/
│   │   ├── metrics.py              # recovery rate, by-cause, by-channel, exception list
│   │   ├── events.py               # in-process bus → WebSocket fan-out
│   │   └── api/                    # app.py, webhooks.py, routes.py, ws.py
│   └── tests/{unit,integration,architecture}/
└── frontend/
    ├── app/                        # layout.tsx, page.tsx
    ├── components/                 # RecoveryCounter, AuditTable, EscalationQueue, ...
    └── lib/                        # api.ts, ws.ts, api-types.d.ts (generated from OpenAPI)
```

---

# Stage A — The Money-Safe Core (no external services)

Everything here runs offline, needs zero credentials, and ends with a fully working recovery loop.

---

## Phase 0 — Scaffold, Config & the Interface Contract

**Implements:** PRD §17 "first-hour tasks", §9.4 "settle the contract in the first hour"

**Why first:** the Next.js↔FastAPI contract must be frozen before either side is built, or the two halves drift. This phase produces no behaviour — it produces the shared vocabulary.

- [ ] `git init`; add `.gitignore` (Python, Node, `.env`, `*.db`, `.venv`)
- [ ] `uv init backend`; `uv python pin 3.13` (3.14.5 is installed but 3.13 has broader wheel coverage for `razorpay`/`twilio`); deps: `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `sqlalchemy`, `httpx`, `websockets`; dev deps: `pytest`, `pytest-asyncio`, `pytest-cov`, `time-machine`, `respx`, `ruff`, `mypy`
- [ ] `npx create-next-app@latest frontend --ts --tailwind --app --eslint`; add shadcn/ui
- [ ] Write `backend/src/recoup/domain/enums.py` — the vocabulary every later phase imports:

```python
class State(StrEnum):
    DETECTED = "DETECTED"
    DIAGNOSED = "DIAGNOSED"
    ACTION_CHOSEN = "ACTION_CHOSEN"
    CONSTRAINT_CHECKED = "CONSTRAINT_CHECKED"
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class Cause(StrEnum):
    INSUFFICIENT_FUNDS = "insufficient_funds"
    GATEWAY_DEGRADATION = "gateway_degradation"
    SOFT_DECLINE = "soft_decline"
    EXPIRED_INSTRUMENT = "expired_instrument"
    FRAUD_FLAGGED = "fraud_flagged"
    UNKNOWN = "unknown"


class ActionType(StrEnum):
    SCHEDULED_RETRY = "scheduled_retry"
    BACKOFF_RETRY = "backoff_retry"
    IMMEDIATE_RETRY = "immediate_retry"
    CUSTOMER_NUDGE = "customer_nudge"
    NO_ACTION = "no_action"
    ESCALATE = "escalate"


class Channel(StrEnum):
    PAYMENT_RETRY = "payment_retry"
    VOICE = "voice"
    SMS = "sms"
    EMAIL = "email"
    HUMAN_QUEUE = "human_queue"
```

- [ ] Write `domain/models.py` — the shared types every later phase imports. Mirrors PRD §10.1/§10.2 exactly, except `amount` → `amount_paise: int`:

```python
class Customer(BaseModel):
    name: str
    phone: str | None
    email: str | None


class Diagnosis(BaseModel):  # produced in Phase 4, consumed in Phases 5, 6, 10
    cause: Cause
    confidence: float
    rationale: str
    source: Literal["rules", "llm", "fallback"]


class Action(BaseModel):  # produced in Phase 5, gated in Phase 6, run in Phase 7+
    type: ActionType
    channel: Channel
    scheduled_for: datetime | None = None
    attempt: int = 0
    reason: str  # human-readable "why this action"


class FailureContext(BaseModel):  # input to the LLM in Phases 4/11
    failure_code: str
    failure_message: str
    method: str | None
    issuer: str | None
    failure_type: str
    amount_paise: int


class ExecutionResult(BaseModel):  # returned by the executor in Phase 6, filled in Phase 7
    recovered: bool
    channel: Channel
    detail: str
    provider_ref: str | None = None


class WorkItem(BaseModel): ...  # PRD §10.1, with amount_paise and state: State


class AuditEvent(BaseModel): ...  # PRD §10.2, verbatim
```
- [ ] Write `clock.py` — `Clock` Protocol (`now() -> datetime`), `SystemClock`, `SimulatedClock(start, advance())`
- [ ] **Write every cross-layer Protocol declaration** (pre-flight ruling: P0 owns interfaces, later phases own implementations — this is what makes the adapter story in PRD §8.4/§9.3 real). Declarations only, no implementations:

```python
# gateways/base.py
class PaymentGateway(Protocol):
    async def get_transaction(self, txn_id: str) -> GatewayTxn: ...
    async def fetch_failure_reason(self, txn_id: str) -> FailureContext: ...
    async def retry_payment(self, txn_id: str, idempotency_key: str) -> ExecutionResult: ...
    async def send_payment_link(self, txn_id: str) -> str: ...


# channels/base.py
class RecoveryChannel(Protocol):
    name: Channel

    def can_handle(self, item: WorkItem) -> bool: ...
    async def execute(self, item: WorkItem, action: Action) -> ChannelResult: ...


class ChannelRegistry:
    """Real behaviour with zero channels registered: resolve() returns None and the
    executor escalates 'no channel available'. Implementations register in P7/P13/P14."""


# diagnosis/base.py
class LLMClient(Protocol):
    async def classify(self, ctx: FailureContext) -> Diagnosis | None: ...


# constraints/base.py
class BreakerState(Protocol):
    def is_open(self, route: str) -> bool: ...


class NullBreaker:
    """Always-closed breaker. A complete, correct implementation for 'no breaker
    configured' — P7 swaps in the real CircuitBreaker. Not a stub."""

    def is_open(self, route: str) -> bool:
        return False
```
- [ ] Write `config.py` — `pydantic-settings` `Settings` with every key **optional**, plus `RECOUP_MODE: Literal["mock","live"] = "mock"`. Add `.env.example` annotating which phase needs each key
- [ ] Write `docs/interface-contract.md` and **freeze it**:
  - REST: `GET /api/health`, `GET /api/workitems`, `GET /api/workitems/{txn_id}`, `GET /api/workitems/{txn_id}/audit`, `GET /api/audit?since_id=`, `GET /api/metrics`, `GET /api/escalations`, `POST /api/batch/run`, `GET /api/batch/{run_id}`, `POST /api/demo/inject`, `POST /webhooks/razorpay`
  - WS `/ws`: envelope `{type, seq, ts, payload}`; types `audit.appended`, `workitem.updated`, `metrics.updated`, `gate.rejected`, `escalation.created`, `batch.progress`, `batch.completed`. Client sends `{type:"hello", last_seq}` on connect; server backfills from `last_seq` (so a dropped connection mid-demo doesn't lose rows)
- [ ] Tests: `tests/unit/test_models.py` — round-trip serialization, `amount_paise` rejects floats, `SimulatedClock.advance()` moves time
- [ ] **Verify:** `uv run pytest -q` passes; `uv run ruff check`; `npm --prefix frontend run build` succeeds
- [ ] **Commit:** `chore: scaffold backend/frontend, domain vocabulary, frozen interface contract`

**Exit criteria:** both apps build; `docs/interface-contract.md` exists and is frozen; no behaviour yet.

---

## Phase 1 — Persistence & the Physically Append-Only Audit Trail

**Implements:** PRD §8.6, §9.6, §10.2, §14 (auditability)

**Why here:** everything downstream writes to the log. Build it first and make its immutability a property of the database, not a coding convention.

- [ ] `storage/tables.py` — SQLAlchemy 2.0 tables `work_items`, `audit_events`. Schema is Postgres-compatible (PRD §9.6: "same schema in production")
- [ ] Attach immutability triggers via `sqlalchemy.event.listen(audit_events, "after_create", DDL(...))`:

```sql
CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
```

- [ ] `storage/audit.py` — `AuditLog.append(event: AuditEvent) -> int` returning monotonic `id`. **The only writer to that table.** No `update`/`delete` methods exist on the class
- [ ] `storage/work_items.py` — `WorkItemRepo`: `create_if_absent(item) -> tuple[WorkItem, bool]` (idempotent on `event_id`), `get`, `save`, `list(state=, cause=, limit=, cursor=)`
- [ ] `storage/db.py` — `unit_of_work()` contextmanager giving one transaction (pre-flight ruling). Phase 2's `transition` wraps the work-item checkpoint and the audit append in a single unit, so a state change can never persist without its audit row — that atomicity is what makes PRD §8.6's completeness claim true
- [ ] Tests (`tests/unit/test_audit.py`, `test_work_items.py`):
  - `test_audit_row_cannot_be_updated` — raw `UPDATE` raises `OperationalError` containing "append-only"
  - `test_audit_row_cannot_be_deleted` — same for `DELETE`
  - `test_audit_ids_are_monotonic`
  - `test_create_if_absent_is_idempotent_on_event_id` — same `event_id` twice → one row, `created=False` second time
- [ ] **Verify:** `uv run pytest tests/unit/test_audit.py -v` — the two immutability tests are the ones to watch; they are the proof behind PRD §8.6
- [ ] **Commit:** `feat(storage): append-only audit trail enforced by DB triggers`

**Exit criteria:** you can demonstrate immutability by attempting a mutation and watching the DB refuse.

---

## Phase 2 — The State Machine & Orchestrator Skeleton

**Implements:** PRD §4, §7.4, §8.2

- [ ] `fsm/states.py` — `LEGAL_TRANSITIONS: dict[State, frozenset[State]]` and `TERMINAL = {RESOLVED, ESCALATED}`. Encodes PRD §7.4's flow including the bounded loop back to `ACTION_CHOSEN` and the `SCHEDULED` parking state
- [ ] `fsm/machine.py`:

```python
class StateMachine:
    def transition(self, item: WorkItem, to: State, *, rationale: str, **audit_fields) -> WorkItem:
        """Validate → mutate → checkpoint → append audit row. Atomic.
        Raises IllegalTransition if `to` is not in LEGAL_TRANSITIONS[item.state].
        Raises TerminalStateError if item.state is terminal (PRD §12.2 stopping rule)."""
```

- [ ] `fsm/orchestrator.py` — `Orchestrator.advance(item) -> WorkItem` driving one step; node handlers injected as callables (diagnose / select / gate / execute), stubbed for now. Never calls an external service itself (PRD §8.2)
- [ ] Tests:
  - `test_legal_transition_persists_and_audits` — one state change → exactly one audit row with correct `from_state`/`to_state`
  - `test_illegal_transition_raises_and_writes_nothing` — DB unchanged after the raise
  - `test_no_action_after_terminal_state` — RESOLVED and ESCALATED both refuse further transitions (PRD §12.2 stopping rule)
  - `test_every_state_is_reachable` — graph walk from DETECTED reaches all 8 states
- [ ] **Verify:** `uv run pytest tests/unit/test_fsm.py -v`
- [ ] **Commit:** `feat(fsm): deterministic state machine with audited, validated transitions`

---

## Phase 3 — Ingestion: Normalization & Idempotency

**Implements:** PRD §8.1, §13.2 (duplicate webhook), §14 (signature verification)

HTTP transport comes in Phase 9 — this phase is the pure logic, so it is unit-testable without a server or a Razorpay account.

- [ ] `ingestion/signature.py` — `verify_razorpay_signature(body: bytes, header: str, secret: str) -> bool` using `hmac.compare_digest` (constant-time). Testable with a self-computed HMAC; needs no Razorpay account
- [ ] `ingestion/normalize.py` — `normalize(payload: dict) -> WorkItem` for `payment.failed`, `subscription.charged`/`halted`, `invoice.expired`. Downstream never touches Razorpay's raw shape (PRD §8.1)
- [ ] `ingestion/idempotency.py` — thin wrapper over `WorkItemRepo.create_if_absent`, returning a `Deduplicated` marker so the caller can 200-OK without re-processing
- [ ] Capture real-shaped Razorpay webhook JSON into `batch/fixtures/*.json` from Razorpay's public docs (no account needed — these are documented payload shapes)
- [ ] Tests:
  - `test_valid_signature_accepted` / `test_tampered_body_rejected` / `test_wrong_secret_rejected`
  - `test_normalize_payment_failed` → correct `amount_paise`, `failure_code`, `customer`, `failure_type`
  - `test_malformed_payload_raises_before_any_db_write`
  - `test_duplicate_event_id_is_deduplicated` — second delivery returns `Deduplicated`, work item count stays 1 (PRD §13.2)
- [ ] **Verify:** `uv run pytest tests/unit/test_ingestion.py -v`
- [ ] **Commit:** `feat(ingestion): signature verification, payload normalization, event-id idempotency`

---

## Phase 4 — Diagnosis Engine: Tier 1 Rules + Two-Tier Composition

**Implements:** PRD §11 (the moat), §13.2 (unknown code, malformed LLM output)

**Key move:** the *entire* two-tier engine — including confidence routing and LLM failure handling — is built and tested here against a `FakeLLM`. Phase 11 only swaps in the real Groq client. This means the moat is finished and provably correct before a single API key exists.

- [ ] `diagnosis/base.py` — `Diagnosis` and `FailureContext` come from `domain/models.py` (Phase 0); this module adds only the Protocol:

```python
from recoup.domain.models import Diagnosis, FailureContext


class LLMClient(Protocol):
    async def classify(self, ctx: FailureContext) -> Diagnosis | None:
        """Returns None on any failure — rate limit, timeout, malformed JSON,
        out-of-enum cause. Never raises. Never returns an unvalidated cause."""
```

- [ ] `diagnosis/rules.py` — Tier-1 table mapping known Razorpay failure codes → `Cause`, confidence `1.0`, source `"rules"`. Cover the documented code families: `insufficient_funds`, `payment_failed`, `gateway_error`, `card_expired`, `invalid_card`, `authentication_failed`, `payment_frozen`, `international_transaction_not_allowed`, plus the PRD's five core classes (§5.1)
- [ ] `diagnosis/engine.py` — `DiagnosisEngine.diagnose(item) -> Diagnosis`:
  1. Tier-1 rule hit → return it (never touches the LLM; PRD §11.2's answer to "why is an LLM reading a code that already says insufficient_funds")
  2. No hit → `await llm.classify(ctx)`
  3. LLM returned `None`, or `confidence < min_confidence` (default `0.7`) → `Diagnosis(UNKNOWN, 0.0, "<reason>", source="fallback")`, which the selector routes to the safest bounded action or escalation (PRD §11.3)
- [ ] `tests/fakes.py` — `FakeLLM` configurable to return a diagnosis, low confidence, `None`, or malformed output
- [ ] Tests:
  - `test_known_code_resolved_by_rules_without_calling_llm` — assert the fake LLM was never invoked
  - `test_unknown_code_routes_to_llm`
  - `test_low_confidence_llm_result_becomes_fallback_not_a_money_action`
  - `test_llm_unavailable_falls_back_to_rules_tier` (PRD §13.1)
  - `test_malformed_llm_json_never_triggers_a_money_action` (PRD §13.2 — the important one)
  - `test_every_diagnosis_carries_a_nonempty_rationale` (PRD §11.1 — rationale goes in the audit log)
- [ ] **Verify:** `uv run pytest tests/unit/test_diagnosis.py -v`
- [ ] **Commit:** `feat(diagnosis): two-tier engine — deterministic rules + LLM protocol with safe fallbacks`

---

## Phase 5 — Action Selector, Retry Timing & Channel Policy

**Implements:** PRD §10.3 (cause→action table), §11.4 (intervention logic), §8.7 (channel selection as intelligence)

- [ ] `policy/selector.py` — `select_action(diagnosis, item, clock) -> Action`, implementing PRD §10.3 verbatim:

| Cause | Action | Channel |
|---|---|---|
| `INSUFFICIENT_FUNDS` | `SCHEDULED_RETRY` | `PAYMENT_RETRY` |
| `GATEWAY_DEGRADATION` | `BACKOFF_RETRY` | `PAYMENT_RETRY` |
| `SOFT_DECLINE` | `IMMEDIATE_RETRY` (once) | `PAYMENT_RETRY` |
| `EXPIRED_INSTRUMENT` | `CUSTOMER_NUDGE` | voice / SMS / email by policy |
| `FRAUD_FLAGGED` | `NO_ACTION` | `HUMAN_QUEUE` |
| `UNKNOWN` | `ESCALATE` | `HUMAN_QUEUE` |

- [ ] `policy/timing.py` — `next_retry_at(cause, attempt, now) -> datetime`, pure function:
  - `INSUFFICIENT_FUNDS`: next salary-cycle window — the 1st or the last day of month, whichever comes sooner — clamped to 10:00–20:00 IST. Never 2am (PRD §11.4, the India-rooted insight)
  - `BACKOFF_RETRY`: exponential `base * 2**attempt` with jitter
  - `IMMEDIATE_RETRY`: short fixed delay
- [ ] `policy/channel_policy.py` — `choose_channel(item) -> list[Channel]` returning an ordered fallback chain (PRD §13.1: voice → SMS → email). High-value + `EXPIRED_INSTRUMENT` → voice first. Missing phone → drop voice/SMS; missing email too → escalate with reason (PRD §13.2)
- [ ] Tests (using `time-machine` to freeze dates):
  - One test per cause asserting the mapped action — the table above is executable
  - `test_insufficient_funds_retry_lands_in_salary_window` across several frozen "today"s including the 28th, 31st, and Feb 29
  - `test_retry_never_scheduled_between_2200_and_1000`
  - `test_backoff_grows_exponentially_per_attempt`
  - `test_soft_decline_retried_at_most_once`
  - `test_no_contact_info_yields_escalation_with_reason`
- [ ] **Verify:** `uv run pytest tests/unit/test_policy.py -v`
- [ ] **Commit:** `feat(policy): root-cause action router with salary-cycle retry timing and channel fallback`

---

## Phase 6 — The Constraints Gate ⭐

**Implements:** PRD §12 (the credibility layer) — the single most important phase for the pitch.

- [ ] `constraints/rules.py` — one `ConstraintRule` per row of PRD §12.2, each a pure predicate returning `(passed, rule_id, reason)`:
  - `retry_cap` — `retry_count ≤ 3`
  - `amount_cap` — `amount_paise ≤ 5_000_000` (₹50,000)
  - `fraud_block` — `fraud_flag is False` required
  - `terminal_stop` — no action after `RESOLVED` / `ESCALATED`
  - `circuit_open` — route breaker must not be OPEN (wired in Phase 7)
- [ ] `constraints/gate.py` — the unforgeable-token design:

```python
@dataclass(frozen=True)
class GatePass:
    txn_id: str
    action: Action
    checked_at: datetime
    token: str


@dataclass(frozen=True)
class GateVerdict:
    result: Literal["PASS", "FAIL"]
    rule_id: str | None  # which rule refused, e.g. "amount_cap"
    reason: str  # "amount_cap: ₹75,000 > ₹50,000"  ← shown on the dashboard
    gate_pass: GatePass | None  # populated only when result == "PASS"


class ConstraintGate:
    def check(self, action: Action, item: WorkItem) -> GateVerdict:
        """Evaluates ALL rules (so the audit log records every reason, not just
        the first). Mints a GatePass — HMAC over txn_id|action|checked_at with a
        per-process secret — only when every rule passes. This constructor is
        the only place a valid token is created."""
```

- [ ] `execution/executor.py` — `ActionExecutor.execute(gate_pass, item) -> ExecutionResult`, which **verifies the HMAC and the token's freshness first** and raises `GateBypassError` otherwise. Channels are invoked only from here
- [ ] Wire into the orchestrator: `FAIL` → `transition(ESCALATED, ...)` with `constraint_result="FAIL"` and `constraint_reason` recorded, then **stop**
- [ ] Tests (`tests/unit/test_gate.py`):
  - One test per constraint, pass and fail sides
  - `test_gate_fail_escalates_and_records_reason` — asserts the audit row reads `amount_cap: ₹75,000 > ₹50,000` (this exact string appears on screen in PRD §12.4 / §16.5)
  - `test_all_failing_rules_are_reported_not_just_the_first`
  - `test_executor_rejects_a_forged_gate_pass` — hand-construct a `GatePass` with a junk token → `GateBypassError`
  - `test_executor_rejects_a_gate_pass_for_a_different_txn` — token from txn A cannot execute txn B
- [ ] `tests/architecture/test_single_door.py` — **the provable claim**: AST-walk every module under `src/recoup/`; assert no module except `execution/executor.py` and `channels/` imports from `recoup.channels`. Fails the build if someone adds a bypass

```python
def test_only_the_executor_may_import_recovery_channels():
    offenders = [
        m
        for m in walk_modules("src/recoup")
        if imports_from(m, "recoup.channels") and m not in ALLOWED
    ]  # {execution.executor, channels.*}
    assert offenders == [], f"Gate bypass: {offenders} import channels directly"
```

- [ ] **Verify:** `uv run pytest tests/unit/test_gate.py tests/architecture -v`
- [ ] **Commit:** `feat(constraints): centralized gate with unforgeable GatePass + architecture test proving single-door`

**Exit criteria:** you can point a judge at `gate.py` and `test_single_door.py` and say "this is the only door, and this test fails the build if anyone opens another."

---

## Phase 7 — Payment Gateway Adapter, MockGateway & Circuit Breaker

**Implements:** PRD §8.4, §9.3, §11.4 (circuit breaker), §13.1 (gateway degradation)

- [ ] `gateways/base.py` — `PaymentGateway` Protocol: `get_transaction`, `fetch_failure_reason`, `retry_payment(txn_id, idempotency_key)`, `send_payment_link`
- [ ] `gateways/mock.py` — `MockGateway` with **scriptable behaviour**: per-txn success/failure, injectable latency, and a `degrade_route(route, failure_rate)` switch. This is what makes the circuit-breaker demo possible without waiting for a real outage (PRD §8.4)
- [ ] `gateways/circuit_breaker.py` — `CircuitBreaker` keyed by *route* (issuer/method), states `CLOSED → OPEN → HALF_OPEN`, configurable failure threshold + cooldown, driven by the injected `Clock`. On `OPEN`, work items park in `SCHEDULED` rather than failing (PRD §13.1)
- [ ] `channels/base.py` — `RecoveryChannel` Protocol (`name`, `can_handle`, `execute`) and `ChannelResult(delivered, recovered, detail, provider_ref)`
- [ ] `channels/retry.py` — `PaymentRetryChannel` wrapping the gateway; passes a deterministic `idempotency_key` derived from `txn_id + attempt` so a duplicated call can never double-charge
- [ ] `tests/contract/test_payment_gateway.py` — **a shared contract suite parameterized over gateway implementations.** `MockGateway` runs it now; `RazorpayGateway` runs the identical suite in Phase 12
- [ ] Tests:
  - `test_breaker_opens_after_threshold_failures_on_one_route`
  - `test_breaker_isolates_routes` — route A open does not block route B
  - `test_open_breaker_parks_item_in_scheduled_not_failed`
  - `test_breaker_half_opens_after_cooldown_then_closes_on_success`
  - `test_retry_uses_stable_idempotency_key_per_attempt`
- [ ] **Verify:** `uv run pytest tests/contract tests/unit/test_circuit_breaker.py -v`
- [ ] **Commit:** `feat(gateways): PaymentGateway adapter, scriptable MockGateway, route-keyed circuit breaker`

---

## Phase 8 — End-to-End Loop, 50-Transaction Batch & Honest Metrics ⭐

**Implements:** PRD §5.1, §7.4, §13.4, §15.1 — **the milestone: the whole PRD loop works, headlessly, with real numbers.**

- [ ] `batch/generator.py` — `generate_batch(n=50, seed=42) -> list[WorkItem]` producing a realistic distribution across all six causes, with **deliberately seeded scenarios**:
  - a **₹75,000** transaction → guaranteed gate rejection (PRD §16.5)
  - a **cluster of same-route failures** → trips the circuit breaker (PRD §16.3)
  - a **high-value expired-mandate** subscription → the voice-call candidate (PRD §16.4)
  - a **fraud-flagged** transaction → blocked, never acted on
  - a **missing-contact** item and an **unknown failure code** → honest exceptions
  - Deterministic under a fixed seed so runs are reproducible
- [ ] `batch/runner.py` — `BatchRunner.run(items) -> BatchReport`, driving each item through the orchestrator to a terminal state, using `SimulatedClock` to fast-forward scheduled retries
- [ ] `metrics.py` — `BatchReport` with everything in PRD §15.1: `total_at_risk_paise`, `total_recovered_paise`, `recovery_rate`, `by_cause`, `by_channel`, `constraint_rejections`, `escalations`, and `exceptions: list[ExceptionRecord]` where `ExceptionRecord(txn_id, cause, final_state, reason)` — **a required field, not optional** (PRD §13.4)
- [ ] CLI: `uv run python -m recoup.batch --n 50 --seed 42 --report`
- [ ] Tests (`tests/integration/test_batch.py`):
  - `test_batch_of_50_reaches_terminal_state_for_every_item` — no item stuck mid-flight
  - `test_seeded_75000_txn_is_rejected_by_amount_cap_and_escalated`
  - `test_fraud_flagged_txn_never_reaches_the_executor` — spy on the executor
  - `test_degraded_route_cluster_trips_the_breaker`
  - `test_report_exception_list_is_populated_and_reasons_are_specific`
  - `test_recovery_rate_equals_recovered_over_at_risk` — the headline number is arithmetically honest
  - `test_audit_log_has_a_row_for_every_transition_of_every_item` — completeness of the trail
  - `test_batch_is_reproducible_under_a_fixed_seed`
- [ ] **Verify:** run the CLI and read the report. Recovery rate should land in a *plausible* range (roughly 50–70%) with a non-empty exception list. **If it is 100%, the batch is not honest — fix the generator, not the report.**
- [ ] **Commit:** `feat(batch): end-to-end recovery loop over 50 synthetic transactions with honest metrics`

**Exit criteria: the product works.** Everything after this is surface, real credentials, and polish.

---

# Stage B — The Surface

---

## Phase 9 — FastAPI App: Webhooks, REST & WebSocket

**Implements:** PRD §8.1, §8.8, §9.5, §14

- [ ] `events.py` — in-process pub/sub bus with a **monotonic `seq`** and a bounded ring buffer for replay. `AuditLog.append` and state transitions publish to it
- [ ] `api/app.py` — app factory, CORS for `localhost:3000`, lifespan wiring (DB init, gateway selection by `RECOUP_MODE`)
- [ ] `api/webhooks.py` — `POST /webhooks/razorpay`: **verify signature before parsing anything** → normalize → idempotent create → enqueue. Returns `200` for duplicates (so Razorpay stops retrying), `400` for bad signature
- [ ] `api/routes.py` — every REST endpoint from the frozen contract, including `POST /api/demo/inject` for the live ₹75,000 moment
- [ ] `api/ws.py` — `/ws`: on `{type:"hello", last_seq}` backfill from the ring buffer, then stream live. Per-connection queues so one slow client cannot stall the batch
- [ ] Tests (`tests/integration/test_api.py`, via `httpx.ASGITransport` — no live server needed):
  - `test_unsigned_webhook_rejected_with_400_and_no_db_write`
  - `test_duplicate_webhook_returns_200_and_does_not_reprocess`
  - `test_ws_client_receives_audit_appended_events_in_seq_order`
  - `test_ws_reconnect_with_last_seq_backfills_missed_events` — protects the demo against a dropped socket
  - `test_metrics_endpoint_matches_batch_report`
  - `test_openapi_schema_matches_interface_contract`
- [ ] **Verify:** `uv run uvicorn recoup.api.app:app --reload`; `POST /api/batch/run` and watch `/ws` stream via `websocat` or a scratch script
- [ ] **Commit:** `feat(api): signed webhook ingestion, REST surface, replayable WebSocket stream`

---

## Phase 10 — Next.js Dashboard

**Implements:** PRD §8.8, §9.4, §12.4, §15.1, §16

- [ ] Generate `frontend/lib/api-types.d.ts` from FastAPI's OpenAPI via `openapi-typescript` — a build step, so contract drift breaks the build rather than the demo
- [ ] `lib/ws.ts` — typed WS client with auto-reconnect that resends `last_seq` (pairs with Phase 9's backfill)
- [ ] Components:
  - `RecoveryCounter` — big animated ₹ figure; the number that climbs on stage (PRD §16.2)
  - `AuditTable` — live-appending rows: `Event → Diagnosis (+confidence, source badge) → Action → Constraint Check → Result`. Expandable row shows the full rationale
  - `ConstraintRejections` — **visually loud**, red. `₹75,000 > ₹50,000 ✗ → HALT → Escalate`. PRD §12.4 is explicit that the gate must be *seen* to say no
  - `EscalationQueue` — the human queue with reasons
  - `CauseBreakdown` — recovery by cause + by channel (PRD §15.1)
  - `ExceptionList` — unresolved items with reasons, presented as a first-class panel, not a footnote (PRD §13.4)
  - `BatchControls` — Run Batch / Inject ₹75,000 / Reset
- [ ] Design pass: dark, dense, fintech-console aesthetic. Diagnosis source rendered as a badge (`rules` vs `llm`) so the two-tier engine is visible at a glance
- [ ] Tests: Vitest + Testing Library for `AuditTable` append ordering, `RecoveryCounter` formatting (paise→₹, Indian digit grouping), and WS reconnect behaviour
- [ ] **Verify:** run backend + `npm run dev`, hit Run Batch, watch the counter climb and the table fill live. Then kill and restart the backend mid-run to confirm reconnect backfill
- [ ] **Commit:** `feat(dashboard): live recovery counter, audit table, constraint rejections, escalation queue`

**Exit criteria:** the full demo script (PRD §16) is performable end-to-end in mock mode, with no credentials.

---

# Stage C — Real Integrations

Each phase below begins with a **CREDENTIAL GATE**: the build pauses, you add keys to `.env`, and the phase proceeds. Every phase here swaps a real implementation in behind a Protocol that already exists and is already covered by tests — so if a key never arrives, the system still runs.

---

## Phase 11 — Groq LLM (Tier 2) 🔑

**CREDENTIAL GATE:** `GROQ_API_KEY` — [console.groq.com](https://console.groq.com), free, no card.

**Implements:** PRD §9.2, §11.1, §13.1 (rate limits)

- [ ] `diagnosis/prompts.py` — classification prompt: failure context in, strict JSON out (`{cause, confidence, rationale}`), `cause` constrained to the `Cause` enum
- [ ] `diagnosis/groq_client.py` — implements the existing `LLMClient` Protocol:
  - JSON mode (confirm support on the chosen model, per PRD §9.2's design note)
  - **Validate the returned `cause` against the enum** — an out-of-vocabulary cause is treated as a parse failure, not passed through
  - Client-side token-bucket limiter at 30 RPM; honor `retry-after` on 429; exponential backoff
  - On-disk classification cache keyed by a hash of the failure context — serves PRD §13.3's "pre-cache for a stall-proof demo"
  - Every failure path returns `None`, per the Protocol contract
- [ ] Wire selection in `config.py`: `GROQ_API_KEY` present → `GroqClient`; absent → `None` (rules-only, still functional)
- [ ] Tests: `respx`-mocked HTTP for `test_429_is_backed_off_and_returns_none`, `test_malformed_json_returns_none`, `test_out_of_enum_cause_returns_none`, `test_cache_hit_skips_network`. Plus **one** opt-in live test (`-m live`) confirming a real round-trip
- [ ] **Verify:** re-run Phase 8's batch with the key set. The `llm` source badge should now appear on the ambiguous items. Compare the report against the rules-only run
- [ ] **Commit:** `feat(diagnosis): Groq Tier-2 client with rate limiting, validation and disk cache`

---

## Phase 12 — Real Razorpay Adapter 🔑

**CREDENTIAL GATE:** `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` — test mode.

**Implements:** PRD §9.3, §13.1

- [ ] `gateways/razorpay.py` — `RazorpayGateway` implementing `PaymentGateway`. Business logic never imports the SDK; only this file does (PRD §9.3)
- [ ] **Run the Phase 7 contract suite against it unchanged.** If `RazorpayGateway` passes the same tests `MockGateway` passes, the adapter boundary is real
- [ ] Error mapping: timeouts/5xx → retryable within the bounded budget; 4xx → escalate. Never silently drop a work item (PRD §13.1)
- [ ] Set up real webhook delivery: `ngrok http 8000` → register the URL in the Razorpay dashboard → confirm signature verification passes on a genuine delivery
- [ ] Create a handful of real test-mode failures (test cards that decline) and watch them flow through the live pipeline to the dashboard
- [ ] `RECOUP_MODE=live` selects `RazorpayGateway`; `mock` keeps `MockGateway`. **Tests always use mock**
- [ ] **Verify:** a real Razorpay test-mode `payment.failed` webhook reaches the dashboard and produces a complete audit trail
- [ ] **Commit:** `feat(gateways): Razorpay test-mode adapter passing the shared gateway contract suite`

---

## Phase 13 — SMS & Email Nudge Channels 🔑

**CREDENTIAL GATE:** `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` (trial, ~$15 credit, no card) and `RESEND_API_KEY` *or* Gmail SMTP app-password.

**Implements:** PRD §8.7, §9.8, §13.1 (channel fallback)

- [ ] `channels/sms.py`, `channels/email.py` implementing `RecoveryChannel`. Message body includes a Razorpay payment link fetched via `gateway.send_payment_link()`
- [ ] `channels/router.py` — walks the ordered chain from `channel_policy` (voice → SMS → email), **logging each failed attempt as its own audited outcome** before falling through (PRD §13.1: "a failed nudge is still a recorded, bounded outcome")
- [ ] Templates in both English and Hinglish, selected per customer
- [ ] Tests: `respx`-mocked Twilio/Resend. `test_sms_failure_falls_through_to_email_and_both_attempts_are_audited`; `test_all_channels_failing_escalates_with_full_reason_chain`
- [ ] **Verify:** send one real SMS and one real email to yourself; confirm both appear as audit rows on the dashboard
- [ ] **Commit:** `feat(channels): SMS and email nudge channels with audited fallback chain`

---

## Phase 14 — The Hinglish Voice Call 🔑

**CREDENTIAL GATE:** Twilio (from Phase 13) + verified demo numbers + `ELEVENLABS_API_KEY` (free, ~10k chars).

**Implements:** PRD §9.7, §11.4, §16.4 — the demo hook.

- [ ] `channels/voice.py` — `VoiceChannel`: outbound Twilio call, TwiML served from a FastAPI route, `<Gather>` capturing a keypress ("press 1 and I'll send the link")
- [ ] Hinglish script per PRD §16.4: *"Sir, aapka payment fail ho gaya hai, link bhejoon retry karne ke liye?"*
- [ ] **Two TTS paths, per PRD §9.7's cost discipline:** Twilio native TTS by default; ElevenLabs (`<Play>` a pre-rendered MP3) only for the single hero call — so the 10k-char free quota is not burned in testing
- [ ] Post-call webhook records the outcome; a keypress triggers the SMS payment link. Voice failure falls through to SMS via the Phase 13 router
- [ ] Verify demo phone numbers in the Twilio console **now, not on demo day** (PRD §13.3)
- [ ] Tests: mocked Twilio for `test_high_value_expired_mandate_selects_voice_first`, `test_voice_failure_falls_back_to_sms`, `test_keypress_triggers_payment_link_sms`
- [ ] **Verify:** place one real call to a verified number, hear the Hinglish prompt, press 1, receive the SMS
- [ ] **Commit:** `feat(channels): Hinglish voice recovery call via Twilio with ElevenLabs hero audio`

> **Cut-line (PRD §9.7):** this phase is the first thing to drop if anything upstream is unfinished. A great diagnosis engine with real guardrails and a *text* nudge beats a flashy call over a dumb retry loop.

---

# Stage D — Proof

---

## Phase 15 — Demo Hardening, Docs & Honest Reporting

**Implements:** PRD §13.3, §13.4, §15, §16

- [ ] `batch/replay.py` — record a full batch run to JSON and replay it deterministically. Per PRD §13.3: replay the cached run on stage while making 2–3 genuinely live calls for authenticity, so a 429 or a venue network drop can never stall the demo
- [ ] Demo runbook script driving PRD §16's six beats in order, including the `POST /api/demo/inject` ₹75,000 moment
- [ ] `docs/exception-report.md` generator — the honest exception list as a shareable artifact (PRD §13.4)
- [ ] `README.md` — setup, `.env` walkthrough, how to run mock vs live, and an **architecture section that names the invariants and the tests that prove them** (`test_single_door.py`, the audit-immutability tests). This is what a technically literate judge will actually read
- [ ] Full-suite CI: `ruff` + `mypy` + `pytest --cov` with a coverage floor on `constraints/`, `fsm/`, `storage/audit.py` — the money-safe modules
- [ ] Offline rehearsal: kill the network, confirm the cached replay still performs the entire demo
- [ ] **Verify:** run the demo end to end twice — once fully live, once fully offline from cache. Both must complete PRD §16's six beats
- [ ] **Commit:** `feat: demo replay, exception reporting, runbook and architecture docs`

---

## Verification — How to know it actually works

**Per phase:** `uv run pytest -q` (backend) and `npm --prefix frontend test` (from Phase 10) must pass before the phase's commit. `uv run ruff check && uv run mypy src` stays clean throughout.

**The five checks that matter most** — these map one-to-one onto the track's bar (PRD §15.2):

| # | Check | Command / action | Expected |
|---|---|---|---|
| 1 | Audit trail is genuinely immutable | `pytest tests/unit/test_audit.py -v` | Raw `UPDATE`/`DELETE` on `audit_events` both abort |
| 2 | The gate is the only door | `pytest tests/architecture -v` | No module outside the executor imports `channels.*`; forged `GatePass` raises `GateBypassError` |
| 3 | Full loop over a real batch | `uv run python -m recoup.batch --n 50 --seed 42 --report` | Every item terminal; recovery rate plausible (**not 100%**); exception list non-empty with specific reasons |
| 4 | One failure handled gracefully | `POST /api/demo/inject` with the ₹75,000 case | Dashboard shows `amount_cap: ₹75,000 > ₹50,000 ✗ → HALT → Escalate`; item lands in the escalation queue; nothing executes |
| 5 | Live end-to-end | Real Razorpay test-mode failure via ngrok | Webhook → diagnosis → gate → retry/nudge → dashboard row, all within seconds |

**Manual smoke each stage:** run backend + frontend, hit Run Batch, and confirm the counter climbs, the audit table appends in order, and three transactions with three *different* causes visibly receive three *different* actions (PRD §16.3 — this is the "not a retry loop, a root-cause router" moment).

---

## Risks & Mitigations

| Risk | Mitigation (built into the plan) |
|---|---|
| Credentials arrive late or never | Every external service is a Protocol with a working fake; Stage A + B are fully functional with an empty `.env` |
| Groq JSON mode unsupported on the chosen model | PRD §9.2 flags this to confirm during build; enum validation + `None` fallback means a bad response degrades to rules-only, never to a wrong money action |
| Python 3.14.5 wheel gaps for `razorpay`/`twilio` | Pin 3.13 in Phase 0 |
| Two-service fragility on stage | Contract frozen Phase 0 and enforced by generated types; both on localhost; WS reconnect backfill tested in Phase 9 |
| Batch reports a suspiciously perfect number | Phase 8 explicitly fails its own exit criteria at 100% recovery — honesty is a test, not an intention |
| Scope creep into deferred lanes | PRD §5.2 is binding: no checkout-abandonment, no B2B receivables, no multi-PSP, no ML fraud scoring in v1 |
