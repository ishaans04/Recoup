import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import ItemDetailPanel from "@/components/console/ItemDetailPanel";
import type { AuditEvent, WorkItem } from "@/lib/types";

const ITEM: WorkItem = {
  txn_id: "pay_ZmT4vB8nQ1XcRe",
  event_id: "evt_demo",
  merchant_id: "merch_1",
  amount_paise: 7_500_000,
  currency: "INR",
  failure_code: "GATEWAY_ERROR",
  failure_message: "Payment processing failed at the issuing bank.",
  failure_type: "one_time",
  method: "netbanking",
  issuer: "ICICI",
  customer: { name: "Rohit Mehta", phone: null, email: null },
  fraud_flag: false,
  created_at: "2026-09-05T14:33:00+05:30",
  state: "ESCALATED",
  retry_count: 0,
  diagnosis: { cause: "unknown", confidence: 0.52, rationale: "low confidence", source: "llm" },
  action: null,
};

const EVENTS: AuditEvent[] = [
  {
    id: 1,
    timestamp: "2026-09-05T14:33:00+05:30",
    txn_id: ITEM.txn_id,
    from_state: "ACTION_CHOSEN",
    to_state: "CONSTRAINT_CHECKED",
    diagnosis_cause: "unknown",
    diagnosis_confidence: 0.52,
    action_chosen: "immediate_retry",
    constraint_result: "FAIL",
    constraint_reason: "amount_cap: Rs 75,000 > Rs 50,000",
    outcome: null,
    rationale: "The amount cap refused this action before any channel was reached.",
  },
];

describe("ItemDetailPanel", () => {
  afterEach(cleanup);

  it("renders the audit chain columns PRD 8.8 asks for", () => {
    render(
      <ItemDetailPanel item={ITEM} events={EVENTS} refused diagnosisSource="llm" />,
    );
    for (const column of ["time", "event", "diagnosis", "action", "gate", "result"]) {
      expect(screen.getByText(column)).toBeInTheDocument();
    }
  });

  it("shows the diagnosis confidence and which tier produced it", () => {
    // PRD 11's two-tier engine has to be visible, not merely claimed: a reader
    // must be able to see that this row needed a model, not the rules table.
    render(
      <ItemDetailPanel item={ITEM} events={EVENTS} refused diagnosisSource="llm" />,
    );
    const row = screen.getByTestId("transition-row");
    expect(row).toHaveTextContent("52%");
    expect(row).toHaveTextContent("LLM");
  });

  it("shows the gate's verdict as a FAIL badge", () => {
    render(
      <ItemDetailPanel item={ITEM} events={EVENTS} refused diagnosisSource="llm" />,
    );
    expect(screen.getByTestId("transition-row")).toHaveTextContent("FAIL");
  });

  it("reveals the full rationale when a row is expanded", () => {
    render(
      <ItemDetailPanel item={ITEM} events={EVENTS} refused diagnosisSource="llm" />,
    );
    const row = screen.getByTestId("transition-row");
    expect(screen.queryByText(/before any channel was reached/)).toBeNull();

    fireEvent.click(row);
    expect(screen.getByText(/before any channel was reached/)).toBeInTheDocument();
    expect(row).toHaveAttribute("aria-expanded", "true");
  });

  it("relabels the act node Escalate on a refused run", () => {
    // Past the refusal this run is no longer a recovery, and the pipeline
    // should not imply an action was taken.
    render(
      <ItemDetailPanel item={ITEM} events={EVENTS} refused diagnosisSource="llm" />,
    );
    expect(screen.getByText("Escalate")).toBeInTheDocument();
    expect(screen.queryByText("Act")).toBeNull();
  });

  it("prompts for a selection when nothing is selected", () => {
    render(<ItemDetailPanel item={null} events={[]} refused={false} diagnosisSource={null} />);
    expect(screen.getByText(/select a row above/i)).toBeInTheDocument();
  });
});
