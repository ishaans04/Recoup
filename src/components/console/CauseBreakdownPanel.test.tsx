import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import CauseBreakdownPanel from "@/components/console/CauseBreakdownPanel";
import type { CauseMetric, ChannelMetric } from "@/lib/types";

const BY_CAUSE: CauseMetric[] = [
  { cause: "insufficient_funds", count: 4, recovered: 3, recovered_paise: 1_200_000 },
  { cause: "fraud_flagged", count: 2, recovered: 0, recovered_paise: 0 },
  { cause: "soft_decline", count: 0, recovered: 0, recovered_paise: 0 },
];

const BY_CHANNEL: ChannelMetric[] = [
  { channel: "payment_retry", attempted: 6, recovered: 4, recovered_paise: 1_800_000 },
  { channel: "voice", attempted: 1, recovered: 1, recovered_paise: 499_900 },
];

describe("CauseBreakdownPanel", () => {
  afterEach(cleanup);

  it("reports recovery by cause with an honest denominator", () => {
    // PRD 15.1: "recovery by cause (which failure types we recover best)".
    // The denominator matters — 1 of 1 must not read like 40 of 40.
    render(<CauseBreakdownPanel byCause={BY_CAUSE} byChannel={BY_CHANNEL} />);
    expect(screen.getByText("Insufficient Funds")).toBeInTheDocument();
    expect(screen.getByText("3/4")).toBeInTheDocument();
    expect(screen.getByText("Rs 12,000")).toBeInTheDocument();
  });

  it("reports actions taken by channel", () => {
    // PRD 15.1: "actions taken by channel (retry / voice / SMS / email)".
    render(<CauseBreakdownPanel byCause={BY_CAUSE} byChannel={BY_CHANNEL} />);
    expect(screen.getByText("Payment Retry")).toBeInTheDocument();
    expect(screen.getByText("Voice")).toBeInTheDocument();
    expect(screen.getByText("4/6")).toBeInTheDocument();
  });

  it("keeps a cause the batch never saw rather than hiding it", () => {
    // Filtering empty rows out would make the breakdown look more complete
    // than the run actually was.
    render(<CauseBreakdownPanel byCause={BY_CAUSE} byChannel={BY_CHANNEL} />);
    expect(screen.getByText("Soft Decline")).toBeInTheDocument();
  });

  it("renders both empty states without collapsing the panel", () => {
    render(<CauseBreakdownPanel byCause={[]} byChannel={[]} />);
    expect(screen.getByText(/no causes diagnosed yet/i)).toBeInTheDocument();
    expect(screen.getByText(/no actions executed yet/i)).toBeInTheDocument();
  });
});
