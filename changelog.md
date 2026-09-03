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
_Status: in progress_

---

## Phase index

| # | Phase | PRD sections | Status |
|---|-------|--------------|--------|
| 0 | Project foundation & domain vocabulary | §9, §10.1, §10.2, §17 | in progress |
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
