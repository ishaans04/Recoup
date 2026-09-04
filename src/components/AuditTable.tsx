"use client";

import { useEffect, useRef, useState } from "react";

import type { AuditEvent, DiagnosisSource } from "@/lib/types";
import { formatConfidence, formatPaise, formatRelativeTime } from "@/lib/format";
import { ConstraintBadge, SourceBadge, StateBadge } from "./badges";

const FLASH_DURATION_MS = 1800;

export interface AuditTableProps {
  /** Newest-first — the order every other panel and the live stream use. */
  events: AuditEvent[];
  /** Optional: amount for each txn_id, so the result column can show what was
   * actually recovered rather than just the word "recovered". Absent fields
   * degrade gracefully — the row still renders, just without the figure. */
  amountByTxnId?: Record<string, number>;
  /**
   * `AuditEvent` (contract section 2.2) does not itself carry a diagnosis
   * source, only `WorkItem.diagnosis.source` does — see the phase 10 report
   * for why this table needs one anyway. The page joins the two by `txn_id`
   * and passes the result in here; a row simply omits the badge if its
   * txn_id isn't in the map yet (e.g. a DETECTED row, before any diagnosis
   * exists).
   */
  diagnosisSourceByTxnId?: Record<string, DiagnosisSource>;
}

/**
 * The core panel (PRD §8.8): one row per audit event,
 * `Time | Txn | Event -> Diagnosis -> Action -> Constraint check -> Result`.
 * Newest rows land at the top and flash briefly on arrival; every row expands
 * to the full rationale text the backend recorded for that transition.
 */
export default function AuditTable({ events, amountByTxnId, diagnosisSourceByTxnId }: AuditTableProps) {
  const [expandedIds, setExpandedIds] = useState<ReadonlySet<number>>(new Set());
  const [flashIds, setFlashIds] = useState<ReadonlySet<number>>(new Set());
  const knownIdsRef = useRef<Set<number> | null>(null);

  useEffect(() => {
    const currentIds = new Set(events.map((e) => e.id));
    if (knownIdsRef.current === null) {
      // First mount: nothing has "just arrived", so nothing flashes.
      knownIdsRef.current = currentIds;
      return;
    }
    const arrived = events
      .filter((e) => !knownIdsRef.current!.has(e.id))
      .map((e) => e.id);
    knownIdsRef.current = currentIds;
    if (arrived.length === 0) return;

    setFlashIds(new Set(arrived));
    const timer = setTimeout(() => setFlashIds(new Set()), FLASH_DURATION_MS);
    return () => clearTimeout(timer);
  }, [events]);

  function toggle(id: number) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="rounded-lg border border-console-border bg-console-panel">
      <div className="flex items-center justify-between border-b border-console-border px-4 py-3">
        <h2 className="text-sm font-medium tracking-tight text-console-text">Audit trail</h2>
        <span className="font-mono text-[11px] text-console-muted">{events.length} events</span>
      </div>
      <div className="max-h-[640px] overflow-auto">
        <table className="w-full min-w-[880px] border-collapse text-left text-sm">
          <thead className="sticky top-0 z-10 bg-console-panel-raised">
            <tr>
              <th scope="col" className="px-3 py-2 font-mono text-[11px] font-medium uppercase tracking-wider text-console-muted">
                Time
              </th>
              <th scope="col" className="px-3 py-2 font-mono text-[11px] font-medium uppercase tracking-wider text-console-muted">
                Txn
              </th>
              <th scope="col" className="px-3 py-2 font-mono text-[11px] font-medium uppercase tracking-wider text-console-muted">
                Event
              </th>
              <th scope="col" className="px-3 py-2 font-mono text-[11px] font-medium uppercase tracking-wider text-console-muted">
                Diagnosis
              </th>
              <th scope="col" className="px-3 py-2 font-mono text-[11px] font-medium uppercase tracking-wider text-console-muted">
                Action
              </th>
              <th scope="col" className="px-3 py-2 font-mono text-[11px] font-medium uppercase tracking-wider text-console-muted">
                Constraint
              </th>
              <th scope="col" className="px-3 py-2 font-mono text-[11px] font-medium uppercase tracking-wider text-console-muted">
                Result
              </th>
            </tr>
          </thead>
          <tbody>
            {events.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-sm text-console-muted">
                  No audit events yet.
                </td>
              </tr>
            ) : (
              events.map((event) => {
                const expanded = expandedIds.has(event.id);
                const amount = amountByTxnId?.[event.txn_id];
                const source = diagnosisSourceByTxnId?.[event.txn_id];
                return (
                  <AuditRow
                    key={event.id}
                    event={event}
                    expanded={expanded}
                    flashing={flashIds.has(event.id)}
                    amountPaise={amount}
                    source={source}
                    onToggle={() => toggle(event.id)}
                  />
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AuditRow({
  event,
  expanded,
  flashing,
  amountPaise,
  source,
  onToggle,
}: {
  event: AuditEvent;
  expanded: boolean;
  flashing: boolean;
  amountPaise: number | undefined;
  source: DiagnosisSource | undefined;
  onToggle: () => void;
}) {
  return (
    <>
      <tr
        className={`cursor-pointer border-b border-console-border/60 align-top hover:bg-console-panel-raised ${
          flashing ? "row-arrive" : ""
        }`}
        onClick={onToggle}
        aria-expanded={expanded}
        data-testid="audit-row"
      >
        <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-console-muted">
          {formatRelativeTime(event.timestamp)}
        </td>
        <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-console-text">{event.txn_id}</td>
        <td className="whitespace-nowrap px-3 py-2">
          <StateBadge state={event.to_state} />
        </td>
        <td className="px-3 py-2">
          {event.diagnosis_cause ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-console-text">{event.diagnosis_cause.replace(/_/g, " ")}</span>
              {event.diagnosis_confidence !== null && (
                <span className="font-mono text-[11px] text-console-muted">
                  {formatConfidence(event.diagnosis_confidence)}
                </span>
              )}
              {source && <SourceBadge source={source} />}
            </div>
          ) : (
            <span className="text-xs text-console-muted">&mdash;</span>
          )}
        </td>
        <td className="whitespace-nowrap px-3 py-2 text-xs text-console-text">
          {event.action_chosen ? event.action_chosen.replace(/_/g, " ") : <span className="text-console-muted">&mdash;</span>}
        </td>
        <td className="whitespace-nowrap px-3 py-2">
          <ConstraintBadge result={event.constraint_result} />
        </td>
        <td className="px-3 py-2 text-xs">
          {event.outcome ? (
            <span
              className={
                event.outcome === "recovered"
                  ? "font-medium text-console-accent"
                  : event.outcome === "escalated"
                    ? "font-medium text-console-warn"
                    : "text-console-text"
              }
            >
              {event.outcome}
              {event.outcome === "recovered" && amountPaise !== undefined ? ` · ${formatPaise(amountPaise)}` : ""}
            </span>
          ) : (
            <span className="text-console-muted">in progress</span>
          )}
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-console-border/60 bg-console-panel-raised/60">
          <td colSpan={7} className="px-3 py-3 text-xs leading-relaxed text-console-muted">
            <span className="font-mono text-[10px] uppercase tracking-wider text-console-muted">Rationale</span>
            <p className="mt-1 text-console-text">{event.rationale}</p>
            {event.constraint_reason && (
              <p className="mt-2 font-mono text-[11px] text-console-muted">{event.constraint_reason}</p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
