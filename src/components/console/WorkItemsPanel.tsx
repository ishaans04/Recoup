"use client";

import { useState } from "react";

import { SourceBadge } from "@/components/badges";
import { actionSummary, stateColors, type WorkItemFilter, WORK_ITEM_FILTERS } from "@/lib/console-view";
import { formatPaise } from "@/lib/format";
import type { WorkItem } from "@/lib/types";

import {
  EMPTY_NOTE,
  ENDPOINT,
  MONO_ROW,
  PANEL,
  PANEL_HEAD,
  PANEL_TITLE,
  WORK_ITEM_COLUMNS,
} from "./chrome";

/**
 * Every work item the page knows about, filtered by lifecycle and selectable.
 *
 * Selecting a row drives the detail panel below it, so the table is the
 * console's primary navigation rather than a read-only list. The state pill is
 * the only coloured thing in a row: an operator scanning the column sees the
 * shape of the batch — how much green, how much amber — before reading an id.
 */
export default function WorkItemsPanel({
  items,
  total,
  filter,
  onFilterChange,
  selectedTxnId,
  onSelect,
}: {
  items: WorkItem[];
  total: number;
  filter: WorkItemFilter;
  onFilterChange: (filter: WorkItemFilter) => void;
  selectedTxnId: string | null;
  onSelect: (txnId: string) => void;
}) {
  const [hovered, setHovered] = useState<string | null>(null);

  return (
    <div style={PANEL}>
      <div style={PANEL_HEAD}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <h2 style={PANEL_TITLE}>Work items</h2>
          <span style={ENDPOINT}>GET /api/workitems</span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {WORK_ITEM_FILTERS.map((option) => {
            const active = option === filter;
            return (
              <button
                key={option}
                type="button"
                onClick={() => onFilterChange(option)}
                aria-pressed={active}
                style={{
                  padding: "6px 12px",
                  borderRadius: 999,
                  border: `1px solid ${active ? "oklch(0.78 0.13 197 / 0.45)" : "rgba(255,255,255,0.1)"}`,
                  background: active ? "oklch(0.78 0.13 197 / 0.14)" : "rgba(255,255,255,0.03)",
                  color: active ? "oklch(0.9 0.1 197)" : "rgba(233,233,240,0.55)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  cursor: "pointer",
                }}
              >
                {option}
              </button>
            );
          })}
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: WORK_ITEM_COLUMNS,
          gap: 12,
          padding: "11px 20px",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
          fontFamily: "var(--font-mono)",
          fontSize: 10.5,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "rgba(233,233,240,0.38)",
        }}
      >
        <span>payment id</span>
        <span>amount</span>
        <span>cause</span>
        <span>state</span>
        <span>action</span>
      </div>

      {items.length === 0 ? (
        <div style={EMPTY_NOTE}>No work items match this filter.</div>
      ) : (
        items.map((item) => {
          const selected = item.txn_id === selectedTxnId;
          const [stateColor, stateBorder] = stateColors(item.state);
          return (
            <div
              key={item.txn_id}
              data-testid="work-item-row"
              role="button"
              tabIndex={0}
              onClick={() => onSelect(item.txn_id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(item.txn_id);
                }
              }}
              onMouseEnter={() => setHovered(item.txn_id)}
              onMouseLeave={() => setHovered(null)}
              style={{
                ...MONO_ROW,
                display: "grid",
                gridTemplateColumns: WORK_ITEM_COLUMNS,
                gap: 12,
                alignItems: "center",
                padding: "13px 20px",
                borderBottom: "1px solid rgba(255,255,255,0.045)",
                cursor: "pointer",
                background: selected
                  ? "oklch(0.78 0.13 197 / 0.09)"
                  : hovered === item.txn_id
                    ? "rgba(255,255,255,0.045)"
                    : "transparent",
              }}
            >
              <span style={{ color: selected ? "#fff" : "rgba(233,233,240,0.85)" }}>
                {item.txn_id}
              </span>
              <span style={{ color: "rgba(233,233,240,0.8)" }}>
                {formatPaise(item.amount_paise)}
              </span>
              {/* Cause plus the tier that decided it: PRD 11's two-tier engine
                  has to be visible in the table, not just claimed in the docs. */}
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  flexWrap: "wrap",
                  color: "rgba(233,233,240,0.6)",
                }}
              >
                {item.diagnosis === null ? (
                  "—"
                ) : (
                  <>
                    <span>{item.diagnosis.cause}</span>
                    <SourceBadge source={item.diagnosis.source} />
                  </>
                )}
              </span>
              <span
                style={{
                  justifySelf: "start",
                  padding: "3px 9px",
                  borderRadius: 6,
                  border: `1px solid ${stateBorder}`,
                  color: stateColor,
                  fontSize: 11,
                  letterSpacing: "0.06em",
                }}
              >
                {item.state}
              </span>
              <span style={{ color: "rgba(233,233,240,0.55)" }}>{actionSummary(item)}</span>
            </div>
          );
        })
      )}

      <div
        style={{
          padding: "12px 20px",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          color: "rgba(233,233,240,0.35)",
        }}
      >
        {items.length} of {total} items · cursor-paginated · filter: {filter}
      </div>
    </div>
  );
}
