import type { Escalation } from "@/lib/types";
import { humanise } from "@/lib/types";
import { formatPaise, formatRelativeTime } from "@/lib/format";
import { ConstraintBadge } from "./badges";

export interface EscalationQueueProps {
  /** Newest first. */
  escalations: Escalation[];
}

/**
 * The human queue: every work item the policy or the gate routed to a
 * person, newest first, with the reason it landed there and how (a failed
 * constraint check, or a policy decision that never reached the gate).
 * Amber throughout — escalated/exception is one of the five reserved
 * meanings, never used decoratively elsewhere on the page.
 */
export default function EscalationQueue({ escalations }: EscalationQueueProps) {
  return (
    <div className="rounded-lg border border-console-border bg-console-panel p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-medium tracking-tight text-console-text">Escalation queue</h2>
        <span className="rounded border border-console-warn/40 bg-console-warn/10 px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-widest text-console-warn">
          {escalations.length} waiting
        </span>
      </div>

      {escalations.length === 0 ? (
        <p className="mt-3 text-sm text-console-muted">No work items are waiting on a human right now.</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[420px] border-collapse text-left text-sm">
            <thead>
              <tr>
                <th scope="col" className="pb-2 font-mono text-[10px] font-medium uppercase tracking-wider text-console-muted">
                  Customer
                </th>
                <th scope="col" className="pb-2 font-mono text-[10px] font-medium uppercase tracking-wider text-console-muted">
                  Amount
                </th>
                <th scope="col" className="pb-2 font-mono text-[10px] font-medium uppercase tracking-wider text-console-muted">
                  Gate
                </th>
                <th scope="col" className="pb-2 font-mono text-[10px] font-medium uppercase tracking-wider text-console-muted">
                  Reason
                </th>
              </tr>
            </thead>
            <tbody>
              {escalations.map((e) => (
                <tr key={e.txn_id} className="border-t border-console-border/50 align-top" data-testid="escalation-row">
                  <td className="py-2 pr-3">
                    <p className="text-xs text-console-text">{e.customer_name}</p>
                    <p className="font-mono text-[10px] text-console-muted">
                      {e.txn_id} · {humanise(e.cause)} · {formatRelativeTime(e.escalated_at)}
                    </p>
                  </td>
                  <td className="whitespace-nowrap py-2 pr-3 font-mono text-xs text-console-text">
                    {formatPaise(e.amount_paise)}
                  </td>
                  <td className="whitespace-nowrap py-2 pr-3">
                    <ConstraintBadge result={e.constraint_result} />
                  </td>
                  <td className="py-2 text-xs text-console-muted">{e.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
