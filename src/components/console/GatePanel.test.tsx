import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import GatePanel from "@/components/console/GatePanel";
import type { ConstraintName } from "@/lib/types";

function rejections(...names: ConstraintName[]) {
  return names.map((constraint) => ({ constraint }));
}

describe("GatePanel", () => {
  afterEach(cleanup);

  it("shows every hard cap even when nothing has breached", () => {
    render(<GatePanel rejections={[]} />);
    const rules = screen.getAllByTestId("gate-rule");
    expect(rules).toHaveLength(3);
    expect(screen.getByText("retry_count ≤ 3")).toBeInTheDocument();
    expect(screen.getByText("amount ≤ ₹50,000")).toBeInTheDocument();
    expect(screen.getByText("fraud_flag == false")).toBeInTheDocument();
  });

  it("tallies refusals per constraint from the live rejections", () => {
    // The counts must come from the gate's actual verdicts, not a hardcoded
    // figure — this panel is the on-screen evidence that the cap did its job.
    render(<GatePanel rejections={rejections("amount_cap", "amount_cap", "fraud_block")} />);
    const rules = screen.getAllByTestId("gate-rule");
    expect(rules[0]).toHaveTextContent("0 breaches");
    expect(rules[1]).toHaveTextContent("2 refused");
    expect(rules[2]).toHaveTextContent("1 refused");
  });

  it("states that the gate is the only door", () => {
    render(<GatePanel rejections={[]} />);
    expect(screen.getByText(/GatePass minted by ConstraintGate\.check\(\) only/)).toBeInTheDocument();
  });
});
