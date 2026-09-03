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

## Phase index

| # | Phase | PRD sections | Status |
|---|-------|--------------|--------|
| 0 | Project foundation & domain vocabulary | §9, §10.1, §10.2, §17 | complete |
| 1 | Persistence & append-only audit trail | §8.6, §9.6, §10.2, §14 | pending |
| 2 | State machine & orchestrator | §4, §7.4, §8.2 | pending |
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
