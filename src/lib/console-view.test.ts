import { describe, expect, it } from "vitest";

import {
  actionSummary,
  auditEventDetail,
  auditEventType,
  formatClock,
  matchesFilter,
  stateHue,
  stateStage,
} from "./console-view";
import type { AuditEvent, State, WorkItem } from "./types";

function event(overrides: Partial<AuditEvent> = {}): AuditEvent {
  return {
    id: 1,
    timestamp: "2026-09-05T14:33:11+05:30",
    txn_id: "pay_test",
    from_state: "CONSTRAINT_CHECKED",
    to_state: "ESCALATED",
    diagnosis_cause: "insufficient_funds",
    diagnosis_confidence: 0.96,
    action_chosen: "scheduled_retry",
    constraint_result: null,
    constraint_reason: null,
    outcome: null,
    rationale: "a rationale is always present",
    ...overrides,
  };
}

function workItem(overrides: Partial<WorkItem> = {}): WorkItem {
  return {
    txn_id: "pay_test",
    event_id: "evt_test",
    merchant_id: "merch_1",
    amount_paise: 249900,
    currency: "INR",
    failure_code: "BAD_REQUEST_ERROR",
    failure_message: "insufficient balance",
    failure_type: "subscription",
    method: "card",
    issuer: "HDFC",
    customer: { name: "Test", phone: null, email: null },
    fraud_flag: false,
    created_at: "2026-09-05T14:00:00+05:30",
    state: "RESOLVED",
    retry_count: 0,
    diagnosis: null,
    action: null,
    ...overrides,
  };
}

describe("stateStage", () => {
  it("puts SCHEDULED and CONSTRAINT_CHECKED on the same node", () => {
    // Both mean "the gate has returned, the action has not run yet", which is
    // one column in a six-node pipeline.
    expect(stateStage("SCHEDULED")).toBe(stateStage("CONSTRAINT_CHECKED"));
  });

  it("treats both terminal states as fully walked", () => {
    // An escalation is a completed run with a terminal audit row, not an
    // unfinished one; drawing it short would misrepresent it.
    expect(stateStage("ESCALATED")).toBe(5);
    expect(stateStage("RESOLVED")).toBe(5);
  });

  it("advances monotonically along the happy path", () => {
    const path: State[] = [
      "DETECTED",
      "DIAGNOSED",
      "ACTION_CHOSEN",
      "CONSTRAINT_CHECKED",
      "EXECUTED",
      "RESOLVED",
    ];
    const stages = path.map(stateStage);
    expect(stages).toEqual([...stages].sort((a, b) => a - b));
  });
});

describe("stateHue", () => {
  it("gives escalations the refusal hue and resolutions the success hue", () => {
    expect(stateHue("ESCALATED")).toBe(75);
    expect(stateHue("RESOLVED")).toBe(145);
  });
});

describe("auditEventType", () => {
  it("names a refusal gate.rejected even though the row also escalates", () => {
    // The row carrying constraint_result FAIL is the same row whose to_state is
    // ESCALATED. Of those two facts the refusal is the one to surface.
    const row = event({ constraint_result: "FAIL", to_state: "ESCALATED" });
    expect(auditEventType(row)).toBe("gate.rejected");
  });

  it("names a passing gate check gate.passed", () => {
    expect(
      auditEventType(event({ constraint_result: "PASS", to_state: "CONSTRAINT_CHECKED" })),
    ).toBe("gate.passed");
  });

  it("names each lifecycle transition", () => {
    expect(auditEventType(event({ to_state: "DETECTED", from_state: null }))).toBe(
      "payment.failed",
    );
    expect(auditEventType(event({ to_state: "DIAGNOSED" }))).toBe("diagnosis.made");
    expect(auditEventType(event({ to_state: "ACTION_CHOSEN" }))).toBe("action.selected");
    expect(auditEventType(event({ to_state: "SCHEDULED" }))).toBe("action.scheduled");
    expect(auditEventType(event({ to_state: "EXECUTED" }))).toBe("action.executed");
    expect(auditEventType(event({ to_state: "RESOLVED" }))).toBe("workitem.resolved");
    expect(auditEventType(event({ to_state: "ESCALATED" }))).toBe("workitem.escalated");
  });
});

describe("auditEventDetail", () => {
  it("prefers the gate's own words when the gate spoke", () => {
    const row = event({
      constraint_result: "FAIL",
      constraint_reason: "amount_cap: Rs 75,000 > Rs 50,000",
      outcome: "escalated",
    });
    expect(auditEventDetail(row)).toBe("amount_cap: Rs 75,000 > Rs 50,000");
  });

  it("falls back to the outcome, then to the always-present rationale", () => {
    expect(auditEventDetail(event({ outcome: "captured" }))).toBe("captured");
    expect(auditEventDetail(event())).toBe("a rationale is always present");
  });
});

describe("matchesFilter", () => {
  it("counts every non-terminal state as in flight", () => {
    expect(matchesFilter(workItem({ state: "SCHEDULED" }), "in flight")).toBe(true);
    expect(matchesFilter(workItem({ state: "DIAGNOSED" }), "in flight")).toBe(true);
    expect(matchesFilter(workItem({ state: "RESOLVED" }), "in flight")).toBe(false);
    expect(matchesFilter(workItem({ state: "ESCALATED" }), "in flight")).toBe(false);
  });

  it("keeps everything under the all filter", () => {
    expect(matchesFilter(workItem({ state: "ESCALATED" }), "all")).toBe(true);
  });
});

describe("formatClock", () => {
  it("renders a zero-padded wall clock", () => {
    expect(formatClock("2026-09-05T04:07:09+05:30")).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });

  it("returns an unparseable timestamp verbatim rather than NaN", () => {
    // Contract rule 5.4: render what you were given, never drop the row.
    expect(formatClock("not-a-date")).toBe("not-a-date");
  });
});

describe("actionSummary", () => {
  it("reads em-dash when no action has been chosen yet", () => {
    expect(actionSummary(workItem({ action: null }))).toBe("—");
  });

  it("names the human queue rather than the action type", () => {
    const item = workItem({
      action: {
        type: "escalate",
        channel: "human_queue",
        scheduled_for: null,
        attempt: 0,
        reason: "gate refused",
      },
    });
    expect(actionSummary(item)).toBe("human queue");
  });

  it("shows the attempt number on a repeated action", () => {
    const item = workItem({
      state: "EXECUTED",
      action: {
        type: "backoff_retry",
        channel: "payment_retry",
        scheduled_for: null,
        attempt: 2,
        reason: "gateway degraded",
      },
    });
    expect(actionSummary(item)).toBe("backoff retry · attempt 2");
  });
});
