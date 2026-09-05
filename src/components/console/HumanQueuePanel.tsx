"use client";

import { formatPaise } from "@/lib/format";
import type { Escalation } from "@/lib/types";

import { EMPTY_NOTE, ENDPOINT, PANEL_HEAD, PANEL_TITLE, tintedPanel } from "./chrome";

/**
 * The human queue — which is also the exception list.
 *
 * `ESCALATED` is the only terminal "did not recover" state, so every exception
 * the PRD requires reporting (13.4) is an escalation, and each row here carries
 * the reason it was refused rather than a bare count. This panel is deliberately
 * the loudest thing on the right-hand column: a system that hides what it could
 * not do is not one you can hand to a reviewer.
 */
export default function HumanQueuePanel({ escalations }: { escalations: Escalation[] }) {
  return (
    <div style={tintedPanel("amber")}>
      <div style={{ ...PANEL_HEAD, gap: 10 }}>
        <h2 style={PANEL_TITLE}>Human queue</h2>
        <span style={ENDPOINT}>GET /api/escalations</span>
        <span
          style={{
            marginLeft: "auto",
            fontFamily: "var(--font-mono)",
            fontSize: 11.5,
            color: "oklch(0.88 0.12 75)",
          }}
        >
          {escalations.length} open
        </span>
      </div>

      {escalations.length === 0 ? (
        <div style={EMPTY_NOTE}>Nothing escalated. Every item resolved inside its bounds.</div>
      ) : (
        escalations.map((escalation) => (
          <div
            key={escalation.txn_id}
            data-testid="escalation-row"
            style={{
              display: "grid",
              gap: 6,
              padding: "14px 20px",
              borderBottom: "1px solid rgba(255,255,255,0.045)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 12,
                fontFamily: "var(--font-mono)",
                fontSize: 12.5,
              }}
            >
              <span style={{ color: "#fff" }}>{escalation.txn_id}</span>
              <span style={{ color: "rgba(233,233,240,0.6)" }}>
                {formatPaise(escalation.amount_paise)}
              </span>
            </div>
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11.5,
                color: "oklch(0.86 0.13 75)",
              }}
            >
              {escalation.reason}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
