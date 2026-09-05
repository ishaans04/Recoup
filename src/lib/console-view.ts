/**
 * The console's view model: pure functions turning contract types into the
 * things the operations surface draws.
 *
 * This is the only place the eight-state lifecycle is projected onto the six
 * nodes the console renders, and the only place an `AuditEvent` is given the
 * dotted event name the live stream shows. Both projections are lossy on
 * purpose — the pipeline graphic has six columns and the stream has one line
 * per row — so they live here, together, where the mapping can be read and
 * tested as a unit rather than being reinvented inside three components.
 *
 * Nothing here computes money and nothing here reaches the network.
 */

import type { AuditEvent, ConstraintName, State, WorkItem } from "./types";

/** The six nodes of the pipeline graphic, left to right. */
export const NODE_LABELS = ["Detect", "Diagnose", "Decide", "Gate", "Act", "Audit"] as const;

/**
 * Which pipeline node a work item has reached.
 *
 * `SCHEDULED` shares node 3 with `CONSTRAINT_CHECKED`: both mean the gate has
 * returned and the action has not run yet, and the console draws that as "past
 * the gate, not yet acted". `ESCALATED` maps to the last node like `RESOLVED`
 * does — an escalation is a completed run with a terminal audit row, not an
 * unfinished one, and colouring it as still in flight would misrepresent it.
 */
export const STATE_STAGE: Record<State, number> = {
  DETECTED: 0,
  DIAGNOSED: 1,
  ACTION_CHOSEN: 2,
  CONSTRAINT_CHECKED: 3,
  SCHEDULED: 3,
  EXECUTED: 4,
  RESOLVED: 5,
  ESCALATED: 5,
};

/** `[text, border]` for a state pill. Severity reads by hue. */
export const STATE_COLORS: Record<State, readonly [string, string]> = {
  RESOLVED: ["oklch(0.86 0.13 145)", "oklch(0.86 0.13 145 / 0.32)"],
  ESCALATED: ["oklch(0.88 0.12 75)", "oklch(0.88 0.12 75 / 0.34)"],
  SCHEDULED: ["oklch(0.82 0.1 258)", "oklch(0.82 0.1 258 / 0.32)"],
  EXECUTED: ["oklch(0.88 0.1 197)", "oklch(0.88 0.1 197 / 0.32)"],
  CONSTRAINT_CHECKED: ["oklch(0.88 0.1 197)", "oklch(0.88 0.1 197 / 0.32)"],
  DETECTED: ["oklch(0.84 0.11 300)", "oklch(0.84 0.11 300 / 0.32)"],
  DIAGNOSED: ["oklch(0.84 0.11 300)", "oklch(0.84 0.11 300 / 0.32)"],
  ACTION_CHOSEN: ["oklch(0.84 0.11 300)", "oklch(0.84 0.11 300 / 0.32)"],
};

/** The oklch hue a work item's pipeline is drawn in. */
export const STATE_HUE: Record<State, number> = {
  RESOLVED: 145,
  ESCALATED: 75,
  SCHEDULED: 258,
  EXECUTED: 197,
  CONSTRAINT_CHECKED: 197,
  DETECTED: 300,
  DIAGNOSED: 300,
  ACTION_CHOSEN: 300,
};

/** Fallback for a state the frontend does not recognise (contract rule 5.4:
 *  render it, never drop it). */
const UNKNOWN_STATE_COLORS = ["#fff", "rgba(255,255,255,0.2)"] as const;

export function stateColors(state: State): readonly [string, string] {
  return STATE_COLORS[state] ?? UNKNOWN_STATE_COLORS;
}

export function stateHue(state: State): number {
  return STATE_HUE[state] ?? 300;
}

export function stateStage(state: State): number {
  return STATE_STAGE[state] ?? 0;
}

/** Colour per event name in the live stream. */
export const EVENT_COLORS: Record<string, string> = {
  "gate.rejected": "oklch(0.88 0.12 75)",
  "workitem.escalated": "oklch(0.88 0.12 75)",
  "gate.passed": "oklch(0.86 0.13 145)",
  "workitem.resolved": "oklch(0.86 0.13 145)",
  "audit.appended": "oklch(0.86 0.1 197)",
  "metrics.updated": "oklch(0.84 0.11 300)",
};

export function eventColor(type: string): string {
  return EVENT_COLORS[type] ?? "rgba(233,233,240,0.85)";
}

/**
 * Name one audit row the way the stream labels it.
 *
 * A refusal is checked before anything else: the row that carries
 * `constraint_result: "FAIL"` is also the row whose `to_state` is `ESCALATED`,
 * and of those two facts the refusal is the one an operator needs to see. The
 * generic `audit.appended` is the floor, never a dropped row.
 */
export function auditEventType(event: AuditEvent): string {
  if (event.constraint_result === "FAIL") return "gate.rejected";
  if (event.to_state === "RESOLVED") return "workitem.resolved";
  if (event.to_state === "ESCALATED") return "workitem.escalated";
  if (event.constraint_result === "PASS") return "gate.passed";
  switch (event.to_state) {
    case "DETECTED":
      return "payment.failed";
    case "DIAGNOSED":
      return "diagnosis.made";
    case "ACTION_CHOSEN":
      return "action.selected";
    case "SCHEDULED":
      return "action.scheduled";
    case "EXECUTED":
      return "action.executed";
    default:
      return "audit.appended";
  }
}

/**
 * The one-line detail the stream and the transition list show. The gate's own
 * words win when the gate spoke, then the recorded outcome, then the rationale
 * every row is guaranteed to carry.
 */
export function auditEventDetail(event: AuditEvent): string {
  return event.constraint_reason ?? event.outcome ?? event.rationale;
}

/** `HH:MM:SS` in the viewer's timezone, or the raw string if it will not parse. */
export function formatClock(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

/** The console's four row filters. */
export type WorkItemFilter = "all" | "in flight" | "resolved" | "escalated";

export const WORK_ITEM_FILTERS: WorkItemFilter[] = ["all", "in flight", "resolved", "escalated"];

/** In flight is "not terminal": still moving through the machine. */
export function matchesFilter(item: WorkItem, filter: WorkItemFilter): boolean {
  switch (filter) {
    case "all":
      return true;
    case "resolved":
      return item.state === "RESOLVED";
    case "escalated":
      return item.state === "ESCALATED";
    case "in flight":
      return item.state !== "RESOLVED" && item.state !== "ESCALATED";
  }
}

/** The three hard caps from PRD 12.2, in the order the gate evaluates them. */
export const GATE_RULES: { constraint: ConstraintName; label: string }[] = [
  { constraint: "retry_cap", label: "retry_count ≤ 3" },
  { constraint: "amount_cap", label: "amount ≤ ₹50,000" },
  { constraint: "fraud_block", label: "fraud_flag == false" },
];

/**
 * A short action summary for the work-items table: what was chosen, and when it
 * is due if it has not run yet.
 */
export function actionSummary(item: WorkItem): string {
  if (!item.action) return "—";
  const type = item.action.type.replace(/_/g, " ");
  if (item.action.channel === "human_queue") return "human queue";
  if (item.action.scheduled_for && item.state === "SCHEDULED") {
    const at = new Date(item.action.scheduled_for);
    if (!Number.isNaN(at.getTime())) {
      const day = at.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
      return `${type} · ${day} ${formatClock(item.action.scheduled_for).slice(0, 5)}`;
    }
  }
  if (item.action.attempt > 0) return `${type} · attempt ${item.action.attempt}`;
  return type;
}
