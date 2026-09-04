import type { ExceptionRecord } from "@/lib/types";
import { humanise } from "@/lib/types";
import { formatPaise, formatRelativeTime } from "@/lib/format";

export interface ExceptionListProps {
  /** Newest first. */
  exceptions: ExceptionRecord[];
  /** Total transactions in the run, so the header can read "N of M" rather
   * than just a bare count. */
  totalAtRisk: number;
}

/**
 * The honest half of the headline number (PRD §13.4): every transaction this
 * run could not resolve, with a specific reason for each — never cherry-
 * picked, never a footnote. Deliberately typeset with the same weight as
 * `RecoveryCounter` (a large figure, a plain-language subhead) rather than
 * tucked away in small print, because an honest exception count is the
 * credibility play, not an admission of failure.
 */
export default function ExceptionList({ exceptions, totalAtRisk }: ExceptionListProps) {
  return (
    <div className="rounded-lg border border-console-border bg-console-panel p-5">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-console-muted">Exceptions</p>
      <p className="mt-2 font-mono text-3xl font-semibold tabular-nums text-console-text">
        {exceptions.length}
        <span className="ml-2 text-base font-normal text-console-muted">of {totalAtRisk} not recovered</span>
      </p>

      {exceptions.length === 0 ? (
        <p className="mt-4 text-sm text-console-muted" data-testid="exception-empty-state">
          No exceptions. Every transaction in this run either recovered or is still in flight.
        </p>
      ) : (
        <ul className="mt-4 space-y-3" data-testid="exception-list">
          {exceptions.map((e) => (
            <li
              key={e.txn_id}
              className="border-t border-console-border/60 pt-3 first:border-t-0 first:pt-0"
              data-testid="exception-row"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                <span className="text-sm text-console-text">{e.customer_name}</span>
                <span className="font-mono text-xs text-console-text">{formatPaise(e.amount_paise)}</span>
              </div>
              <p className="mt-0.5 font-mono text-[11px] text-console-muted">
                {e.txn_id} · {humanise(e.cause)} · {formatRelativeTime(e.escalated_at)}
              </p>
              <p className="mt-1 text-xs text-console-muted">{e.reason}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
