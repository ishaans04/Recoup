import type { ConstraintName, WsGateRejectedPayload } from "@/lib/types";
import { humanise } from "@/lib/types";
import { formatPaise, formatRelativeTime } from "@/lib/format";

export interface GateRejectionView extends WsGateRejectedPayload {
  seq: number;
  ts: string;
  customerName?: string;
}

export interface ConstraintRejectionsProps {
  /** Newest first. */
  rejections: GateRejectionView[];
}

const CONSTRAINT_LABEL: Record<ConstraintName, string> = {
  amount_cap: "Amount Cap",
  retry_cap: "Retry Cap",
  fraud_block: "Fraud Block",
  stopping_rule: "Stopping Rule",
};

/** The `metric > limit ✗` clause PRD §12.4 puts on screen, e.g.
 * `Rs 75,000 > Rs 50,000`. Falls back to the raw reason text for a
 * constraint this build doesn't know how to render structurally, per
 * contract rule 5.4 — never hide a rejection because its shape is
 * unfamiliar. */
function comparisonClause(r: WsGateRejectedPayload): string {
  switch (r.constraint) {
    case "amount_cap":
      return `${formatPaise(r.amount_paise)} > ${formatPaise(r.limit_paise)}`;
    case "retry_cap":
      return `${r.retry_count} attempts > ${r.max_retries} max`;
    case "fraud_block":
      return "fraud_flag = true";
    case "stopping_rule":
      return r.reason;
    default:
      return r.reason;
  }
}

/**
 * The demo-critical panel (PRD §12.4): the constraint gate seen saying no.
 * Loud by design — a red border, a red heading, one line per rejection in
 * exactly the shape the PRD's own worked example uses:
 * `Amount Cap: Rs 75,000 > Rs 50,000 ✗ -> HALT -> Escalate`. A gate that
 * only ever says yes looks like a label; this is what makes it look like a
 * system instead.
 */
export default function ConstraintRejections({ rejections }: ConstraintRejectionsProps) {
  const hasRejections = rejections.length > 0;

  return (
    <div
      className={`rounded-lg border p-5 ${
        hasRejections
          ? "border-console-danger/60 bg-console-danger/[0.06]"
          : "border-console-border bg-console-panel"
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <h2
          className={`text-sm font-semibold tracking-tight ${hasRejections ? "text-console-danger" : "text-console-text"}`}
        >
          Constraint rejections
        </h2>
        {hasRejections && (
          <span className="rounded border border-console-danger/50 px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-widest text-console-danger">
            {rejections.length} halted
          </span>
        )}
      </div>

      {!hasRejections ? (
        <p className="mt-3 text-sm text-console-muted">
          No rejections yet. Every proposed action so far has stayed within every cap.
        </p>
      ) : (
        <ul className="mt-3 space-y-3" data-testid="rejection-list">
          {rejections.map((r) => (
            <li
              key={`${r.txn_id}-${r.seq}`}
              className="rounded-md border border-console-danger/40 bg-console-panel px-3 py-2.5"
              data-testid="rejection-row"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <p className="font-mono text-sm leading-relaxed text-console-text">
                  <span className="font-semibold text-console-danger">
                    {CONSTRAINT_LABEL[r.constraint] ?? humanise(r.constraint)}:
                  </span>{" "}
                  {comparisonClause(r)}{" "}
                  <span aria-hidden="true" className="text-console-danger">
                    &#10007;
                  </span>{" "}
                  <span className="text-console-muted">-&gt;</span>{" "}
                  <span className="font-semibold text-console-danger">HALT</span>{" "}
                  <span className="text-console-muted">-&gt;</span>{" "}
                  <span className="font-semibold text-console-warn">{humanise(r.next_state)}</span>
                </p>
                <span className="whitespace-nowrap font-mono text-[11px] text-console-muted">
                  {formatRelativeTime(r.ts)}
                </span>
              </div>
              <p className="mt-1 font-mono text-[11px] text-console-muted">
                {r.txn_id}
                {r.customerName ? ` · ${r.customerName}` : ""}
              </p>
              <p className="mt-1 text-xs text-console-muted">{r.reason}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
