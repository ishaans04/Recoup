import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import ConstraintRejectionsPanel, {
  type GateRejectionView,
} from "@/components/console/ConstraintRejectionsPanel";

function rejection(overrides: Partial<GateRejectionView> = {}): GateRejectionView {
  return {
    seq: 41,
    ts: new Date().toISOString(),
    txn_id: "pay_ZmT4vB8nQ1XcRe",
    constraint: "amount_cap",
    reason: "amount_cap: Rs 75,000 > Rs 50,000",
    amount_paise: 7_500_000,
    limit_paise: 5_000_000,
    retry_count: 0,
    max_retries: 3,
    fraud_flag: false,
    action_type: "immediate_retry",
    channel: "payment_retry",
    next_state: "ESCALATED",
    ...overrides,
  };
}

describe("ConstraintRejectionsPanel", () => {
  afterEach(cleanup);

  it("puts the PRD's worked example on screen verbatim", () => {
    // PRD 12.4 / 16.5: `Amount Cap: Rs 75,000 > Rs 50,000 ✗ -> HALT -> Escalate`
    // is the demo-critical line. The gate has to be *seen* saying no.
    render(<ConstraintRejectionsPanel rejections={[rejection()]} />);
    const row = screen.getByTestId("gate-rejection-row");
    expect(row).toHaveTextContent("Amount Cap: Rs 75,000 > Rs 50,000");
    expect(row).toHaveTextContent("✗");
    expect(row).toHaveTextContent("HALT");
    expect(row).toHaveTextContent("Escalate");
  });

  it("states that no GatePass was minted", () => {
    render(<ConstraintRejectionsPanel rejections={[rejection()]} />);
    expect(screen.getByTestId("gate-rejection-row")).toHaveTextContent("no GatePass minted");
  });

  it("renders the comparison clause for each constraint shape", () => {
    render(
      <ConstraintRejectionsPanel
        rejections={[
          rejection({ constraint: "retry_cap", retry_count: 4, max_retries: 3, seq: 1 }),
          rejection({ constraint: "fraud_block", seq: 2, txn_id: "pay_fraud" }),
        ]}
      />,
    );
    expect(screen.getByText(/Retry Cap: 4 attempts > 3 max/)).toBeInTheDocument();
    expect(screen.getByText(/Fraud Block: fraud_flag = true/)).toBeInTheDocument();
  });

  it("stays on screen when the gate has refused nothing", () => {
    // A panel that only appears on failure teaches a viewer nothing about what
    // it watches; "0 refusals" is itself a claim worth making.
    render(<ConstraintRejectionsPanel rejections={[]} />);
    expect(screen.getByText(/0 refused/)).toBeInTheDocument();
    expect(screen.getByText(/refused nothing yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId("gate-rejection-row")).toBeNull();
  });
});
