import { describe, expect, it } from "vitest";

import { formatConfidence, formatPaise } from "@/lib/format";

describe("formatPaise — Indian lakh grouping", () => {
  it("groups by two after the first three digits, prefixed Rs", () => {
    // The exact strings the demo script and the gate rejection put on screen.
    expect(formatPaise(7_500_000)).toBe("Rs 75,000");
    expect(formatPaise(5_000_000)).toBe("Rs 50,000");
    expect(formatPaise(12_050_000)).toBe("Rs 1,20,500");
    expect(formatPaise(100_000_000)).toBe("Rs 10,00,000");
  });

  it("renders whole rupees without a trailing .00 but keeps a real remainder", () => {
    expect(formatPaise(100)).toBe("Rs 1");
    expect(formatPaise(0)).toBe("Rs 0");
    expect(formatPaise(150)).toBe("Rs 1.5");
  });

  it("keeps the sign on a negative amount and never renders NaN", () => {
    expect(formatPaise(-100_000)).toBe("-Rs 1,000");
    expect(formatPaise(Number.NaN)).toBe("Rs 0");
  });
});

describe("formatConfidence", () => {
  it("rounds a 0..1 confidence to a whole percentage", () => {
    expect(formatConfidence(0.965)).toBe("97%");
    expect(formatConfidence(1)).toBe("100%");
    expect(formatConfidence(0)).toBe("0%");
  });

  it("clamps out-of-range input rather than reporting more than 100%", () => {
    expect(formatConfidence(1.4)).toBe("100%");
    expect(formatConfidence(-0.2)).toBe("0%");
  });
});
