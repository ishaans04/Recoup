# Recoup — Service Interface Contract

**Status: FROZEN as of Phase 0.**

This document is the boundary between the Next.js dashboard and the FastAPI backend. Both halves
are built independently against it (PRD §9.4: *"Settle the Next.js ↔ FastAPI contract — REST
endpoints + WebSocket message shape — in the first hour so frontend and backend build in
parallel against a fixed interface."*).

Freezing means: the endpoint paths, the field names, the enum values and the WebSocket envelope in
this document do not change. Additive changes (a new optional response field, a new WebSocket
message type) are allowed and must be appended here in the same commit that introduces them.
Renames and removals are breaking and require both halves to change together.

- **Base URL (development):** `http://localhost:8000`
- **WebSocket URL (development):** `ws://localhost:8000/ws`
- **Content type:** `application/json` on every request and response body.
- **Timestamps:** ISO-8601 with an explicit offset, always `+05:30` (Asia/Kolkata). Example:
  `"2026-09-03T14:32:05+05:30"`.
- **Money:** every monetary field is an integer named `*_paise`. There are no floating-point money
  fields anywhere in this contract. ₹500.00 is `50000`.
- **Currency:** `"INR"` only.

---

## 1. Vocabulary

These string values are the contract. They are what the backend writes into the audit log and what
the dashboard renders, so they are identical on both sides, byte for byte.

### `state`

| Value | Meaning |
|---|---|
| `DETECTED` | A failed payment has been normalized into a work item. |
| `DIAGNOSED` | A cause and rationale have been attached. |
| `ACTION_CHOSEN` | The policy has proposed an intervention. |
| `CONSTRAINT_CHECKED` | The constraint gate has evaluated the proposed action. |
| `SCHEDULED` | The action passed the gate but executes at a future time. |
| `EXECUTED` | A recovery channel has run the action. |
| `RESOLVED` | Terminal. The payment was recovered. |
| `ESCALATED` | Terminal. Routed to the human queue. |

`RESOLVED` and `ESCALATED` are terminal: no further transition is ever emitted for a work item in
either state.

### `cause`

`insufficient_funds`, `gateway_degradation`, `soft_decline`, `expired_instrument`, `fraud_flagged`,
`unknown`

### `action_type`

`scheduled_retry`, `backoff_retry`, `immediate_retry`, `customer_nudge`, `no_action`, `escalate`

### `channel`

`payment_retry`, `voice`, `sms`, `email`, `human_queue`

### `failure_type`

`subscription`, `one_time`, `invoice`

### `diagnosis.source`

`rules`, `llm`, `fallback`

### `constraint_result`

`PASS`, `FAIL`, or `null` when the transition did not involve the gate.

---

## 2. Shared object shapes

### 2.1 `WorkItem`

```json
{
  "txn_id": "pay_QjK9x2LmN4TzAb",
  "event_id": "evt_8fH2kQpR7sVdWx",
  "merchant_id": "acc_MerchantDemo01",
  "amount_paise": 249900,
  "currency": "INR",
  "failure_code": "BAD_REQUEST_ERROR",
  "failure_message": "Your card has insufficient balance to complete this payment.",
  "failure_type": "subscription",
  "method": "card",
  "issuer": "HDFC",
  "customer": {
    "name": "Ananya Rao",
    "phone": "+919876543210",
    "email": "ananya.rao@example.com"
  },
  "fraud_flag": false,
  "created_at": "2026-09-03T14:32:05+05:30",
  "state": "DIAGNOSED",
  "retry_count": 1,
  "diagnosis": {
    "cause": "insufficient_funds",
    "confidence": 0.96,
    "rationale": "Issuer message names an insufficient balance; matched by the deterministic rules table on failure_code BAD_REQUEST_ERROR with an insufficient-balance description.",
    "source": "rules"
  },
  "action": {
    "type": "scheduled_retry",
    "channel": "payment_retry",
    "scheduled_for": "2026-09-30T10:00:00+05:30",
    "attempt": 2,
    "reason": "Insufficient funds: retry near the salary cycle rather than immediately."
  }
}
```

`method`, `issuer`, `customer.phone`, `customer.email`, `diagnosis` and `action` are nullable.
`currency` is always `"INR"`.

### 2.2 `AuditEvent`

```json
{
  "id": 412,
  "timestamp": "2026-09-03T14:32:06+05:30",
  "txn_id": "pay_QjK9x2LmN4TzAb",
  "from_state": "ACTION_CHOSEN",
  "to_state": "CONSTRAINT_CHECKED",
  "diagnosis_cause": "insufficient_funds",
  "diagnosis_confidence": 0.96,
  "action_chosen": "scheduled_retry",
  "constraint_result": "PASS",
  "constraint_reason": "retry_count 1 <= 3; amount_paise 249900 <= 5000000; fraud_flag false",
  "outcome": null,
  "rationale": "All four constraints evaluated; the proposed scheduled_retry is within every cap."
}
```

`id` is a monotonically increasing integer assigned by the append-only store. It is the cursor for
`GET /api/audit?since_id=` and for WebSocket backfill. `rationale` is never empty.

### 2.3 `Error`

Every non-2xx response uses this shape.

```json
{
  "error": {
    "code": "work_item_not_found",
    "message": "No work item exists with txn_id pay_DoesNotExist.",
    "detail": null
  }
}
```

| HTTP status | `code` values |
|---|---|
| 400 | `invalid_request` |
| 401 | `invalid_signature` |
| 404 | `work_item_not_found`, `batch_run_not_found` |
| 409 | `duplicate_event` |
| 422 | `validation_error` |
| 503 | `dependency_unavailable` |

---

## 3. REST endpoints

### 3.1 `GET /api/health`

Liveness plus the operating mode, so the dashboard can label the demo honestly.

**200**

```json
{
  "status": "ok",
  "mode": "mock",
  "version": "0.1.0",
  "time": "2026-09-03T14:32:05+05:30",
  "database": "ok",
  "ws_connections": 1
}
```

`mode` is `"mock"` or `"live"`, mirroring `RECOUP_MODE`.

### 3.2 `GET /api/workitems`

Cursor-paginated list, newest first.

| Query param | Type | Default | Notes |
|---|---|---|---|
| `state` | `state` value | none | Repeatable; matches any of the given states. |
| `cause` | `cause` value | none | Repeatable; matches any of the given causes. |
| `limit` | int 1–200 | `50` | |
| `cursor` | opaque string | none | The `next_cursor` from the previous page. |

**200**

```json
{
  "items": [
    {
      "txn_id": "pay_QjK9x2LmN4TzAb",
      "event_id": "evt_8fH2kQpR7sVdWx",
      "merchant_id": "acc_MerchantDemo01",
      "amount_paise": 249900,
      "currency": "INR",
      "failure_code": "BAD_REQUEST_ERROR",
      "failure_message": "Your card has insufficient balance to complete this payment.",
      "failure_type": "subscription",
      "method": "card",
      "issuer": "HDFC",
      "customer": { "name": "Ananya Rao", "phone": "+919876543210", "email": "ananya.rao@example.com" },
      "fraud_flag": false,
      "created_at": "2026-09-03T14:32:05+05:30",
      "state": "RESOLVED",
      "retry_count": 2,
      "diagnosis": {
        "cause": "insufficient_funds",
        "confidence": 0.96,
        "rationale": "Issuer message names an insufficient balance.",
        "source": "rules"
      },
      "action": {
        "type": "scheduled_retry",
        "channel": "payment_retry",
        "scheduled_for": "2026-09-30T10:00:00+05:30",
        "attempt": 2,
        "reason": "Insufficient funds: retry near the salary cycle rather than immediately."
      }
    }
  ],
  "next_cursor": "eyJpZCI6NDEyfQ",
  "total": 50
}
```

`next_cursor` is `null` on the last page.

### 3.3 `GET /api/workitems/{txn_id}`

**200** — a single `WorkItem` object (section 2.1), unwrapped.
**404** — `work_item_not_found`.

### 3.4 `GET /api/workitems/{txn_id}/audit`

The complete transition history for one work item, oldest first.

**200**

```json
{
  "txn_id": "pay_QjK9x2LmN4TzAb",
  "events": [
    {
      "id": 410,
      "timestamp": "2026-09-03T14:32:05+05:30",
      "txn_id": "pay_QjK9x2LmN4TzAb",
      "from_state": null,
      "to_state": "DETECTED",
      "diagnosis_cause": null,
      "diagnosis_confidence": null,
      "action_chosen": null,
      "constraint_result": null,
      "constraint_reason": null,
      "outcome": null,
      "rationale": "Webhook payment.failed accepted; signature verified; work item created."
    },
    {
      "id": 411,
      "timestamp": "2026-09-03T14:32:05+05:30",
      "txn_id": "pay_QjK9x2LmN4TzAb",
      "from_state": "DETECTED",
      "to_state": "DIAGNOSED",
      "diagnosis_cause": "insufficient_funds",
      "diagnosis_confidence": 0.96,
      "action_chosen": null,
      "constraint_result": null,
      "constraint_reason": null,
      "outcome": null,
      "rationale": "Rules table matched the issuer insufficient-balance description; no LLM call needed."
    }
  ]
}
```

`from_state` is `null` only on the first event of a work item.

### 3.5 `GET /api/audit`

The global append-only stream, oldest first. This is the endpoint the dashboard polls if the
WebSocket is unavailable.

| Query param | Type | Default | Notes |
|---|---|---|---|
| `since_id` | int | `0` | Returns events with `id > since_id`. |
| `limit` | int 1–500 | `100` | |

**200**

```json
{
  "events": [
    {
      "id": 413,
      "timestamp": "2026-09-03T14:32:07+05:30",
      "txn_id": "pay_QjK9x2LmN4TzAb",
      "from_state": "EXECUTED",
      "to_state": "RESOLVED",
      "diagnosis_cause": "insufficient_funds",
      "diagnosis_confidence": 0.96,
      "action_chosen": "scheduled_retry",
      "constraint_result": null,
      "constraint_reason": null,
      "outcome": "recovered",
      "rationale": "Retry captured 249900 paise; provider reference pay_QjK9x2LmN4TzAb/rt2."
    }
  ],
  "last_id": 413
}
```

### 3.6 `GET /api/metrics`

The honest-metrics payload (PRD §13.4, §15.1). Attempted and recovered are counted separately so
the dashboard never implies recovery it cannot evidence.

**200**

```json
{
  "total_failed": 50,
  "total_failed_paise": 8742500,
  "attempted": 44,
  "recovered": 19,
  "recovered_paise": 3184600,
  "recovery_rate": 0.38,
  "escalated": 6,
  "gate_rejections": 4,
  "in_flight": 3,
  "by_cause": [
    { "cause": "insufficient_funds", "count": 18, "recovered": 9, "recovered_paise": 1620400 },
    { "cause": "gateway_degradation", "count": 12, "recovered": 7, "recovered_paise": 1120200 },
    { "cause": "soft_decline", "count": 8, "recovered": 3, "recovered_paise": 444000 },
    { "cause": "expired_instrument", "count": 7, "recovered": 0, "recovered_paise": 0 },
    { "cause": "fraud_flagged", "count": 3, "recovered": 0, "recovered_paise": 0 },
    { "cause": "unknown", "count": 2, "recovered": 0, "recovered_paise": 0 }
  ],
  "by_channel": [
    { "channel": "payment_retry", "attempted": 38, "recovered": 19, "recovered_paise": 3184600 },
    { "channel": "sms", "attempted": 4, "recovered": 0, "recovered_paise": 0 },
    { "channel": "voice", "attempted": 1, "recovered": 0, "recovered_paise": 0 },
    { "channel": "email", "attempted": 1, "recovered": 0, "recovered_paise": 0 },
    { "channel": "human_queue", "attempted": 0, "recovered": 0, "recovered_paise": 0 }
  ],
  "generated_at": "2026-09-03T14:35:00+05:30"
}
```

`recovery_rate` is `recovered / attempted`, rounded to two decimals, and is `0.0` when
`attempted` is `0`. It is a ratio, not a money field, so it is the one float in this contract.

### 3.7 `GET /api/escalations`

The human queue: every work item in `ESCALATED`, newest first, with the reason it landed there.

**200**

```json
{
  "escalations": [
    {
      "txn_id": "pay_ZmT4vB8nQ1XcRe",
      "merchant_id": "acc_MerchantDemo01",
      "amount_paise": 7500000,
      "customer_name": "Rohit Mehta",
      "cause": "unknown",
      "reason": "Amount cap: 7500000 paise exceeds the 5000000 paise limit.",
      "constraint_result": "FAIL",
      "escalated_at": "2026-09-03T14:33:11+05:30",
      "retry_count": 0
    },
    {
      "txn_id": "pay_Lp7wR2sYtK9dNv",
      "merchant_id": "acc_MerchantDemo01",
      "amount_paise": 129900,
      "customer_name": "Sneha Iyer",
      "cause": "fraud_flagged",
      "reason": "Fraud block: fraud_flag is set; no money action permitted.",
      "constraint_result": "FAIL",
      "escalated_at": "2026-09-03T14:33:12+05:30",
      "retry_count": 0
    }
  ],
  "total": 6
}
```

### 3.8 `POST /api/batch/run`

Starts a batch over synthetic transactions and returns immediately; progress arrives over the
WebSocket as `batch.progress` and `batch.completed`.

**Request**

```json
{ "size": 50, "seed": 20260903 }
```

`size` defaults to `50` (1–500). `seed` is optional; supplying it makes the generated batch
reproducible.

**202**

```json
{
  "run_id": "run_2026090314350001",
  "size": 50,
  "seed": 20260903,
  "status": "running",
  "started_at": "2026-09-03T14:35:00+05:30"
}
```

### 3.9 `GET /api/batch/{run_id}`

**200**

```json
{
  "run_id": "run_2026090314350001",
  "status": "completed",
  "size": 50,
  "seed": 20260903,
  "processed": 50,
  "started_at": "2026-09-03T14:35:00+05:30",
  "finished_at": "2026-09-03T14:35:04+05:30",
  "metrics": {
    "total_failed": 50,
    "total_failed_paise": 8742500,
    "attempted": 44,
    "recovered": 19,
    "recovered_paise": 3184600,
    "recovery_rate": 0.43,
    "escalated": 6,
    "gate_rejections": 4
  }
}
```

`status` is `running`, `completed` or `failed`. `metrics` is `null` while `running`.
**404** — `batch_run_not_found`.

### 3.10 `POST /api/demo/inject`

Injects one hand-crafted failure so a specific behaviour can be demonstrated on stage — most
importantly the gate saying **no** (PRD §12.4).

**Request**

```json
{
  "amount_paise": 7500000,
  "failure_code": "GATEWAY_ERROR",
  "failure_message": "Payment processing failed at the issuing bank.",
  "failure_type": "one_time",
  "method": "netbanking",
  "issuer": "ICICI",
  "fraud_flag": false,
  "customer": { "name": "Rohit Mehta", "phone": "+919812345678", "email": "rohit.mehta@example.com" }
}
```

Only `amount_paise`, `failure_code` and `failure_message` are required. `failure_type` defaults to
`one_time`, `fraud_flag` to `false`, and a customer is generated when omitted.

**201**

```json
{
  "txn_id": "pay_ZmT4vB8nQ1XcRe",
  "event_id": "evt_demo_2026090314331100",
  "state": "DETECTED",
  "accepted_at": "2026-09-03T14:33:11+05:30"
}
```

### 3.11 `POST /webhooks/razorpay`

The ingestion endpoint. The signature is verified **before** the body is parsed (PRD §14).

**Headers**

| Header | Required | Notes |
|---|---|---|
| `X-Razorpay-Signature` | yes | HMAC-SHA256 of the raw body with the webhook secret. |
| `X-Razorpay-Event-Id` | yes | The idempotency key. |

**Request** — the Razorpay `payment.failed` envelope, passed through unmodified.

```json
{
  "entity": "event",
  "account_id": "acc_MerchantDemo01",
  "event": "payment.failed",
  "contains": ["payment"],
  "payload": {
    "payment": {
      "entity": {
        "id": "pay_QjK9x2LmN4TzAb",
        "amount": 249900,
        "currency": "INR",
        "status": "failed",
        "method": "card",
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Your card has insufficient balance to complete this payment.",
        "card": { "network": "Visa", "issuer": "HDFC" },
        "notes": { "customer_name": "Ananya Rao" },
        "contact": "+919876543210",
        "email": "ananya.rao@example.com",
        "created_at": 1788509525
      }
    }
  },
  "created_at": 1788509525
}
```

Razorpay's `amount` is already in paise and maps straight onto `amount_paise`.

**202** — accepted for processing.

```json
{ "accepted": true, "txn_id": "pay_QjK9x2LmN4TzAb", "duplicate": false }
```

**200 with `"duplicate": true`** — the same `X-Razorpay-Event-Id` was already processed. A webhook
delivered twice never triggers two recovery attempts; the endpoint is idempotent on `event_id` and
this is a success, not an error.

**401** — `invalid_signature`. The body is discarded unparsed.

---

## 4. WebSocket `/ws`

### 4.1 Envelope

Every server-to-client frame uses exactly this envelope. There are no bare payloads.

```json
{
  "type": "audit.appended",
  "seq": 413,
  "ts": "2026-09-03T14:32:07+05:30",
  "payload": {}
}
```

| Field | Type | Meaning |
|---|---|---|
| `type` | string | One of the message types in section 4.3. |
| `seq` | int | Monotonically increasing per connection-independent server stream, starting at 1. |
| `ts` | ISO-8601 | When the server emitted the frame. |
| `payload` | object | Type-specific, documented below. |

`seq` is the resume token. It never decreases and never repeats.

### 4.2 Handshake and backfill

On connect the client sends exactly one frame:

```json
{ "type": "hello", "last_seq": 411 }
```

`last_seq` is the highest `seq` the client has already applied, or `0` on a fresh page load. The
server replies with:

```json
{
  "type": "hello.ack",
  "seq": 413,
  "ts": "2026-09-03T14:32:07+05:30",
  "payload": { "backfill_count": 2, "current_seq": 413, "mode": "mock" }
}
```

and then replays every buffered frame with `seq > last_seq` in order before resuming live delivery.
A socket dropped mid-demo therefore loses nothing: the client reconnects, sends its `last_seq`, and
receives the gap. `backfill_count` is the number of replayed frames. If `last_seq` is older than the
server's retained buffer, `backfill_count` is `-1`, no replay occurs, and the client must refetch
via `GET /api/audit?since_id=`.

The client sends no other frames. It is a read-only subscriber; all mutations go over REST.

### 4.3 Message types

#### `audit.appended`

One append-only audit row was written. `payload` is an `AuditEvent` (section 2.2).

```json
{
  "type": "audit.appended",
  "seq": 413,
  "ts": "2026-09-03T14:32:07+05:30",
  "payload": {
    "id": 413,
    "timestamp": "2026-09-03T14:32:07+05:30",
    "txn_id": "pay_QjK9x2LmN4TzAb",
    "from_state": "EXECUTED",
    "to_state": "RESOLVED",
    "diagnosis_cause": "insufficient_funds",
    "diagnosis_confidence": 0.96,
    "action_chosen": "scheduled_retry",
    "constraint_result": null,
    "constraint_reason": null,
    "outcome": "recovered",
    "rationale": "Retry captured 249900 paise; provider reference pay_QjK9x2LmN4TzAb/rt2."
  }
}
```

#### `workitem.updated`

A work item changed state. `payload` is a `WorkItem` (section 2.1) plus `previous_state`.

```json
{
  "type": "workitem.updated",
  "seq": 414,
  "ts": "2026-09-03T14:32:07+05:30",
  "payload": {
    "previous_state": "EXECUTED",
    "txn_id": "pay_QjK9x2LmN4TzAb",
    "event_id": "evt_8fH2kQpR7sVdWx",
    "merchant_id": "acc_MerchantDemo01",
    "amount_paise": 249900,
    "currency": "INR",
    "failure_code": "BAD_REQUEST_ERROR",
    "failure_message": "Your card has insufficient balance to complete this payment.",
    "failure_type": "subscription",
    "method": "card",
    "issuer": "HDFC",
    "customer": { "name": "Ananya Rao", "phone": "+919876543210", "email": "ananya.rao@example.com" },
    "fraud_flag": false,
    "created_at": "2026-09-03T14:32:05+05:30",
    "state": "RESOLVED",
    "retry_count": 2,
    "diagnosis": {
      "cause": "insufficient_funds",
      "confidence": 0.96,
      "rationale": "Issuer message names an insufficient balance.",
      "source": "rules"
    },
    "action": {
      "type": "scheduled_retry",
      "channel": "payment_retry",
      "scheduled_for": "2026-09-30T10:00:00+05:30",
      "attempt": 2,
      "reason": "Insufficient funds: retry near the salary cycle rather than immediately."
    }
  }
}
```

#### `metrics.updated`

The counters moved. `payload` is the `GET /api/metrics` body (section 3.6) verbatim.

```json
{
  "type": "metrics.updated",
  "seq": 415,
  "ts": "2026-09-03T14:32:07+05:30",
  "payload": {
    "total_failed": 50,
    "total_failed_paise": 8742500,
    "attempted": 44,
    "recovered": 19,
    "recovered_paise": 3184600,
    "recovery_rate": 0.43,
    "escalated": 6,
    "gate_rejections": 4,
    "in_flight": 3,
    "by_cause": [
      { "cause": "insufficient_funds", "count": 18, "recovered": 9, "recovered_paise": 1620400 }
    ],
    "by_channel": [
      { "channel": "payment_retry", "attempted": 38, "recovered": 19, "recovered_paise": 3184600 }
    ],
    "generated_at": "2026-09-03T14:32:07+05:30"
  }
}
```

#### `gate.rejected`

The constraint gate said **no**. This is the demo-critical frame (PRD §12.4) and is emitted for
every `FAIL`, in addition to the `audit.appended` row that records it.

```json
{
  "type": "gate.rejected",
  "seq": 416,
  "ts": "2026-09-03T14:33:11+05:30",
  "payload": {
    "txn_id": "pay_ZmT4vB8nQ1XcRe",
    "constraint": "amount_cap",
    "reason": "Amount cap: 7500000 paise exceeds the 5000000 paise limit.",
    "amount_paise": 7500000,
    "limit_paise": 5000000,
    "retry_count": 0,
    "max_retries": 3,
    "fraud_flag": false,
    "action_type": "immediate_retry",
    "channel": "payment_retry",
    "next_state": "ESCALATED"
  }
}
```

`constraint` is one of `retry_cap`, `amount_cap`, `fraud_block`, `stopping_rule`.
`limit_paise` and `max_retries` are always present so the dashboard can render
`₹75,000 > ₹50,000 ✗` without a second request.

#### `escalation.created`

A work item entered the human queue. `payload` is one entry of the `GET /api/escalations` list
(section 3.7).

```json
{
  "type": "escalation.created",
  "seq": 417,
  "ts": "2026-09-03T14:33:11+05:30",
  "payload": {
    "txn_id": "pay_ZmT4vB8nQ1XcRe",
    "merchant_id": "acc_MerchantDemo01",
    "amount_paise": 7500000,
    "customer_name": "Rohit Mehta",
    "cause": "unknown",
    "reason": "Amount cap: 7500000 paise exceeds the 5000000 paise limit.",
    "constraint_result": "FAIL",
    "escalated_at": "2026-09-03T14:33:11+05:30",
    "retry_count": 0
  }
}
```

#### `batch.progress`

Emitted periodically during a batch run.

```json
{
  "type": "batch.progress",
  "seq": 418,
  "ts": "2026-09-03T14:35:02+05:30",
  "payload": {
    "run_id": "run_2026090314350001",
    "processed": 27,
    "size": 50,
    "recovered": 11,
    "escalated": 3,
    "current_txn_id": "pay_Lp7wR2sYtK9dNv"
  }
}
```

#### `batch.completed`

Emitted once when a batch finishes. `payload` is the `GET /api/batch/{run_id}` body (section 3.9).

```json
{
  "type": "batch.completed",
  "seq": 419,
  "ts": "2026-09-03T14:35:04+05:30",
  "payload": {
    "run_id": "run_2026090314350001",
    "status": "completed",
    "size": 50,
    "seed": 20260903,
    "processed": 50,
    "started_at": "2026-09-03T14:35:00+05:30",
    "finished_at": "2026-09-03T14:35:04+05:30",
    "metrics": {
      "total_failed": 50,
      "total_failed_paise": 8742500,
      "attempted": 44,
      "recovered": 19,
      "recovered_paise": 3184600,
      "recovery_rate": 0.43,
      "escalated": 6,
      "gate_rejections": 4
    }
  }
}
```

---

## 5. Rules that bind both halves

1. **Enum values are lowercase snake_case except `state`, which is UPPERCASE**, and
   `constraint_result`, which is `PASS`/`FAIL`. This asymmetry is deliberate: states are shouted in
   the audit log and the dashboard renders them as badges.
2. **The frontend never computes money.** `recovered_paise` and every other total come from the
   backend. The frontend divides by 100 for display only.
3. **The frontend never infers state.** It renders `state` as received. It does not derive
   "resolved" from a metric or from the absence of a later event.
4. **Unknown enum values are rendered verbatim, not dropped.** If the backend ever emits a value the
   frontend does not know, the dashboard shows the raw string rather than hiding the row. Silent
   omission from an audit view would break the audit claim.
5. **Unknown WebSocket `type` values are ignored, and `seq` is still advanced.** This is what makes
   adding a message type non-breaking.
6. **Ordering is by `seq`, not arrival.** The client applies frames in `seq` order and drops any
   frame whose `seq` it has already applied.
