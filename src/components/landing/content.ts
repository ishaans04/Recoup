/**
 * Everything the landing page states about the system, in one place.
 *
 * The figures here are not illustrative. They are the aggregates of the
 * twenty-transaction preview batch in `src/lib/fixtures.ts` — the same dataset
 * the console renders when the backend is not reachable — so the headline on
 * the landing page and the numbers in the console can never disagree. The three
 * flow lanes are three real transactions from that batch, quoted by their actual
 * ids, causes and outcomes.
 *
 * The recovery rate is 54%, not 100%, and six of twenty transactions end in the
 * human queue. That is the honest result the PRD demands (13.4): a batch that
 * recovers everything is a broken batch, not a good one.
 */

/** Aggregates of the preview batch. Mirrors FIXTURE_METRICS exactly. */
export const TARGETS = {
  /** Integer paise, as everywhere else in this system. */
  recoveredPaise: 2_658_400,
  recoveredTxns: 7,
  /** Percent, for display. attempted 13 -> recovered 7. */
  rate: 54,
  processed: 20,
  escalations: 6,
  exceptions: 6,
  rejections: 4,
  auditEvents: 107,
} as const;

export interface Lane {
  id: string;
  amount: string;
  cause: string;
  tier: string;
  /** oklch hue the lane's pipeline is drawn in. */
  hue: number;
  outState: string;
  outcome: string;
  /** Label for node 5, which is the action actually taken. */
  actLabel: string;
  /** True when the gate refused, which recolours the pipeline from the gate on. */
  refuse: boolean;
}

export const NODE_LABELS = ["Detect", "Diagnose", "Decide", "Gate", "Act", "Audit"] as const;

export const LANES: Lane[] = [
  {
    id: "pay_QjK9x2LmN4TzAb",
    amount: "₹2,499",
    cause: "insufficient_funds",
    tier: "tier 1 · rules table · 0.96",
    hue: 197,
    outState: "RESOLVED",
    outcome: "retry scheduled inside the salary-cycle window, not at 2am",
    actLabel: "Retry",
    refuse: false,
  },
  {
    id: "pay_Lp9wB3nRx7VkTs",
    amount: "₹4,999",
    cause: "expired_instrument",
    tier: "tier 1 · rules table · 0.97",
    hue: 328,
    outState: "RESOLVED",
    outcome: "retrying can never work — customer nudged to update the card",
    actLabel: "Nudge",
    refuse: false,
  },
  {
    id: "pay_ZmT4vB8nQ1XcRe",
    amount: "₹75,000",
    cause: "unknown",
    tier: "tier 2 · Groq · confidence 0.52",
    hue: 75,
    outState: "ESCALATED",
    outcome: "gate refused — amount_cap: ₹75,000 > ₹50,000 → human queue",
    actLabel: "Escalate",
    refuse: true,
  },
];

export interface Benefit {
  num: string;
  title: string;
  body: string;
  proof: string;
}

export const BENEFITS: Benefit[] = [
  {
    num: "01",
    title: "One action per failure, not a retry storm",
    body: "The cause picks the action: a retry near payday, a back-off behind a circuit breaker, a nudge on a channel the customer can actually receive, or a human.",
    proof: "policy/selector.py · cause → action",
  },
  {
    num: "02",
    title: "The model can never move money",
    body: "The LLM's entire authority is returning a Diagnosis. Everything downstream is deterministic and bounded, so an unlucky model response cannot select an action nobody authorised.",
    proof: "unknown is an explicitly correct answer",
  },
  {
    num: "03",
    title: "Every rupee movement passes one door",
    body: "ActionExecutor.execute() demands a GatePass — a frozen object carrying an HMAC only ConstraintGate.check() can mint. An AST test fails the build if anything else imports a channel.",
    proof: "tests/architecture/test_single_door.py",
  },
  {
    num: "04",
    title: "The audit log physically cannot be rewritten",
    body: "SQLite BEFORE UPDATE / BEFORE DELETE triggers RAISE(ABORT) on audit_events. A test issues a raw UPDATE and watches the database refuse it.",
    proof: "append-only · reconstructs any run",
  },
  {
    num: "05",
    title: "Duplicates and unsigned traffic die at the edge",
    body: "Ingestion verifies the signature before parsing and dedupes on event_id, so a webhook delivered twice never starts a second recovery and a wrong secret never reaches the parser.",
    proof: "idempotent · signature-first",
  },
  {
    num: "06",
    title: "Metrics you can hand to a reviewer",
    body: "Every batch report ships the full exception list with reasons. Money is integer paise end to end; the UI divides by 100 only at the point of display.",
    proof: "6 of 20 escalated · every one with a reason",
  },
];

export const TICKERS: string[] = [
  "ws://…/ws · audit.appended · workitem.updated · gate.rejected",
  "ws://…/ws · metrics.updated · recovery_rate 0.54 · exceptions 6",
  "ws://…/ws · backfill-on-reconnect replayed 3 events · sequence intact",
];

/** Indian lakh grouping: 1,84,62,500 rather than 18,462,500. */
export function inr(value: number): string {
  const s = String(Math.round(value));
  if (s.length <= 3) return s;
  const last3 = s.slice(-3);
  let rest = s.slice(0, -3);
  const parts: string[] = [];
  while (rest.length > 2) {
    parts.unshift(rest.slice(-2));
    rest = rest.slice(0, -2);
  }
  if (rest) parts.unshift(rest);
  return `${parts.join(",")},${last3}`;
}
