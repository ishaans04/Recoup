"use client";

import { formatPaise, formatRelativeTime } from "@/lib/format";
import type { ConstraintName, WsGateRejectedPayload } from "@/lib/types";

import { EMPTY_NOTE, ENDPOINT, PANEL, PANEL_HEAD, PANEL_TITLE, tintedPanel } from "./chrome";

export interface GateRejectionView extends WsGateRejectedPayload {
  seq: number;
  ts: string;
  customerName?: string;
}

const CONSTRAINT_LABEL: Record<ConstraintName, string> = {
  amount_cap: "Amount Cap",
  retry_cap: "Retry Cap",
  fraud_block: "Fraud Block",
  stopping_rule: "Stopping Rule",
};

/**
 * The `metric > limit ✗` clause PRD 12.4 puts on screen, e.g.
 * `Rs 75,000 > Rs 50,000`. Falls back to the raw reason text for a constraint
 * this build does not know how to render structurally — contract rule 5.4:
 * never hide a rejection because its shape is unfamiliar.
 */
function comparisonClause(rejection: WsGateRejectedPayload): string {
  switch (rejection.constraint) {
    case "amount_cap":
      return `${formatPaise(rejection.amount_paise)} > ${formatPaise(rejection.limit_paise)}`;
    case "retry_cap":
      return `${rejection.retry_count} attempts > ${rejection.max_retries} max`;
    case "fraud_block":
      return "fraud_flag = true";
    case "stopping_rule":
      return rejection.reason;
    default:
      return rejection.reason;
  }
}

/**
 * The demo-critical panel (PRD 12.4): the constraint gate seen saying no.
 *
 * Loud by design, and the only red on the console. Each row reads in exactly
 * the shape the PRD's own worked example uses —
 * `Amount Cap: Rs 75,000 > Rs 50,000 ✗ → HALT → Escalate` — because a gate
 * that only ever says yes looks like a label, and a gate that says no in
 * public looks like a system.
 *
 * The panel stays on screen when there is nothing to report, rather than
 * unmounting: "0 refusals so far" is itself a claim worth making, and a panel
 * that appears only on failure teaches a viewer nothing about what it watches.
 */
export default function ConstraintRejectionsPanel({
  rejections,
}: {
  rejections: GateRejectionView[];
}) {
  const loud = rejections.length > 0;

  return (
    <div style={loud ? tintedPanel("danger") : PANEL}>
      <div style={{ ...PANEL_HEAD, gap: 10 }}>
        <h2 style={{ ...PANEL_TITLE, color: loud ? "oklch(0.82 0.16 32)" : undefined }}>
          Constraint rejections
        </h2>
        <span style={ENDPOINT}>WS gate.rejected</span>
        <span
          style={{
            marginLeft: "auto",
            fontFamily: "var(--font-mono)",
            fontSize: 11.5,
            color: loud ? "oklch(0.82 0.16 32)" : "rgba(233,233,240,0.4)",
          }}
        >
          {rejections.length} refused
        </span>
      </div>

      {!loud ? (
        <div style={EMPTY_NOTE}>
          The gate has refused nothing yet. Inject the ₹75,000 case to watch it say no.
        </div>
      ) : (
        rejections.map((rejection) => (
          <div
            key={`${rejection.txn_id}-${rejection.seq}`}
            data-testid="gate-rejection-row"
            style={{
              display: "grid",
              gap: 7,
              padding: "14px 20px",
              borderBottom: "1px solid rgba(255,255,255,0.045)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 10,
                flexWrap: "wrap",
                fontFamily: "var(--font-mono)",
                fontSize: 12.5,
              }}
            >
              <span style={{ color: "#fff" }}>{rejection.txn_id}</span>
              {rejection.customerName !== undefined && (
                <span style={{ color: "rgba(233,233,240,0.45)" }}>{rejection.customerName}</span>
              )}
              <span style={{ marginLeft: "auto", color: "rgba(233,233,240,0.3)" }}>
                {formatRelativeTime(rejection.ts)}
              </span>
            </div>

            {/* The PRD's worked example, verbatim in shape. */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                flexWrap: "wrap",
                fontFamily: "var(--font-mono)",
                fontSize: 12.5,
                color: "oklch(0.84 0.16 32)",
                fontWeight: 600,
              }}
            >
              <span>
                {CONSTRAINT_LABEL[rejection.constraint] ?? rejection.constraint}:{" "}
                {comparisonClause(rejection)}
              </span>
              <span aria-label="rejected">✗</span>
              <span style={{ color: "rgba(233,233,240,0.5)" }}>→</span>
              <span>HALT</span>
              <span style={{ color: "rgba(233,233,240,0.5)" }}>→</span>
              <span>Escalate</span>
            </div>

            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11.5,
                color: "rgba(233,233,240,0.5)",
              }}
            >
              no GatePass minted · {rejection.action_type.replace(/_/g, " ")} never reached{" "}
              {rejection.channel.replace(/_/g, " ")}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
