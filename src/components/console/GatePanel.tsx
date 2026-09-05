"use client";

import { GATE_RULES } from "@/lib/console-view";
import type { ConstraintName, WsGateRejectedPayload } from "@/lib/types";

import { PANEL, PANEL_TITLE } from "./chrome";

/**
 * The three hard caps, each carrying how many times it actually refused.
 *
 * The counts are derived from the gate rejections the page has seen rather than
 * typed in, so this panel is a live tally of the gate doing its job. A rule that
 * has refused nothing today is green; a rule that has refused something is
 * amber, and the number beside it is exactly how many items are sitting in the
 * human queue because of it.
 */
export default function GatePanel({
  rejections,
}: {
  rejections: readonly Pick<WsGateRejectedPayload, "constraint">[];
}) {
  const counts = new Map<ConstraintName, number>();
  for (const rejection of rejections) {
    counts.set(rejection.constraint, (counts.get(rejection.constraint) ?? 0) + 1);
  }

  return (
    <div style={{ ...PANEL, padding: "20px 22px", display: "grid", gap: 14 }}>
      <h2 style={PANEL_TITLE}>Constraint gate</h2>

      {GATE_RULES.map((rule) => {
        const count = counts.get(rule.constraint) ?? 0;
        return (
          <div
            key={rule.constraint}
            data-testid="gate-rule"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 14,
              padding: "11px 14px",
              borderRadius: 10,
              background: "rgba(255,255,255,0.028)",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
            }}
          >
            <span style={{ color: "rgba(233,233,240,0.72)" }}>{rule.label}</span>
            <span
              style={{ color: count > 0 ? "oklch(0.88 0.12 75)" : "oklch(0.86 0.13 145)" }}
            >
              {count === 0 ? "0 breaches" : `${count} refused`}
            </span>
          </div>
        );
      })}

      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          lineHeight: 1.7,
          color: "rgba(233,233,240,0.35)",
        }}
      >
        GatePass minted by ConstraintGate.check() only.
        <br />
        Breach → ESCALATED, never a money move.
      </div>
    </div>
  );
}
