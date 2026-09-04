import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RecoveryCounter from "@/components/RecoveryCounter";

describe("RecoveryCounter", () => {
  beforeEach(() => {
    // Drive the count-up animation straight to completion with a monotonically
    // increasing timestamp, so the test asserts the final formatted figure
    // rather than the value mid-animation.
    let t = 0;
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      t += 1000;
      cb(t);
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", () => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it("renders the recovered amount as a lakh-grouped rupee figure", () => {
    render(
      <RecoveryCounter
        recoveredPaise={22_729_000}
        recoveredCount={27}
        totalAtRisk={50}
        recoveryRate={0.53}
      />,
    );
    expect(screen.getByTestId("recovery-counter-value")).toHaveTextContent("Rs 2,27,290");
    expect(screen.getByText("53%")).toBeInTheDocument();
    expect(screen.getByText("27")).toBeInTheDocument();
    expect(screen.getByText("50")).toBeInTheDocument();
  });
});
