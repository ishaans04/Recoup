/**
 * The frontend's mirror of the backend contract.
 *
 * These types are hand-written from `docs/interface-contract.md`, not generated.
 * That is deliberate for now: the contract is frozen before either half is built,
 * so the dashboard can be developed against it while the FastAPI app does not yet
 * exist. Phase 9 replaces this file with types generated from the backend's
 * OpenAPI schema, at which point a drift between the two becomes a compile error
 * rather than a runtime surprise. Until then, this file is the source of truth on
 * this side and every string literal below must match the contract byte for byte.
 *
 * Two rules from section 5 of the contract shape what is and is not modelled here:
 *
 * - Money is always an integer number of paise. There is no rupee field and no
 *   float money anywhere in this file. Divide by 100 at the point of display only.
 * - Unknown enum values are rendered verbatim rather than dropped. The unions
 *   below are therefore documentation and autocomplete, not a filter; code that
 *   renders one must handle a value it does not recognise instead of hiding the
 *   row, because silently omitting a row would break the audit claim.
 */

/** The lifecycle of a failed payment. Uppercase, unlike every other enum. */
export type State =
  | "DETECTED"
  | "DIAGNOSED"
  | "ACTION_CHOSEN"
  | "CONSTRAINT_CHECKED"
  | "SCHEDULED"
  | "EXECUTED"
  | "RESOLVED"
  | "ESCALATED";

/** States from which no further transition is ever emitted. */
export const TERMINAL_STATES: readonly State[] = ["RESOLVED", "ESCALATED"];

export function isTerminal(state: State): boolean {
  return TERMINAL_STATES.includes(state);
}

/** Why a payment failed, as decided by the diagnosis engine. */
export type Cause =
  | "insufficient_funds"
  | "gateway_degradation"
  | "soft_decline"
  | "expired_instrument"
  | "fraud_flagged"
  | "unknown";

/** The bounded set of interventions the policy may propose. */
export type ActionType =
  | "scheduled_retry"
  | "backoff_retry"
  | "immediate_retry"
  | "customer_nudge"
  | "no_action"
  | "escalate";

/** How an action reaches the world. */
export type Channel =
  | "payment_retry"
  | "voice"
  | "sms"
  | "email"
  | "human_queue";

/** What kind of payment failed. */
export type FailureType = "subscription" | "one_time" | "invoice";

/** Which tier produced a diagnosis. */
export type DiagnosisSource = "rules" | "llm" | "fallback";

/** The gate's verdict. Null when a transition did not involve the gate. */
export type ConstraintResult = "PASS" | "FAIL";

/** Which constraint refused an action. */
export type ConstraintName =
  | "retry_cap"
  | "amount_cap"
  | "fraud_block"
  | "stopping_rule";

export interface Customer {
  name: string;
  phone: string | null;
  email: string | null;
}

export interface Diagnosis {
  cause: Cause;
  confidence: number;
  rationale: string;
  source: DiagnosisSource;
}

export interface Action {
  type: ActionType;
  channel: Channel;
  /** ISO-8601 with a +05:30 offset. Null means execute now. */
  scheduled_for: string | null;
  attempt: number;
  reason: string;
}

export interface WorkItem {
  txn_id: string;
  event_id: string;
  merchant_id: string;
  /** Integer paise. Never a float, never rupees. */
  amount_paise: number;
  currency: "INR";
  failure_code: string;
  failure_message: string;
  failure_type: FailureType;
  method: string | null;
  issuer: string | null;
  customer: Customer;
  fraud_flag: boolean;
  /** ISO-8601 with a +05:30 offset. */
  created_at: string;
  state: State;
  retry_count: number;
  diagnosis: Diagnosis | null;
  action: Action | null;
}

export interface AuditEvent {
  id: number;
  timestamp: string;
  txn_id: string;
  /** Null only on a work item's first event. */
  from_state: State | null;
  to_state: State;
  diagnosis_cause: Cause | null;
  diagnosis_confidence: number | null;
  action_chosen: ActionType | null;
  constraint_result: ConstraintResult | null;
  constraint_reason: string | null;
  outcome: string | null;
  rationale: string;
}

export interface Escalation {
  txn_id: string;
  merchant_id: string;
  amount_paise: number;
  customer_name: string;
  cause: Cause;
  reason: string;
  constraint_result: ConstraintResult;
  escalated_at: string;
  retry_count: number;
}

export interface CauseMetric {
  cause: Cause;
  count: number;
  recovered: number;
  recovered_paise: number;
}

export interface ChannelMetric {
  channel: Channel;
  attempted: number;
  recovered: number;
  recovered_paise: number;
}

export interface Metrics {
  total_failed: number;
  total_failed_paise: number;
  attempted: number;
  recovered: number;
  recovered_paise: number;
  /** A ratio, not money. The one float in the contract. */
  recovery_rate: number;
  escalated: number;
  gate_rejections: number;
  in_flight: number;
  by_cause: CauseMetric[];
  by_channel: ChannelMetric[];
  generated_at: string;
}

export type BatchStatus = "running" | "completed" | "failed";

export interface BatchRun {
  run_id: string;
  status: BatchStatus;
  size: number;
  seed: number | null;
  processed: number;
  started_at: string;
  finished_at: string | null;
  /** Null while the run is still in progress. */
  metrics: Omit<Metrics, "in_flight" | "by_cause" | "by_channel" | "generated_at"> | null;
}

export interface HealthResponse {
  status: "ok";
  /** Mirrors RECOUP_MODE. A mocked run must not be mistakable for a live one. */
  mode: "mock" | "live";
  version: string;
  time: string;
  database: string;
  ws_connections: number;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
    detail: string | null;
  };
}

/* -------------------------------------------------------------------------- */
/* WebSocket                                                                   */
/* -------------------------------------------------------------------------- */

export type WsMessageType =
  | "hello.ack"
  | "audit.appended"
  | "workitem.updated"
  | "metrics.updated"
  | "gate.rejected"
  | "escalation.created"
  | "batch.progress"
  | "batch.completed";

/**
 * The envelope every server frame arrives in. There are no bare payloads.
 *
 * `seq` is the resume token: it never decreases and never repeats. The client
 * applies frames in `seq` order, drops any `seq` it has already applied, and
 * advances `seq` even for a `type` it does not recognise — which is what makes
 * adding a message type a non-breaking change.
 */
export interface WsEnvelope<T = unknown> {
  type: WsMessageType;
  seq: number;
  ts: string;
  payload: T;
}

/** The single frame the client sends, once, on connect. */
export interface WsHello {
  type: "hello";
  /** The highest seq already applied, or 0 on a fresh load. */
  last_seq: number;
}

export interface WsHelloAckPayload {
  /** How many frames were replayed. -1 when the gap exceeds the server's buffer,
   *  in which case the client must refetch via GET /api/audit?since_id=. */
  backfill_count: number;
  current_seq: number;
  mode: "mock" | "live";
}

export interface WsWorkItemUpdatedPayload extends WorkItem {
  previous_state: State;
}

export interface WsGateRejectedPayload {
  txn_id: string;
  constraint: ConstraintName;
  reason: string;
  amount_paise: number;
  limit_paise: number;
  retry_count: number;
  max_retries: number;
  fraud_flag: boolean;
  action_type: ActionType;
  channel: Channel;
  next_state: State;
}

export interface WsBatchProgressPayload {
  run_id: string;
  processed: number;
  size: number;
  recovered: number;
  escalated: number;
  current_txn_id: string;
}

export type WsMessage =
  | WsEnvelope<WsHelloAckPayload> & { type: "hello.ack" }
  | WsEnvelope<AuditEvent> & { type: "audit.appended" }
  | WsEnvelope<WsWorkItemUpdatedPayload> & { type: "workitem.updated" }
  | WsEnvelope<Metrics> & { type: "metrics.updated" }
  | WsEnvelope<WsGateRejectedPayload> & { type: "gate.rejected" }
  | WsEnvelope<Escalation> & { type: "escalation.created" }
  | WsEnvelope<WsBatchProgressPayload> & { type: "batch.progress" }
  | WsEnvelope<BatchRun> & { type: "batch.completed" };

/* -------------------------------------------------------------------------- */
/* Display helpers                                                             */
/* -------------------------------------------------------------------------- */

/**
 * Format integer paise as rupees for display.
 *
 * The only place a monetary value stops being an integer, and it stops being one
 * on its way to the screen and nowhere else. Nothing computed from this value is
 * ever sent back to the backend.
 */
export function formatPaise(paise: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(paise / 100);
}

/** Turn any contract enum value into a human label, including unrecognised ones. */
export function humanise(value: string): string {
  return value
    .toLowerCase()
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
