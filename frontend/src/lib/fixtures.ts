/**
 * Preview dataset — contract-shaped sample data for when the FastAPI backend
 * (Phase 9) is not reachable yet.
 *
 * This is not a mockup. It is a full, internally consistent batch: 20 work
 * items spanning every `Cause`, run through a state machine that matches
 * `docs/interface-contract.md` exactly — the same enums, the same event
 * shape, the same envelope the live WebSocket would send. Every aggregate
 * number in `FIXTURE_METRICS` is derived from the 20 items below by the same
 * kind of counting the real backend would do (see `computeMetrics` at the
 * bottom), not typed in by hand, so nothing here can silently drift out of
 * arithmetic agreement with itself.
 *
 * Two of the twenty reuse the exact worked examples from the interface
 * contract (`pay_ZmT4vB8nQ1XcRe`, the ₹75,000 amount-cap rejection, and
 * `pay_Lp7wR2sYtK9dNv`, the fraud block) so the preview screen a judge sees
 * before the backend exists is literally the contract's own demo case.
 */

import type {
  Action,
  ActionType,
  AuditEvent,
  BatchRun,
  Cause,
  Channel,
  ConstraintName,
  ConstraintResult,
  Customer,
  DiagnosisSource,
  Escalation,
  FailureType,
  Metrics,
  State,
  WorkItem,
  WsGateRejectedPayload,
} from "./types";

/* -------------------------------------------------------------------------- */
/* Timestamps                                                                  */
/* -------------------------------------------------------------------------- */

/** 2026-09-03T09:00:00+05:30, expressed as the equivalent UTC instant. */
const BASE_EPOCH_MS = Date.UTC(2026, 8, 3, 3, 30, 0);
const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;

/** Format an epoch instant as ISO-8601 with the literal `+05:30` offset the
 * contract requires everywhere — never `Z`, per section on timestamps. */
function formatIst(epochMs: number): string {
  const shifted = new Date(epochMs + IST_OFFSET_MS);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}` +
    `T${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}:${pad(shifted.getUTCSeconds())}+05:30`
  );
}

function at(offsetSeconds: number): string {
  return formatIst(BASE_EPOCH_MS + offsetSeconds * 1000);
}

/* -------------------------------------------------------------------------- */
/* Scenario definitions                                                       */
/* -------------------------------------------------------------------------- */

type Outcome =
  /** PASS -> EXECUTED -> RESOLVED. A clean recovery. */
  | "recovered"
  /** PASS -> SCHEDULED. Parked for a future retry, nothing executed yet. */
  | "scheduled"
  /** PASS -> EXECUTED. An attempt is underway; not yet terminal. */
  | "in_flight"
  /** ACTION_CHOSEN -> CONSTRAINT_CHECKED FAILs, straight to ESCALATED. No attempt was made. */
  | "gate_rejected"
  /** A prior attempt exists (retry_count already at the cap); the gate rejects the next one. */
  | "gate_rejected_after_attempt"
  /** The policy itself chose to escalate (low confidence / no safe action) — the gate trivially PASSes an escalate. */
  | "policy_escalated";

interface Scenario {
  txnId: string;
  eventId: string;
  customer: Customer;
  amountPaise: number;
  failureCode: string;
  failureMessage: string;
  failureType: FailureType;
  method: string | null;
  issuer: string | null;
  fraudFlag: boolean;
  cause: Cause;
  confidence: number;
  source: DiagnosisSource;
  diagnosisRationale: string;
  actionType: ActionType;
  channel: Channel;
  actionReason: string;
  attempt: number;
  retryCount: number;
  scheduledForOffsetSeconds: number | null;
  constraint?: { name: ConstraintName; limitPaise: number | null; maxRetries: number | null };
  outcome: Outcome;
  /** Seconds after BASE this item's DETECTED event lands. Spaced so the whole
   * batch reads as one ~13-minute run, oldest item first. */
  startOffsetSeconds: number;
}

const RAJ: Customer = { name: "Ananya Rao", phone: "+919876543210", email: "ananya.rao@example.com" };

const SCENARIOS: Scenario[] = [
  // -- insufficient_funds (4) ------------------------------------------------
  {
    txnId: "pay_QjK9x2LmN4TzAb",
    eventId: "evt_8fH2kQpR7sVdWx",
    customer: RAJ,
    amountPaise: 249900,
    failureCode: "BAD_REQUEST_ERROR",
    failureMessage: "Your card has insufficient balance to complete this payment.",
    failureType: "subscription",
    method: "card",
    issuer: "HDFC",
    fraudFlag: false,
    cause: "insufficient_funds",
    confidence: 0.96,
    source: "rules",
    diagnosisRationale:
      "Issuer message names an insufficient balance; matched by the deterministic rules table on failure_code BAD_REQUEST_ERROR with an insufficient-balance description.",
    actionType: "scheduled_retry",
    channel: "payment_retry",
    actionReason: "Insufficient funds: retry near the salary cycle rather than immediately.",
    attempt: 2,
    retryCount: 2,
    scheduledForOffsetSeconds: null,
    outcome: "recovered",
    startOffsetSeconds: 0,
  },
  {
    txnId: "pay_Bx7mR3vTn2QkLp",
    eventId: "evt_2mN8vQxR7sTdWk",
    customer: { name: "Rohan Gupta", phone: "+919812345671", email: "rohan.gupta@example.com" },
    amountPaise: 149900,
    failureCode: "BAD_REQUEST_ERROR",
    failureMessage: "Your card has insufficient balance to complete this payment.",
    failureType: "subscription",
    method: "card",
    issuer: "ICICI",
    fraudFlag: false,
    cause: "insufficient_funds",
    confidence: 0.94,
    source: "rules",
    diagnosisRationale:
      "Issuer message names an insufficient balance; matched by the deterministic rules table.",
    actionType: "scheduled_retry",
    channel: "payment_retry",
    actionReason: "Insufficient funds: retry scheduled for the customer's typical salary-credit window.",
    attempt: 1,
    retryCount: 0,
    scheduledForOffsetSeconds: 27 * 24 * 3600,
    outcome: "scheduled",
    startOffsetSeconds: 40,
  },
  {
    txnId: "pay_Fk4wT8nYs3RcVm",
    eventId: "evt_9kP2xM5vBnHqZs",
    customer: { name: "Priya Nair", phone: "+919845098450", email: "priya.nair@example.com" },
    amountPaise: 89900,
    failureCode: "BAD_REQUEST_ERROR",
    failureMessage: "Your card has insufficient balance to complete this payment.",
    failureType: "invoice",
    method: "card",
    issuer: "SBI",
    fraudFlag: false,
    cause: "insufficient_funds",
    confidence: 0.91,
    source: "rules",
    diagnosisRationale: "Matched by the deterministic rules table on failure_code BAD_REQUEST_ERROR.",
    actionType: "scheduled_retry",
    channel: "payment_retry",
    actionReason: "Insufficient funds: retry timed to a likely credit window.",
    attempt: 1,
    retryCount: 1,
    scheduledForOffsetSeconds: null,
    outcome: "in_flight",
    startOffsetSeconds: 80,
  },
  {
    txnId: "pay_Ht6qL9wXz4NbFj",
    eventId: "evt_3sD7rK1nQmVxYt",
    customer: { name: "Karan Malhotra", phone: "+919876501234", email: "karan.malhotra@example.com" },
    amountPaise: 349900,
    failureCode: "BAD_REQUEST_ERROR",
    failureMessage: "Payment could not be completed; the issuing bank reported insufficient funds.",
    failureType: "subscription",
    method: "card",
    issuer: "Axis Bank",
    fraudFlag: false,
    cause: "insufficient_funds",
    confidence: 0.82,
    source: "llm",
    diagnosisRationale:
      "The issuer message did not match the rules table's exact insufficient-balance phrasing; Groq classified it as insufficient_funds with 0.82 confidence, above the 0.70 diagnosis threshold.",
    actionType: "scheduled_retry",
    channel: "payment_retry",
    actionReason: "Insufficient funds: retry near the salary cycle rather than immediately.",
    attempt: 1,
    retryCount: 1,
    scheduledForOffsetSeconds: null,
    outcome: "recovered",
    startOffsetSeconds: 120,
  },

  // -- gateway_degradation (4) ------------------------------------------------
  {
    txnId: "pay_Nq2wR5vTk8LmXs",
    eventId: "evt_7bC4nM9pQrStYv",
    customer: { name: "Neha Kulkarni", phone: "+919823456701", email: "neha.kulkarni@example.com" },
    amountPaise: 599000,
    failureCode: "GATEWAY_ERROR",
    failureMessage: "Payment processing failed at the issuing bank.",
    failureType: "one_time",
    method: "netbanking",
    issuer: "Kotak Mahindra",
    fraudFlag: false,
    cause: "gateway_degradation",
    confidence: 0.9,
    source: "rules",
    diagnosisRationale:
      "GATEWAY_ERROR matched the rules table's gateway-degradation entry; the route's circuit breaker was closed.",
    actionType: "backoff_retry",
    channel: "payment_retry",
    actionReason: "Gateway degradation: back off and retry once the route's breaker resets.",
    attempt: 2,
    retryCount: 2,
    scheduledForOffsetSeconds: null,
    outcome: "recovered",
    startOffsetSeconds: 160,
  },
  {
    txnId: "pay_Wv9xK3mPr6TzNq",
    eventId: "evt_5fL8dR2sVnQwXm",
    customer: { name: "Arjun Verma", phone: "+919867123450", email: "arjun.verma@example.com" },
    amountPaise: 275000,
    failureCode: "GATEWAY_ERROR",
    failureMessage: "Payment processing failed at the issuing bank.",
    failureType: "subscription",
    method: "netbanking",
    issuer: "HDFC",
    fraudFlag: false,
    cause: "gateway_degradation",
    confidence: 0.78,
    source: "llm",
    diagnosisRationale:
      "The issuer message was ambiguous between a soft decline and a genuine outage; Groq classified it as gateway_degradation at 0.78 confidence after cross-referencing the route's recent failure rate.",
    actionType: "backoff_retry",
    channel: "payment_retry",
    actionReason: "Gateway degradation: the route's breaker is open; parked until cooldown.",
    attempt: 1,
    retryCount: 0,
    scheduledForOffsetSeconds: 25 * 60,
    outcome: "scheduled",
    startOffsetSeconds: 200,
  },
  {
    txnId: "pay_Zc5tN8wVj3RkLb",
    eventId: "evt_6qH1mP4xTsDwYr",
    customer: { name: "Meera Joshi", phone: "+919812309876", email: "meera.joshi@example.com" },
    amountPaise: 199000,
    failureCode: "GATEWAY_ERROR",
    failureMessage: "Payment processing failed at the issuing bank.",
    failureType: "one_time",
    method: "netbanking",
    issuer: "ICICI",
    fraudFlag: false,
    cause: "gateway_degradation",
    confidence: 0.88,
    source: "rules",
    diagnosisRationale: "GATEWAY_ERROR matched the rules table's gateway-degradation entry.",
    actionType: "backoff_retry",
    channel: "payment_retry",
    actionReason: "Gateway degradation: back off and retry once the route's breaker resets.",
    attempt: 1,
    retryCount: 1,
    scheduledForOffsetSeconds: null,
    outcome: "in_flight",
    startOffsetSeconds: 240,
  },
  {
    txnId: "pay_Jm3rV7xQs9NkTw",
    eventId: "evt_4pW6nL2vRxKdSm",
    customer: { name: "Simran Kaur", phone: "+919845612378", email: "simran.kaur@example.com" },
    amountPaise: 320000,
    failureCode: "GATEWAY_ERROR",
    failureMessage: "Payment processing failed at the issuing bank.",
    failureType: "subscription",
    method: "netbanking",
    issuer: "Yes Bank",
    fraudFlag: false,
    cause: "gateway_degradation",
    confidence: 0.85,
    source: "rules",
    diagnosisRationale: "GATEWAY_ERROR matched the rules table's gateway-degradation entry.",
    actionType: "backoff_retry",
    channel: "payment_retry",
    actionReason: "Gateway degradation: one more backoff retry before the cap is reached.",
    attempt: 4,
    retryCount: 4,
    scheduledForOffsetSeconds: null,
    constraint: { name: "retry_cap", limitPaise: null, maxRetries: 3 },
    outcome: "gate_rejected_after_attempt",
    startOffsetSeconds: 280,
  },

  // -- soft_decline (4) --------------------------------------------------------
  {
    txnId: "pay_Rt8kD4mXv2QwPz",
    eventId: "evt_1nJ9sV6xMqTrLd",
    customer: { name: "Aditya Shah", phone: "+919823401567", email: "aditya.shah@example.com" },
    amountPaise: 199900,
    failureCode: "TRANSACTION_DECLINED",
    failureMessage: "Your bank declined this transaction. Please try again or contact your bank.",
    failureType: "one_time",
    method: "card",
    issuer: "HDFC",
    fraudFlag: false,
    cause: "soft_decline",
    confidence: 0.83,
    source: "llm",
    diagnosisRationale:
      "TRANSACTION_DECLINED carries no rules-table match; Groq read the issuer message as a generic soft decline with no fraud or balance signal, 0.83 confidence.",
    actionType: "immediate_retry",
    channel: "payment_retry",
    actionReason: "Soft decline: no clear cause given; an immediate retry is safe and often succeeds.",
    attempt: 1,
    retryCount: 1,
    scheduledForOffsetSeconds: null,
    outcome: "recovered",
    startOffsetSeconds: 320,
  },
  {
    txnId: "pay_Yb6hG2nKw5VtRs",
    eventId: "evt_0mQ3xD8vNsLwPk",
    customer: { name: "Fatima Sheikh", phone: "+919834567012", email: "fatima.sheikh@example.com" },
    amountPaise: 99900,
    failureCode: "TRANSACTION_DECLINED",
    failureMessage: "Your bank declined this transaction. Please try again or contact your bank.",
    failureType: "one_time",
    method: "upi",
    issuer: "ICICI",
    fraudFlag: false,
    cause: "soft_decline",
    confidence: 0.79,
    source: "llm",
    diagnosisRationale: "Groq read the issuer message as a generic soft decline, 0.79 confidence.",
    actionType: "immediate_retry",
    channel: "payment_retry",
    actionReason: "Soft decline: an immediate retry is safe and often succeeds.",
    attempt: 1,
    retryCount: 1,
    scheduledForOffsetSeconds: null,
    outcome: "recovered",
    startOffsetSeconds: 360,
  },
  {
    txnId: "pay_Xd4jF7pLv9TkNc",
    eventId: "evt_8rY5wK1sQxVbHm",
    customer: { name: "Vikram Rathod", phone: "+919812098765", email: "vikram.rathod@example.com" },
    amountPaise: 249900,
    failureCode: "TRANSACTION_DECLINED",
    failureMessage: "Your bank declined this transaction. Please try again or contact your bank.",
    failureType: "subscription",
    method: "card",
    issuer: "SBI",
    fraudFlag: false,
    cause: "soft_decline",
    confidence: 0.81,
    source: "llm",
    diagnosisRationale: "Groq read the issuer message as a generic soft decline, 0.81 confidence.",
    actionType: "immediate_retry",
    channel: "payment_retry",
    actionReason: "Soft decline: an immediate retry is safe and often succeeds.",
    attempt: 1,
    retryCount: 1,
    scheduledForOffsetSeconds: null,
    outcome: "in_flight",
    startOffsetSeconds: 400,
  },
  {
    txnId: "pay_Sm2vC6qJx4WrDt",
    eventId: "evt_9tZ7yN3mLsKfQb",
    customer: { name: "Ishita Bose", phone: "+919845123409", email: "ishita.bose@example.com" },
    amountPaise: 149900,
    failureCode: "TRANSACTION_DECLINED",
    failureMessage: "Your bank declined this transaction. Please try again or contact your bank.",
    failureType: "one_time",
    method: "card",
    issuer: "Kotak Mahindra",
    fraudFlag: false,
    cause: "soft_decline",
    confidence: 0.68,
    source: "llm",
    diagnosisRationale:
      "Groq's soft-decline classification came back at 0.68 confidence, below the 0.70 diagnosis threshold — treated as low-confidence rather than acted on.",
    actionType: "escalate",
    channel: "human_queue",
    actionReason: "Confidence 0.68 is below the 0.70 diagnosis threshold; routed to a human rather than guessed.",
    attempt: 0,
    retryCount: 0,
    scheduledForOffsetSeconds: null,
    outcome: "policy_escalated",
    startOffsetSeconds: 440,
  },

  // -- expired_instrument (3) ---------------------------------------------------
  {
    txnId: "pay_Lp9wB3nRx7VkTs",
    eventId: "evt_2dQ6mS8vXrNwYc",
    customer: { name: "Devika Pillai", phone: "+919823045678", email: "devika.pillai@example.com" },
    amountPaise: 499900,
    failureCode: "CARD_EXPIRED",
    failureMessage: "Your card has expired.",
    failureType: "subscription",
    method: "card",
    issuer: "HDFC",
    fraudFlag: false,
    cause: "expired_instrument",
    confidence: 0.97,
    source: "rules",
    diagnosisRationale: "CARD_EXPIRED matched the rules table's expired-instrument entry exactly.",
    actionType: "customer_nudge",
    channel: "sms",
    actionReason: "Expired instrument: retrying will never succeed; nudge the customer to update payment details.",
    attempt: 1,
    retryCount: 0,
    scheduledForOffsetSeconds: null,
    outcome: "in_flight",
    startOffsetSeconds: 480,
  },
  {
    txnId: "pay_Vq5xM9kDw2RtNb",
    eventId: "evt_7cH4rL1sPqTvXd",
    customer: { name: "Rahul Chawla", phone: "+919876123045", email: "rahul.chawla@example.com" },
    amountPaise: 999900,
    failureCode: "SUBSCRIPTION_HALTED",
    failureMessage: "Your saved payment mandate has expired and needs to be renewed.",
    failureType: "subscription",
    method: "emandate",
    issuer: "ICICI",
    fraudFlag: false,
    cause: "expired_instrument",
    confidence: 0.95,
    source: "rules",
    diagnosisRationale: "SUBSCRIPTION_HALTED matched the rules table's expired-mandate entry.",
    actionType: "customer_nudge",
    channel: "voice",
    actionReason:
      "Expired mandate on a high-value subscription: a voice nudge converts better than a text for this ticket size.",
    attempt: 1,
    retryCount: 0,
    scheduledForOffsetSeconds: null,
    outcome: "recovered",
    startOffsetSeconds: 520,
  },
  {
    txnId: "pay_Kf3nT7wYq5BsRv",
    eventId: "evt_5xM8vD2nQrLwSc",
    customer: { name: "Ananya Desai", phone: "+919812456709", email: "ananya.desai@example.com" },
    amountPaise: 199900,
    failureCode: "CARD_EXPIRED",
    failureMessage: "Your card has expired.",
    failureType: "subscription",
    method: "card",
    issuer: "SBI",
    fraudFlag: false,
    cause: "expired_instrument",
    confidence: 0.93,
    source: "rules",
    diagnosisRationale: "CARD_EXPIRED matched the rules table's expired-instrument entry.",
    actionType: "customer_nudge",
    channel: "email",
    actionReason: "Expired instrument: nudge the customer to update payment details.",
    attempt: 1,
    retryCount: 0,
    scheduledForOffsetSeconds: null,
    outcome: "in_flight",
    startOffsetSeconds: 560,
  },

  // -- fraud_flagged (2) ---------------------------------------------------------
  {
    txnId: "pay_Lp7wR2sYtK9dNv",
    eventId: "evt_demo_fraud_0001",
    customer: { name: "Sneha Iyer", phone: null, email: null },
    amountPaise: 129900,
    failureCode: "FRAUD_SUSPECTED",
    failureMessage: "Transaction flagged for suspicious activity by the issuing bank.",
    failureType: "one_time",
    method: "card",
    issuer: "IDFC First",
    fraudFlag: true,
    cause: "fraud_flagged",
    confidence: 0.99,
    source: "rules",
    diagnosisRationale: "fraud_flag was set on the inbound webhook; the rules table routes this straight to a block, no LLM call.",
    actionType: "escalate",
    channel: "human_queue",
    actionReason: "Fraud-flagged transactions are never acted on; blocked and routed to a human immediately.",
    attempt: 0,
    retryCount: 0,
    scheduledForOffsetSeconds: null,
    constraint: { name: "fraud_block", limitPaise: null, maxRetries: null },
    outcome: "gate_rejected",
    startOffsetSeconds: 600,
  },
  {
    txnId: "pay_Dw6mK4vXn8QtRj",
    eventId: "evt_demo_fraud_0002",
    customer: { name: "Manish Trivedi", phone: "+919845098123", email: "manish.trivedi@example.com" },
    amountPaise: 899900,
    failureCode: "FRAUD_SUSPECTED",
    failureMessage: "Transaction flagged for suspicious activity by the issuing bank.",
    failureType: "one_time",
    method: "card",
    issuer: "Axis Bank",
    fraudFlag: true,
    cause: "fraud_flagged",
    confidence: 0.99,
    source: "rules",
    diagnosisRationale: "fraud_flag was set on the inbound webhook; routed straight to a block.",
    actionType: "escalate",
    channel: "human_queue",
    actionReason: "Fraud-flagged transactions are never acted on; blocked and routed to a human immediately.",
    attempt: 0,
    retryCount: 0,
    scheduledForOffsetSeconds: null,
    constraint: { name: "fraud_block", limitPaise: null, maxRetries: null },
    outcome: "gate_rejected",
    startOffsetSeconds: 640,
  },

  // -- unknown (3) — includes the contract's own ₹75,000 amount-cap example ----
  {
    txnId: "pay_ZmT4vB8nQ1XcRe",
    eventId: "evt_demo_2026090314331100",
    customer: { name: "Rohit Mehta", phone: "+919812345678", email: "rohit.mehta@example.com" },
    amountPaise: 7500000,
    failureCode: "GATEWAY_ERROR",
    failureMessage: "Payment processing failed at the issuing bank.",
    failureType: "one_time",
    method: "netbanking",
    issuer: "ICICI",
    fraudFlag: false,
    cause: "unknown",
    confidence: 0.52,
    source: "llm",
    diagnosisRationale:
      "GATEWAY_ERROR at this amount did not cleanly match a rules-table entry; Groq's classification came back at 0.52 confidence, too low to commit to a specific cause. Recorded as unknown rather than guessed.",
    actionType: "immediate_retry",
    channel: "payment_retry",
    actionReason: "Low-confidence diagnosis: propose the safest bounded action and let the gate decide.",
    attempt: 0,
    retryCount: 0,
    scheduledForOffsetSeconds: null,
    constraint: { name: "amount_cap", limitPaise: 5000000, maxRetries: 3 },
    outcome: "gate_rejected",
    startOffsetSeconds: 680,
  },
  {
    txnId: "pay_Gh9xW3rTk6VmNq",
    eventId: "evt_1qL5nP8vRxTsWm",
    customer: { name: "Zara Ahmed", phone: "+919823567890", email: "zara.ahmed@example.com" },
    amountPaise: 79900,
    failureCode: "UNKNOWN_ERROR",
    failureMessage: "An unspecified error occurred while processing this payment.",
    failureType: "one_time",
    method: "card",
    issuer: "Yes Bank",
    fraudFlag: false,
    cause: "unknown",
    confidence: 0.3,
    source: "fallback",
    diagnosisRationale:
      "The Groq response failed to parse as valid JSON; fell back to the safest bounded action rather than guess a diagnosis.",
    actionType: "escalate",
    channel: "human_queue",
    actionReason: "Diagnosis unavailable: escalate rather than act without a cause.",
    attempt: 0,
    retryCount: 0,
    scheduledForOffsetSeconds: null,
    outcome: "policy_escalated",
    startOffsetSeconds: 720,
  },
  {
    txnId: "pay_Uc2vN7xKq4TmBs",
    eventId: "evt_6wR9dM3sQvLxYt",
    customer: { name: "Farhan Qureshi", phone: "+919876034521", email: "farhan.qureshi@example.com" },
    amountPaise: 159900,
    failureCode: "UNKNOWN_ERROR",
    failureMessage: "An unspecified error occurred while processing this payment.",
    failureType: "one_time",
    method: "upi",
    issuer: "HDFC",
    fraudFlag: false,
    cause: "unknown",
    confidence: 0.74,
    source: "llm",
    diagnosisRationale:
      "UNKNOWN_ERROR carries no rules-table match; Groq's best read was a transient failure at 0.74 confidence, just above the diagnosis threshold.",
    actionType: "immediate_retry",
    channel: "payment_retry",
    actionReason: "Low-confidence but above threshold: an immediate retry is the safest bounded action.",
    attempt: 1,
    retryCount: 1,
    scheduledForOffsetSeconds: null,
    outcome: "recovered",
    startOffsetSeconds: 760,
  },
];

/* -------------------------------------------------------------------------- */
/* Generator                                                                   */
/* -------------------------------------------------------------------------- */

let nextAuditId = 1;

function terminalStateFor(outcome: Outcome): State {
  switch (outcome) {
    case "recovered":
      return "RESOLVED";
    case "scheduled":
      return "SCHEDULED";
    case "in_flight":
      return "EXECUTED";
    case "gate_rejected":
    case "gate_rejected_after_attempt":
    case "policy_escalated":
      return "ESCALATED";
  }
}

function buildWorkItemAndEvents(s: Scenario): {
  workItem: WorkItem;
  events: AuditEvent[];
  escalation: Escalation | null;
  gateRejection: (WsGateRejectedPayload & { seq: number; ts: string }) | null;
} {
  const events: AuditEvent[] = [];
  const t = s.startOffsetSeconds;
  const finalState = terminalStateFor(s.outcome);

  const constraintResultForCheck: ConstraintResult =
    s.outcome === "gate_rejected" || s.outcome === "gate_rejected_after_attempt" ? "FAIL" : "PASS";
  const constraintReason =
    constraintResultForCheck === "FAIL" && s.constraint
      ? s.constraint.name === "amount_cap"
        ? `Amount cap: ${s.amountPaise} paise exceeds the ${s.constraint.limitPaise} paise limit.`
        : s.constraint.name === "fraud_block"
          ? "Fraud block: fraud_flag is set; no money action permitted."
          : `Retry cap: ${s.retryCount} attempts exceeds the ${s.constraint.maxRetries} attempt limit.`
      : `retry_count ${s.retryCount} <= 3; amount_paise ${s.amountPaise} <= 5000000; fraud_flag ${s.fraudFlag}`;

  events.push({
    id: nextAuditId++,
    timestamp: at(t),
    txn_id: s.txnId,
    from_state: null,
    to_state: "DETECTED",
    diagnosis_cause: null,
    diagnosis_confidence: null,
    action_chosen: null,
    constraint_result: null,
    constraint_reason: null,
    outcome: null,
    rationale: "Webhook payment.failed accepted; signature verified; work item created.",
  });

  events.push({
    id: nextAuditId++,
    timestamp: at(t + 2),
    txn_id: s.txnId,
    from_state: "DETECTED",
    to_state: "DIAGNOSED",
    diagnosis_cause: s.cause,
    diagnosis_confidence: s.confidence,
    action_chosen: null,
    constraint_result: null,
    constraint_reason: null,
    outcome: null,
    rationale: s.diagnosisRationale,
  });

  events.push({
    id: nextAuditId++,
    timestamp: at(t + 4),
    txn_id: s.txnId,
    from_state: "DIAGNOSED",
    to_state: "ACTION_CHOSEN",
    diagnosis_cause: s.cause,
    diagnosis_confidence: s.confidence,
    action_chosen: s.actionType,
    constraint_result: null,
    constraint_reason: null,
    outcome: null,
    rationale: s.actionReason,
  });

  events.push({
    id: nextAuditId++,
    timestamp: at(t + 6),
    txn_id: s.txnId,
    from_state: "ACTION_CHOSEN",
    to_state: "CONSTRAINT_CHECKED",
    diagnosis_cause: s.cause,
    diagnosis_confidence: s.confidence,
    action_chosen: s.actionType,
    constraint_result: constraintResultForCheck,
    constraint_reason: constraintReason,
    outcome: null,
    rationale:
      constraintResultForCheck === "FAIL"
        ? "The constraint gate evaluated the proposed action and refused it."
        : "All constraints evaluated; the proposed action is within every cap.",
  });

  let gateRejection: (WsGateRejectedPayload & { seq: number; ts: string }) | null = null;
  let escalation: Escalation | null = null;

  if (s.outcome === "gate_rejected" || s.outcome === "gate_rejected_after_attempt") {
    events.push({
      id: nextAuditId++,
      timestamp: at(t + 7),
      txn_id: s.txnId,
      from_state: "CONSTRAINT_CHECKED",
      to_state: "ESCALATED",
      diagnosis_cause: s.cause,
      diagnosis_confidence: s.confidence,
      action_chosen: s.actionType,
      constraint_result: null,
      constraint_reason: null,
      outcome: "escalated",
      rationale: `Routed to the human queue: ${constraintReason}`,
    });

    const seq = nextAuditId; // monotonic, shared numbering space with audit ids is fine for a static fixture
    gateRejection = {
      seq,
      ts: at(t + 7),
      txn_id: s.txnId,
      constraint: s.constraint!.name,
      reason: constraintReason,
      amount_paise: s.amountPaise,
      limit_paise: s.constraint!.limitPaise ?? 5000000,
      retry_count: s.retryCount,
      max_retries: s.constraint!.maxRetries ?? 3,
      fraud_flag: s.fraudFlag,
      action_type: s.actionType,
      channel: s.channel,
      next_state: "ESCALATED",
    };
    escalation = {
      txn_id: s.txnId,
      merchant_id: "acc_MerchantDemo01",
      amount_paise: s.amountPaise,
      customer_name: s.customer.name,
      cause: s.cause,
      reason: constraintReason,
      constraint_result: "FAIL",
      escalated_at: at(t + 7),
      retry_count: s.retryCount,
    };
  } else if (s.outcome === "policy_escalated") {
    events.push({
      id: nextAuditId++,
      timestamp: at(t + 7),
      txn_id: s.txnId,
      from_state: "CONSTRAINT_CHECKED",
      to_state: "ESCALATED",
      diagnosis_cause: s.cause,
      diagnosis_confidence: s.confidence,
      action_chosen: s.actionType,
      constraint_result: null,
      constraint_reason: null,
      outcome: "escalated",
      rationale: s.actionReason,
    });
    escalation = {
      txn_id: s.txnId,
      merchant_id: "acc_MerchantDemo01",
      amount_paise: s.amountPaise,
      customer_name: s.customer.name,
      cause: s.cause,
      reason: s.actionReason,
      constraint_result: "PASS",
      escalated_at: at(t + 7),
      retry_count: s.retryCount,
    };
  } else if (s.outcome === "scheduled") {
    events.push({
      id: nextAuditId++,
      timestamp: at(t + 7),
      txn_id: s.txnId,
      from_state: "CONSTRAINT_CHECKED",
      to_state: "SCHEDULED",
      diagnosis_cause: s.cause,
      diagnosis_confidence: s.confidence,
      action_chosen: s.actionType,
      constraint_result: null,
      constraint_reason: null,
      outcome: null,
      rationale: "Action passed the gate; parked for future execution.",
    });
  } else {
    // in_flight or recovered both execute first.
    events.push({
      id: nextAuditId++,
      timestamp: at(t + 7),
      txn_id: s.txnId,
      from_state: "CONSTRAINT_CHECKED",
      to_state: "EXECUTED",
      diagnosis_cause: s.cause,
      diagnosis_confidence: s.confidence,
      action_chosen: s.actionType,
      constraint_result: null,
      constraint_reason: null,
      outcome: null,
      rationale: `${s.channel} channel invoked.`,
    });
    if (s.outcome === "recovered") {
      events.push({
        id: nextAuditId++,
        timestamp: at(t + 9),
        txn_id: s.txnId,
        from_state: "EXECUTED",
        to_state: "RESOLVED",
        diagnosis_cause: s.cause,
        diagnosis_confidence: s.confidence,
        action_chosen: s.actionType,
        constraint_result: null,
        constraint_reason: null,
        outcome: "recovered",
        rationale: `Retry captured ${s.amountPaise} paise; provider reference ${s.txnId}/rt${s.attempt}.`,
      });
    }
  }

  const action: Action | null =
    s.actionType === "no_action"
      ? null
      : {
          type: s.actionType,
          channel: s.channel,
          scheduled_for: s.scheduledForOffsetSeconds !== null ? at(t + s.scheduledForOffsetSeconds) : null,
          attempt: s.attempt,
          reason: s.actionReason,
        };

  const workItem: WorkItem = {
    txn_id: s.txnId,
    event_id: s.eventId,
    merchant_id: "acc_MerchantDemo01",
    amount_paise: s.amountPaise,
    currency: "INR",
    failure_code: s.failureCode,
    failure_message: s.failureMessage,
    failure_type: s.failureType,
    method: s.method,
    issuer: s.issuer,
    customer: s.customer,
    fraud_flag: s.fraudFlag,
    created_at: at(t),
    state: finalState,
    retry_count: s.retryCount,
    diagnosis: {
      cause: s.cause,
      confidence: s.confidence,
      rationale: s.diagnosisRationale,
      source: s.source,
    },
    action,
  };

  return { workItem, events, escalation, gateRejection };
}

const GENERATED = SCENARIOS.map(buildWorkItemAndEvents);

/** Newest-first, matching what `useRecoupStream`'s live state looks like. */
export const FIXTURE_WORK_ITEMS: WorkItem[] = GENERATED.map((g) => g.workItem)
  .slice()
  .reverse();

/** Newest-first — the same convention `StreamState.auditEvents` uses. */
export const FIXTURE_AUDIT_EVENTS: AuditEvent[] = GENERATED.flatMap((g) => g.events)
  .slice()
  .sort((a, b) => b.id - a.id);

/** Newest-first. */
export const FIXTURE_ESCALATIONS: Escalation[] = GENERATED.map((g) => g.escalation)
  .filter((e): e is Escalation => e !== null)
  .slice()
  .reverse();

/** Alias with the name the exception-list panel talks about. Same rows as
 * `FIXTURE_ESCALATIONS` — see the `ExceptionRecord` comment in `types.ts` for why. */
export const FIXTURE_EXCEPTIONS = FIXTURE_ESCALATIONS;

/** Newest-first. */
export const FIXTURE_GATE_REJECTIONS: (WsGateRejectedPayload & { seq: number; ts: string })[] = GENERATED.map(
  (g) => g.gateRejection,
)
  .filter((g): g is WsGateRejectedPayload & { seq: number; ts: string } => g !== null)
  .slice()
  .reverse();

/* -------------------------------------------------------------------------- */
/* Metrics — derived, not hand-typed, so the totals can't drift               */
/* -------------------------------------------------------------------------- */

function computeMetrics(): Metrics {
  const items = SCENARIOS;
  const attempted = new Set<Outcome>(["recovered", "in_flight", "gate_rejected_after_attempt"]);
  const recoveredOutcomes = new Set<Outcome>(["recovered"]);

  const byCause = new Map<Cause, { count: number; recovered: number; recoveredPaise: number }>();
  const byChannel = new Map<Channel, { attempted: number; recovered: number; recoveredPaise: number }>();

  let totalFailedPaise = 0;
  let attemptedCount = 0;
  let recoveredCount = 0;
  let recoveredPaise = 0;
  let escalatedCount = 0;
  let gateRejectionCount = 0;
  let inFlightCount = 0;

  for (const item of items) {
    totalFailedPaise += item.amountPaise;

    const wasAttempted = attempted.has(item.outcome);
    const wasRecovered = recoveredOutcomes.has(item.outcome);
    if (wasAttempted) attemptedCount += 1;
    if (wasRecovered) {
      recoveredCount += 1;
      recoveredPaise += item.amountPaise;
    }
    if (item.outcome === "gate_rejected" || item.outcome === "gate_rejected_after_attempt" || item.outcome === "policy_escalated") {
      escalatedCount += 1;
    }
    if (item.outcome === "gate_rejected" || item.outcome === "gate_rejected_after_attempt") {
      gateRejectionCount += 1;
    }
    if (item.outcome === "scheduled" || item.outcome === "in_flight") {
      inFlightCount += 1;
    }

    const causeBucket = byCause.get(item.cause) ?? { count: 0, recovered: 0, recoveredPaise: 0 };
    causeBucket.count += 1;
    if (wasRecovered) {
      causeBucket.recovered += 1;
      causeBucket.recoveredPaise += item.amountPaise;
    }
    byCause.set(item.cause, causeBucket);

    const channelBucket = byChannel.get(item.channel) ?? { attempted: 0, recovered: 0, recoveredPaise: 0 };
    if (wasAttempted) {
      channelBucket.attempted += 1;
      if (wasRecovered) {
        channelBucket.recovered += 1;
        channelBucket.recoveredPaise += item.amountPaise;
      }
    }
    byChannel.set(item.channel, channelBucket);
  }

  // Every channel in the vocabulary appears in the breakdown, even at zero —
  // matching the contract's own by_channel example, which lists human_queue
  // with attempted: 0, recovered: 0 rather than omitting it.
  const allChannels: Channel[] = ["payment_retry", "voice", "sms", "email", "human_queue"];
  for (const channel of allChannels) {
    if (!byChannel.has(channel)) byChannel.set(channel, { attempted: 0, recovered: 0, recoveredPaise: 0 });
  }
  const allCauses: Cause[] = [
    "insufficient_funds",
    "gateway_degradation",
    "soft_decline",
    "expired_instrument",
    "fraud_flagged",
    "unknown",
  ];
  for (const cause of allCauses) {
    if (!byCause.has(cause)) byCause.set(cause, { count: 0, recovered: 0, recoveredPaise: 0 });
  }

  return {
    total_failed: items.length,
    total_failed_paise: totalFailedPaise,
    attempted: attemptedCount,
    recovered: recoveredCount,
    recovered_paise: recoveredPaise,
    recovery_rate: attemptedCount === 0 ? 0 : Math.round((recoveredCount / attemptedCount) * 100) / 100,
    escalated: escalatedCount,
    gate_rejections: gateRejectionCount,
    in_flight: inFlightCount,
    by_cause: allCauses.map((cause) => ({
      cause,
      count: byCause.get(cause)!.count,
      recovered: byCause.get(cause)!.recovered,
      recovered_paise: byCause.get(cause)!.recoveredPaise,
    })),
    by_channel: allChannels.map((channel) => ({
      channel,
      attempted: byChannel.get(channel)!.attempted,
      recovered: byChannel.get(channel)!.recovered,
      recovered_paise: byChannel.get(channel)!.recoveredPaise,
    })),
    generated_at: at(800),
  };
}

export const FIXTURE_METRICS: Metrics = computeMetrics();

export const FIXTURE_BATCH_RUN: BatchRun = {
  run_id: "run_2026090309000001",
  status: "completed",
  size: SCENARIOS.length,
  seed: 20260903,
  processed: SCENARIOS.length,
  started_at: at(0),
  finished_at: at(800),
  metrics: {
    total_failed: FIXTURE_METRICS.total_failed,
    total_failed_paise: FIXTURE_METRICS.total_failed_paise,
    attempted: FIXTURE_METRICS.attempted,
    recovered: FIXTURE_METRICS.recovered,
    recovered_paise: FIXTURE_METRICS.recovered_paise,
    recovery_rate: FIXTURE_METRICS.recovery_rate,
    escalated: FIXTURE_METRICS.escalated,
    gate_rejections: FIXTURE_METRICS.gate_rejections,
  },
};
