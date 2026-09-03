# Recoup — Product Requirements Document

**An autonomous, money-safe revenue recovery agent for merchants.**

*Version 1.0 · Buildathon Track 03: AI Revenue Recovery · Razorpay*

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [The Problem](#2-the-problem)
3. [The Solution](#3-the-solution)
4. [Governing Design Principle](#4-governing-design-principle)
5. [Scope — In and Out](#5-scope--in-and-out)
6. [User Personas & Stories](#6-user-personas--stories)
7. [System Architecture](#7-system-architecture)
8. [Component Deep-Dives](#8-component-deep-dives)
9. [Tech Stack — Choices & Justifications](#9-tech-stack--choices--justifications)
10. [Data Model & Schemas](#10-data-model--schemas)
11. [The Diagnosis Engine](#11-the-diagnosis-engine)
12. [The Constraints Gate](#12-the-constraints-gate)
13. [Edge Cases & Failure Handling](#13-edge-cases--failure-handling)
14. [Security, Compliance & Guardrails](#14-security-compliance--guardrails)
15. [Success Metrics](#15-success-metrics)
16. [Demo Script](#16-demo-script)
17. [Build Plan](#17-build-plan)
18. [Future Roadmap](#18-future-roadmap)
19. [Appendix: Cost Sheet](#19-appendix-cost-sheet)

---

## 1. Executive Summary

**Recoup** is an autonomous agent that watches a merchant's payment stream, detects revenue that is slipping away — failed payments, failed subscription renewals, overdue invoices — diagnoses *why* each one failed, and executes a **bounded** recovery workflow to win the money back. Every money action is explainable, gated by hard constraints, and written to an immutable audit trail.

The defining property of Recoup is **restraint**. It is not an autonomous LLM that decides how to spend money. It is a deterministic state machine that uses an LLM only for diagnosis, and never lets that LLM move money directly. Every recovery action passes through a single constraint gate that it cannot override.

**The one-line pitch:**
> Everyone else detects the problem. Recoup diagnoses it, recovers the money, and shows you every decision it made — in Hinglish.

**What makes it defensible:**
- A **root-cause diagnosis engine** that maps each failure to a *different* intervention (not a blind retry loop).
- A **centralized constraint gate** — the single door all money actions pass through — making "every action bounded and gated" a provable claim, not a slogan.
- A **Hinglish voice recovery agent** for high-value failures — a demo hook almost no competing team will attempt.
- **Measured recovery across a batch** with an honest exception list, directly answering the track's bar: *"one cherry-picked match proves nothing."*

---

## 2. The Problem

### 2.1 The core insight

Revenue loss rarely happens in one clean, catchable step. A payment degrades. A checkout gets abandoned. A subscription renewal silently fails. An invoice quietly goes overdue. By the time a human notices, the money — and often the customer — is already gone.

The critical failure of existing approaches is that they treat all payment failures identically: **retry and hope.** But a ₹5,000 payment that failed due to insufficient funds needs a completely different response than one that failed because of a bank-side gateway outage, which needs a completely different response than one that failed because the customer's card expired.

- **Insufficient funds** → retrying immediately just fails again. It needs *timing intelligence* (retry near salary day).
- **Gateway degradation** → hammering a degraded bank endpoint makes it worse. It needs *backoff and circuit breaking*.
- **Expired card / lapsed mandate** → no retry will ever work. It needs the *customer* to act, via a nudge.

Applying one strategy to all three loses money on all three.

### 2.2 Why now

- NPCI's UAP and the global protocol race make agent-to-agent commerce the open problem of the year, and AI can now close the loop end to end: detect → diagnose → choose intervention → recover.
- AI-enabled fraud, returns, and chargebacks are quietly eating merchant margin across Indian BFSI.
- The 2026 builder consensus: verification and bounded execution capacity — not raw generation speed — is the real bottleneck. A recovery agent is exactly a verification-and-bounded-execution problem.

### 2.3 Who feels the pain

Small and mid-sized merchants on Razorpay lose a meaningful slice of revenue to recoverable failures every month, and they lack the engineering capacity to build intelligent, compliant, auditable recovery workflows themselves. They need this as a product, not a project.

---

## 3. The Solution

Recoup closes the loop across five stages:

| Stage | What happens |
|-------|-------------|
| **1. Detect** | Ingests payment events (failed charges, failed subscription renewals, overdue invoices) from Razorpay test-mode via webhooks. Flags recoverable ones. |
| **2. Diagnose** | Classifies each failure by root cause using a two-tier engine: deterministic rules for known error codes, Groq-hosted LLM for ambiguous cases. Every diagnosis carries a rationale. |
| **3. Decide** | Maps each cause to a *specific, bounded* intervention — smart-timed retry, backoff retry, or customer-facing nudge. |
| **4. Execute** | Runs the chosen action: calls Razorpay to retry, or triggers a recovery channel (Hinglish voice / SMS / email). All actions pass the constraint gate first. |
| **5. Govern & Measure** | Logs every state transition to an append-only audit trail. Enforces stopping rules and escalation. Reports total money recovered across the batch, plus the exceptions it could not resolve. |

---

## 4. Governing Design Principle

**Recovery is a state machine, not a chatbot.**

This principle dictates every architectural decision in this document. Each failed payment is a work item that moves through a defined lifecycle:

```
detected → diagnosed → action_chosen → constraint_checked → executed → resolved
                                              │
                                              └────────→ escalated (on constraint breach / exhausted retries)
```

The next state is almost always *known* — it is determined by the diagnosed failure cause, not discovered through open-ended reasoning. Therefore:

1. **The LLM advises; it does not act.** The LLM's only job is diagnosis (classifying an ambiguous failure). It never calls a payment API, never chooses to move money, never overrides a limit.
2. **Code executes, under constraints.** A deterministic orchestrator drives the workflow. Money moves only through the constraint gate.
3. **Fewer degrees of freedom, by design.** This is the opposite of an autonomous multi-agent system. Restraint is the feature.

> **The sentence that ties the system together:**
> The LLM diagnoses, the state machine decides, the constraint gate guards, and the audit log proves it — money never moves without passing the gate, and the gate is the only door.

---

## 5. Scope — In and Out

### 5.1 In scope (v1 / buildathon build)

- **One lane, built deep:** failed payment and failed subscription-renewal recovery.
- Root-cause diagnosis across the core failure classes (insufficient funds, gateway degradation, expired card/mandate, soft decline, fraud-flagged).
- Bounded interventions: smart-timed retry, exponential-backoff retry with circuit breaker, customer nudge (voice / SMS / email).
- Centralized constraint gate (retry ≤ 3, amount cap ≤ ₹50,000, fraud block, stopping rules, human escalation).
- Append-only audit trail.
- Live dashboard: recovery counter, per-transaction audit table, constraint rejections, escalations.
- Hinglish voice recovery call for high-value expired-mandate failures.
- Batch processing over 50+ synthetic transactions with measured recovery rate and honest exception list.

### 5.2 Out of scope (v1) — deliberately deferred

Deferred so the one lane is built bulletproof. Depth beats breadth.

- Checkout-abandonment recovery.
- B2B receivables chasing / promise-to-pay tracking.
- Multi-PSP support (architecture allows it — see the adapter layer — but only Razorpay is wired in v1).
- Real (non-test-mode) money movement.
- Customer-facing self-service portal.
- ML-trained fraud scoring (v1 uses rule/flag-based fraud handling; ML is roadmap).

### 5.3 Explicitly not built

- No autonomous LLM that decides money movement.
- No offense-capable behavior of any kind (aligned with the track's defense-only spirit).

---

## 6. User Personas & Stories

### 6.1 Personas

**Priya — Merchant Operator.** Runs a subscription business on Razorpay. Not technical. Wants lost revenue recovered without hiring an ops team, and wants to trust that the system won't do anything reckless with her customers or her money.

**Arjun — Finance / Risk Lead.** Cares about auditability and control. Needs to prove to *his* stakeholders that every automated money action was bounded, logged, and compliant. Will kill any tool he can't audit.

### 6.2 User stories

- *As Priya,* I want failed payments retried intelligently so I recover revenue without lifting a finger.
- *As Priya,* I want high-value lapsed subscriptions to trigger a friendly recovery call so my best customers come back.
- *As Arjun,* I want every automated action logged immutably so I can audit exactly what happened and why.
- *As Arjun,* I want hard caps on retries and amounts, and automatic human escalation above those caps, so the system can never run away.
- *As Arjun,* I want to see the exceptions the agent could *not* resolve, honestly, rather than a cherry-picked success number.

---

## 7. System Architecture

### 7.1 High-level architecture

```
   Razorpay test-mode  ──webhooks──►   Ingestion Endpoint (FastAPI)
                                              │
                                              ▼
                              ┌───────────────────────────────┐
                              │        ORCHESTRATOR            │
                              │  (LangGraph / Python FSM)      │
                              │  drives state transitions      │
                              └───────────────────────────────┘
                                              │
              ┌───────────────────────────────┼───────────────────────────────┐
              ▼                                ▼                                ▼
     DIAGNOSIS ENGINE                 CONSTRAINTS GATE                    AUDIT LOG
   ┌────────────────────┐          ┌──────────────────────┐         ┌────────────────┐
   │ Tier 1: rules table│          │ retry_count ≤ 3       │         │ append-only    │
   │ Tier 2: Groq LLM   │          │ amount ≤ ₹50,000      │         │ one row per    │
   │   (JSON, rationale) │          │ fraud_flag → block    │         │ state          │
   │ confidence score   │          │ stopping rules        │         │ transition     │
   └────────────────────┘          │ → EXECUTE or ESCALATE │         │ (SQLite)       │
                                    └──────────────────────┘         └────────────────┘
                                              │                              │
                                              ▼                              │
                              ┌───────────────────────────────┐            │
                              │      RECOVERY CHANNELS          │            │
                              │  (common RecoveryChannel iface) │            │
                              ├───────────────────────────────┤            │
                              │ PaymentGateway adapter (retry)  │            │
                              │ Twilio Voice (Hinglish, ElevenLabs)         │
                              │ Twilio SMS                      │            │
                              │ Email (Resend / SMTP)           │            │
                              └───────────────────────────────┘            │
                                              │                              │
                                              ▼                              ▼
                                    ┌──────────────────────────────────────────┐
                                    │   DASHBOARD (Next.js / React)              │
                                    │   ₹ recovered counter · live audit table   │
                                    │   constraint rejections · escalation queue │
                                    │   (live updates via WebSocket)             │
                                    └──────────────────────────────────────────┘
```

### 7.2 Architectural layers

| Layer | Responsibility | Key property |
|-------|---------------|--------------|
| **L1 Orchestrator** | Drives the workflow through defined states | Deterministic, checkpointed |
| **L2 Diagnosis Engine** | Classifies failure → cause + rationale | Two-tier: rules + LLM |
| **L3 Payment Integration** | Talks to Razorpay behind an adapter | Swappable, mockable |
| **L4 Constraints Gate** | The single door for all money actions | Centralized, non-bypassable |
| **L5 Audit Trail** | Immutable record of every transition | Append-only |
| **L6 Recovery Channels** | Executes interventions (retry/voice/SMS/email) | Pluggable behind one interface |
| **L7 Dashboard** | Live view + proof for judges | Real-time |

### 7.3 Why this separation matters

The through-line is **disciplined separation of concerns around a money-safe core.** The LLM is confined to diagnosis. Money is confined behind a single gate. Every external service sits behind an adapter. Every action is logged as an immutable state transition.

Most competing teams will build one blob where an LLM agent loops and calls APIs directly. Recoup instead lets you point at exactly which component makes it *safe* (the gate), which makes it *smart* (the diagnosis engine), and which makes it *auditable* (the log) — and explain why each boundary exists. That is the difference between a hackathon hack and a startup's v0.

### 7.4 Request/data flow (single transaction)

```
1. Webhook fires (payment.failed) ──► Ingestion validates signature, normalizes payload
2. Orchestrator creates work item, state = DETECTED
3. Diagnosis Engine:
      - Tier 1 rules match error code? → cause + action (deterministic)
      - No match / ambiguous? → Groq LLM → cause + confidence + rationale
   state = DIAGNOSED
4. Action Selector maps cause → proposed intervention
   state = ACTION_CHOSEN
5. Constraints Gate evaluates proposed action:
      - PASS → proceed to execution
      - FAIL → state = ESCALATED, human queue, STOP
   state = CONSTRAINT_CHECKED
6. Recovery Channel executes (retry / voice / SMS / email)
   state = EXECUTED
7. Outcome recorded:
      - recovered → state = RESOLVED
      - failed, retries remain → back to step 4 (bounded)
      - failed, retries exhausted → state = ESCALATED
8. Every transition above appended to Audit Log
9. Dashboard updates live via WebSocket
```

---

## 8. Component Deep-Dives

### 8.1 Ingestion Endpoint (FastAPI)

- Receives Razorpay webhooks (`payment.failed`, subscription failures, invoice events).
- **Verifies webhook signature** before processing anything (security-critical — see §14).
- Normalizes the raw payload into an internal `WorkItem` schema so downstream layers never touch Razorpay's raw shape.
- **Idempotent:** deduplicates on event ID so a webhook delivered twice never triggers two recovery attempts.
- For the demo, the same endpoint replays a batch of stored webhook payloads — so "live" and "batch" runs use identical code paths.

### 8.2 Orchestrator

- Models the workflow as an explicit graph: nodes = states, edges = gated transitions.
- Holds per-work-item state; checkpoints it so state survives and the audit trail is a natural byproduct.
- Never calls external services directly — it invokes L2/L4/L6 components.

### 8.3 Diagnosis Engine

See [§11](#11-the-diagnosis-engine) for full detail. Two-tier: deterministic rules first, LLM only for the ambiguous long tail.

### 8.4 Payment Integration (adapter)

- A `PaymentGateway` interface: `fetch_failure_reason()`, `retry_payment()`, `send_payment_link()`, `get_transaction()`.
- Razorpay is one implementation behind it. Business logic never imports the Razorpay SDK directly.
- A `MockGateway` implementation lets us **simulate gateway degradation on demand** — essential for demoing the circuit breaker without waiting for a real outage.

### 8.5 Constraints Gate

See [§12](#12-the-constraints-gate). The single choke-point for money actions.

### 8.6 Audit Trail

- Append-only event table. Never updated, never deleted — only inserted.
- Each row: `{timestamp, txn_id, from_state, to_state, diagnosis, confidence, action, constraint_result, outcome, rationale}`.
- Because it is immutable, it reads as a genuine audit system.

### 8.7 Recovery Channels

- Common interface: `RecoveryChannel.execute(context) -> Result`.
- Implementations: payment retry (via adapter), Twilio voice (Hinglish), Twilio SMS, email.
- The **state machine picks the channel by policy** (high-value + expired mandate → voice; low-value → SMS/email). Channel selection is itself a piece of intelligence.

### 8.8 Dashboard

- Next.js/React, updated live over WebSocket.
- Shows: running ₹-recovered counter, per-transaction audit table (`Event → Diagnosis → Action → Constraint Check → Result`), constraint rejections highlighted, escalation queue.

---

## 9. Tech Stack — Choices & Justifications

Every choice below is made so that the obvious alternative feels weaker *for this specific project*.

### 9.1 Orchestration — LangGraph (with plain-Python FSM fallback)

**Chosen because** a recovery workflow *is* a graph of states with persistent state between them. LangGraph models exactly that — nodes, conditional edges, checkpointing — and hands us the audit trail almost for free.

| Alternative | Why it's weaker here |
|-------------|---------------------|
| **CrewAI / AutoGen** | Multi-*agent* collaboration frameworks — agents talking to agents. That's *more* autonomy; we want *less*. Using them would actively undercut the "bounded, not autonomous" story. |
| **Plain LangChain chains** | Linear. Can't cleanly express "if cause = gateway_degradation, trip breaker and branch; if cause = expired_mandate, go to nudge." We'd fight the framework. |
| **Hand-rolled FSM, no library** | Legitimate and reinforces the "no magic" narrative — kept as the **fallback** if LangGraph feels heavy — but hand-rolling checkpointing costs hours we don't have. |

**Fallback discipline:** if LangGraph adds friction during the build, a plain Python state machine (a dict of states + a transition function) is a fully acceptable substitute. The *concept* — explicit states, gated transitions — is what we pitch, not the library.

### 9.2 Diagnosis LLM — Groq (open model, JSON mode)

**Chosen because** Groq runs open models on LPU hardware at very low latency, which maps onto two demo-winning properties: the 50-transaction batch resolves near-instantly on stage (feels production-grade), and the voice agent's mid-call reasoning has no awkward lag. It is free, needs no credit card, and its free tier (30 RPM / 6,000 TPM / up to 14,400 req/day) comfortably fits our batch.

| Alternative | Why it's weaker here |
|-------------|---------------------|
| **Gemini Flash** | Also free and capable, but ~half the RPM and no latency edge. Groq's speed is a *deliberate architectural reason*, which pitches better than "it was free." (Gemini remains a drop-in fallback if Groq has issues — the diagnosis interface is model-agnostic.) |
| **GPT-4 / Claude (frontier)** | Over-engineering. Classifying failures into ~6 buckets does not need a frontier model, and paid/frontier tiers add cost and latency we'd have to defend. |
| **Pure rules, no LLM** | Looks like a script; can't handle the messy long tail of real failure reasons; forfeits the "AI" story. |

**Design note:** the LLM is called *only* for ambiguous cases (Tier 2), so we stay well under 6,000 TPM. Output is forced to structured JSON so it drops straight into the state machine with no fragile parsing. Confirm JSON mode on the chosen Groq-hosted model during build.

### 9.3 Payments — Razorpay test mode (behind an adapter)

**Chosen because** it's the track's own platform, free in test mode, and simulates the full payment/subscription/invoice lifecycle. The **adapter layer** around it is the real architectural decision: it signals production thinking (swap in Stripe/second PSP without touching core logic) and lets us mock the gateway to force failures on demand.

| Alternative | Why it's weaker here |
|-------------|---------------------|
| **Calling Razorpay SDK directly from business logic** | Couples core logic to one PSP, can't be mocked, can't demo the circuit breaker cleanly. |

### 9.4 Frontend — Next.js / React (+ WebSocket)

**Chosen because** it produces a polished, custom, startup-looking dashboard, and live-updating the audit table + recovery counter over WebSocket is a strong demo moment. Paired with a **separate FastAPI backend** that holds the money-safe core.

| Alternative | Why it's weaker here |
|-------------|---------------------|
| **Streamlit** | Faster to build and a legitimate *fallback* if solo and time-pressed, but less polished and less "product-grade" for a technical fintech track. |
| **All-in-Next.js (orchestration in TS API routes)** | Loses the mature Python ecosystem for orchestration/integrations; heavy long-running workflows sit awkwardly in serverless-style routes (timeouts, cold starts, no persistent in-memory state). |

**Key discipline:** do **not** force the money-safe core into serverless API routes. Keep it an always-on Python service. Settle the Next.js ↔ FastAPI contract (REST endpoints + WebSocket message shape) in the first hour so frontend and backend build in parallel against a fixed interface.

### 9.5 Backend — FastAPI (Python)

**Chosen because** the core (state machine, diagnosis, constraint gate, Razorpay/Twilio integrations) is heavy backend logic best served by Python's mature ecosystem, and FastAPI gives async, WebSocket support, and fast iteration.

### 9.6 Audit store — SQLite

**Chosen because** for a live demo, the right engineering answer is the boring, reliable one: zero setup, zero cost, zero network failure points, and a single inspectable file. The schema is identical to what Postgres would use.

| Alternative | Why it's weaker here |
|-------------|---------------------|
| **Postgres / Mongo / cloud DB** | Defensible in production, but deployment risk and setup time on stage. "SQLite for the demo, Postgres in production, same schema" shows we know the difference — stronger than running Postgres and having it be a liability. |

### 9.7 Voice — Twilio trial + ElevenLabs (hero call)

**Chosen because** Twilio's trial gives ~$15 credit with no credit card and ~1,000 outbound minutes; trial calls reach verified numbers only (up to 5), which is *fine* for a demo we control (we call our own verified phones). Twilio native TTS handles Hinglish acceptably for the working build; ElevenLabs' free tier (~10k chars) is swapped in for the single hero call played to judges.

| Alternative | Why it's weaker here |
|-------------|---------------------|
| **Bland.ai** | Free tier has thinned to small credits with no real free tier; Twilio is more generous and more controllable. |
| **ElevenLabs for every call** | Burns the limited free character quota; unnecessary when only the hero call needs top quality. |

**Deadline discipline:** voice is Layer 6 — the first thing cut if time runs short. A system with a great diagnosis engine and real guardrails but a *text* nudge still wins. A flashy voice call over a dumb retry loop does not.

### 9.8 Email/SMS nudge — Twilio SMS + Resend/SMTP

**Chosen because** Twilio SMS rides the same trial credit; email via Resend free tier (~100/day) or Gmail SMTP app-password is free. Gives the non-voice recovery path without any paid tier.

### 9.9 Stack summary

| Layer | Technology | Cost |
|-------|-----------|------|
| Frontend | Next.js / React + WebSocket | Free |
| Backend / orchestration | FastAPI (Python) | Free (localhost for demo) |
| Workflow engine | LangGraph (fallback: Python FSM) | Free |
| Diagnosis LLM | Groq (open model, JSON) | Free (no card) |
| Payments | Razorpay test mode (via adapter) | Free |
| Voice | Twilio trial + ElevenLabs free | Free (no card) |
| SMS / Email | Twilio SMS / Resend / SMTP | Free tier |
| Audit store | SQLite | Free |

**Total out of pocket: ₹0. No credit card required on the core path.**

---

## 10. Data Model & Schemas

### 10.1 WorkItem (internal normalized representation)

```json
{
  "txn_id": "string (unique)",
  "event_id": "string (for idempotency/dedup)",
  "merchant_id": "string",
  "amount": "number (INR)",
  "currency": "INR",
  "failure_code": "string (raw from PSP)",
  "failure_type": "subscription | one_time | invoice",
  "customer": { "name": "string", "phone": "string", "email": "string" },
  "fraud_flag": "boolean",
  "created_at": "timestamp",
  "state": "DETECTED | DIAGNOSED | ACTION_CHOSEN | CONSTRAINT_CHECKED | EXECUTED | RESOLVED | ESCALATED",
  "retry_count": "integer",
  "diagnosis": { "cause": "string", "confidence": "number", "rationale": "string", "source": "rules | llm" }
}
```

### 10.2 AuditEvent (append-only)

```json
{
  "id": "auto-increment",
  "timestamp": "timestamp",
  "txn_id": "string",
  "from_state": "string",
  "to_state": "string",
  "diagnosis_cause": "string | null",
  "diagnosis_confidence": "number | null",
  "action_chosen": "string | null",
  "constraint_result": "PASS | FAIL | null",
  "constraint_reason": "string | null",
  "outcome": "string | null",
  "rationale": "string"
}
```

### 10.3 Cause → Action mapping table (the policy)

| Failure cause | Retryable? | Chosen action | Channel |
|---------------|-----------|---------------|---------|
| Insufficient funds | Yes | Schedule off-peak / salary-cycle retry | Payment retry |
| Gateway degradation | Yes | Exponential backoff + circuit breaker | Payment retry |
| Soft decline | Yes (once) | Single retry with short backoff | Payment retry |
| Expired card / lapsed mandate | No | Customer nudge for re-auth | Voice (high-value) / SMS / email |
| Fraud-flagged | No | Block, do not act, escalate | Human queue |
| Unknown / ambiguous | LLM decides | Per LLM diagnosis (bounded) | Per policy |

---

## 11. The Diagnosis Engine

*The intelligence layer — the moat.*

### 11.1 Two-tier design

**Tier 1 — Deterministic rules.** Most PSP failure codes are unambiguous. An `insufficient_funds` code does not need an LLM. A rules table maps known code → cause → action. Fast, free, deterministic, and it keeps us off the LLM rate limit for cases that don't need it.

**Tier 2 — Groq LLM for the ambiguous long tail.** Vague gateway errors, unusual decline reasons, conflicting signals. We send the failure context and get back structured JSON: `{cause, confidence, rationale}`. The rationale goes into the audit log.

### 11.2 Why two tiers beats the alternatives

- **"Send everything to the LLM"** (what most teams do): slower, hits rate limits, less reliable, and *less* impressive — a systems-literate judge will ask why an LLM is reading an error code that already says `insufficient_funds`. We've already answered that.
- **"Pure rules"**: forfeits the AI story and can't handle the messy tail.

The pitchable line: *"We use the LLM where it adds judgment and rules where determinism is safer — and every diagnosis carries a rationale in the audit log."*

### 11.3 Confidence handling

- High-confidence LLM diagnosis → proceed to action selection.
- Low-confidence diagnosis → do **not** guess a money action. Route to the safest bounded action or escalate to human. Uncertainty must never resolve into an unbounded money move.

### 11.4 Intervention logic per cause

- **Insufficient funds →** timing intelligence. Don't retry at 2am; schedule near salary cycle (1st / month-end). A distinctly India-rooted insight.
- **Gateway degradation →** exponential backoff + **circuit breaker**: if many transactions are failing on the same route, trip the breaker and halt retries for that route rather than hammering a degraded endpoint. (The term itself signals payments-infra literacy — most teams won't use it.)
- **Expired card / lapsed mandate →** no retry can succeed; the customer must act. Trigger a nudge; for high-value cases, a Hinglish voice call.

---

## 12. The Constraints Gate

*The credibility layer.*

### 12.1 The policy gate pattern

Every proposed action must pass through `check_constraints(action, context)` before execution, and that function is the **only** path to executing anything. Constraints are a discrete, centralized module — never scattered `if` statements.

### 12.2 Enforced constraints

| Constraint | Rule | On breach |
|------------|------|-----------|
| Retry cap | `retry_count ≤ 3` | Stop, escalate |
| Amount cap | `amount ≤ ₹50,000` | Reject, escalate |
| Fraud block | `fraud_flag == false` required | Block, escalate |
| Stopping rule | No further action after RESOLVED or ESCALATED | Halt |
| Escalation trigger | Any breach or exhausted retries | Route to human queue |

### 12.3 Why centralization is architecturally superior

- **A single choke-point is the entire safety argument.** If constraints are sprinkled through the code, "every money action is gated" is unprovable. With exactly one gate, it's provable — and we can show the code.
- **It makes the intentional-failure demo bulletproof:** feed in a ₹75,000 case; the gate rejects it, escalates, logs it — *guaranteed*, because the gate is the only door.
- It maps directly onto the track's bar: *bounded, gated, stopping rules, one failure handled gracefully.*

### 12.4 The visible rejection (demo-critical)

The gate must be seen to say **no**, not just yes. `Amount Cap: ₹75,000 > ₹50,000 ✗ → HALT → Escalate` on screen is worth more than three successful recoveries — it proves the guardrails are real, not decorative. A gate that only ever says yes looks like a label; a gate that says no looks like a system.

---

## 13. Edge Cases & Failure Handling

The architecture is built to handle failure gracefully — because "one failure handled gracefully" is explicitly in the track's bar, and because a real system must.

### 13.1 External service failures

| Failure | Handling |
|---------|----------|
| **Groq rate limit (429 / TPM exceeded)** | Client-side rate limiting; exponential backoff using `retry-after` header; fall back to Tier-1 rules or safest-bounded-action if LLM unavailable. Batch processes sequentially/chunked to stay under 6,000 TPM. Pre-cache classifications for the demo replay so a 429 never stalls the stage. |
| **Razorpay API error / timeout** | Adapter catches, logs to audit, retries within the bounded retry budget; if persistent, escalate. Never silently drop a work item. |
| **Twilio call/SMS failure** | Log outcome; fall back to next channel (voice → SMS → email). A failed nudge is still a recorded, bounded outcome. |
| **Gateway degradation across many txns** | Circuit breaker trips for the affected route; retries halt for that route until reset; work items park in a waiting state rather than failing. |

### 13.2 Data / logic edge cases

| Edge case | Handling |
|-----------|----------|
| **Duplicate webhook** | Idempotency on `event_id` — deduped, no double recovery attempt. |
| **Malformed / unsigned webhook** | Signature verification fails → reject before processing. |
| **Unknown failure code** | No Tier-1 match → Tier-2 LLM; if still low-confidence → safest bounded action or escalate. |
| **Missing customer contact info** | Can't nudge → skip nudge channels, try retry if retryable, else escalate with reason logged. |
| **Amount above cap** | Gate rejects → escalate (this is also the intentional demo failure). |
| **Retries exhausted** | Stop; escalate; log honest "unresolved" outcome — appears in the exception list. |
| **Fraud-flagged transaction** | Never acted on; blocked and escalated immediately. |
| **LLM returns non-JSON / malformed output** | Parse guarded; on failure, treat as low-confidence → safe fallback. Never let a bad parse trigger a money action. |

### 13.3 Demo-environment failures

| Risk | Mitigation |
|------|-----------|
| Live LLM 429 on stage | Pre-run the batch, cache results, replay from stored run while doing 2–3 genuinely live calls for authenticity. |
| Twilio verification not done | Verify demo phone numbers the night before, not live. |
| Two-service (Next + FastAPI) fragility | Fixed interface contract early; localhost for both removes deployment/network failure points; Streamlit fallback exists. |
| Network failure at venue | SQLite + localhost core means the system runs without internet except for the actual API calls; cached batch demonstrates full flow offline if needed. |

### 13.4 The honest-metrics principle

The system **never cherry-picks.** The batch run reports the true recovery rate *and* the full list of exceptions it could not resolve, with reasons. This directly answers the track's bar and builds judge trust: a working system with honest numbers beats a slick fake every time.

---

## 14. Security, Compliance & Guardrails

- **Webhook signature verification** on every inbound event — no unsigned payload is processed.
- **No secrets in code** — API keys via environment variables only.
- **No real money** — test mode throughout; no production credentials.
- **Bounded autonomy** — hard caps the system cannot override (retry, amount), enforced centrally.
- **Human-in-the-loop escalation** — anything above caps, fraud-flagged, or retry-exhausted goes to a human, never auto-actioned.
- **Full auditability** — every action explainable and logged immutably; compliant escalation and stopping rules throughout.
- **Defense-only** — no offense-capable behavior; the system only recovers legitimately owed revenue through compliant channels.
- **Idempotency** — no duplicate money actions from duplicate events.

---

## 15. Success Metrics

### 15.1 Product metrics (what we report on the batch)

- **Total revenue recovered** (₹) across the batch — the headline number.
- **Recovery rate** (% of at-risk revenue recovered).
- **Recovery by cause** (which failure types we recover best).
- **Exception count** — transactions we could not resolve, with reasons (honest).
- **Actions taken by channel** (retry / voice / SMS / email).
- **Constraint rejections / escalations** — proof the gate works.

### 15.2 Buildathon success criteria (mapped to the track's bar)

| Track bar requirement | How Recoup satisfies it |
|-----------------------|-------------------------|
| Detect → diagnose → intervene → recover | The full state-machine loop |
| Measured money recovered across a batch | Batch run over 50+ txns with a real recovery number |
| Compliant escalation | Human queue for breaches/fraud/exhausted retries |
| Stopping rules | Centralized in the constraint gate |
| Audit trail | Append-only log, shown live |
| One failure handled gracefully | Intentional ₹75,000 rejection → escalate, on screen |
| Not cherry-picked | Honest exception list reported alongside successes |

---

## 16. Demo Script

A tight, judge-facing narrative:

1. **Frame (15s):** "Everyone else detects failed payments. Recoup diagnoses *why* they failed and recovers the money — bounded, gated, and audited."
2. **Run the batch (30s):** Hit process. 50 synthetic transactions flow through. The ₹-recovered counter climbs in near-real-time (Groq speed). The audit table fills live.
3. **Show the intelligence (30s):** Point at three transactions with three *different* causes getting three *different* actions — insufficient funds (smart-timed retry), gateway degradation (circuit breaker), expired mandate (nudge). "Not a retry loop — a root-cause router."
4. **The hero call (45s):** A high-value expired-mandate subscription triggers a live Hinglish voice call to a verified phone: *"Sir, aapka payment fail ho gaya hai, link bhejoon retry karne ke liye?"*
5. **The guardrail moment (30s):** Feed the ₹75,000 case. The gate rejects it on screen — `₹75,000 > ₹50,000 ✗ → HALT → Escalate` — and it lands in the human queue. "The gate is the only door, and it just said no."
6. **The honest close (20s):** Show the final number *and* the exception list. "Real recovery, honest exceptions, every decision logged. This is a startup's v0, not a demo."

---

## 17. Build Plan

Build in an order that keeps the system shippable at every checkpoint. **Cut from the bottom** if time runs short.

| Priority | Layer | Rationale |
|----------|-------|-----------|
| 1 | Ingestion + WorkItem schema + SQLite audit | Foundation; everything writes to the log |
| 2 | Orchestrator (state machine) | The skeleton the loop runs on |
| 3 | **Diagnosis engine (rules + Groq)** | The moat — most intelligence effort here |
| 4 | **Constraints gate + escalation** | The credibility — cheap, high-impact; enables the guardrail demo |
| 5 | Payment retry via adapter (+ mock for circuit breaker) | Core recovery action |
| 6 | Dashboard (Next.js + WebSocket) | The proof judges see |
| 7 | SMS / email nudge | Non-voice recovery path |
| 8 | **Hinglish voice call** | The hook — first to cut if time-pressed |

**First-hour tasks:** lock the Next.js ↔ FastAPI interface contract; stand up the WorkItem + AuditEvent schemas; generate the 50-transaction synthetic batch in Razorpay test mode.

**Night-before tasks:** verify Twilio demo numbers; pre-run and cache the batch classifications for a stall-proof replay.

---

## 18. Future Roadmap

Beyond the buildathon, Recoup extends along its existing architectural seams:

- **More lanes:** checkout-abandonment recovery, B2B receivables chasing, promise-to-pay tracking (the other Track 03 example directions) — each a new intervention behind the existing orchestrator.
- **Multi-PSP:** a second `PaymentGateway` implementation (Stripe, etc.) — no core-logic change, thanks to the adapter.
- **ML fraud scoring:** replace rule/flag-based fraud handling with a trained scorer.
- **Learning loop:** feed recovery outcomes back to tune retry timing and channel-selection policy per merchant.
- **Production hardening:** SQLite → Postgres (identical schema), localhost → managed hosting, real-money mode with expanded compliance.
- **Merchant self-service:** dashboards, configurable caps and policies per merchant.

---

## 19. Appendix: Cost Sheet

| Component | Service | Free-tier detail | Card needed? |
|-----------|---------|------------------|:---:|
| Diagnosis LLM | Groq | 30 RPM / 6,000 TPM / ≤14,400 req/day, all models | No |
| Payments | Razorpay test mode | Free by definition | No |
| Voice | Twilio trial | ~$15 credit, ~1,000 min, verified numbers only | No |
| Voice quality (hero call) | ElevenLabs free | ~10k chars/month | No |
| SMS | Twilio SMS | Same trial credit | No |
| Email | Resend / Gmail SMTP | ~100/day / app-password | No |
| Dashboard | Next.js on localhost/Vercel | Free tier | No |
| Backend | FastAPI on localhost | Free | No |
| Audit store | SQLite | Free (single file) | No |

**Total: ₹0 out of pocket. No credit card required on the core path.**

---

*End of PRD — Recoup v1.0*