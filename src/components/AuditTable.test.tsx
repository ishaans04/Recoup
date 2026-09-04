import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import AuditTable from "@/components/AuditTable";
import type { AuditEvent } from "@/lib/types";

function row(id: number, txn: string): AuditEvent {
  return {
    id,
    timestamp: "2026-09-04T10:00:00+05:30",
    txn_id: txn,
    from_state: "DETECTED",
    to_state: "DIAGNOSED",
    diagnosis_cause: "insufficient_funds",
    diagnosis_confidence: 0.96,
    action_chosen: null,
    constraint_result: null,
    constraint_reason: null,
    outcome: null,
    rationale: `row ${id}`,
  };
}

describe("AuditTable", () => {
  afterEach(cleanup);

  it("renders rows in the newest-first order it is given", () => {
    // The page and the live stream both hand this table newest-first; the table
    // must preserve that order rather than re-sorting.
    const events = [row(2, "pay_newest"), row(1, "pay_oldest")];
    render(<AuditTable events={events} />);
    const rows = screen.getAllByTestId("audit-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("pay_newest");
    expect(rows[1]).toHaveTextContent("pay_oldest");
  });

  it("shows the two-tier diagnosis source badge when a source is provided", () => {
    render(
      <AuditTable events={[row(1, "pay_a")]} diagnosisSourceByTxnId={{ pay_a: "rules" }} />,
    );
    expect(screen.getByText("RULES")).toBeInTheDocument();
  });

  it("renders an empty state when there are no events", () => {
    render(<AuditTable events={[]} />);
    expect(screen.getByText(/no audit events yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId("audit-row")).toBeNull();
  });
});
