"use client";

import { useState } from "react";

import { ConstraintBadge, SourceBadge } from "@/components/badges";
import {
  auditEventDetail,
  auditEventType,
  eventColor,
  formatClock,
  NODE_LABELS,
  stateColors,
  stateHue,
  stateStage,
} from "@/lib/console-view";
import { formatConfidence } from "@/lib/format";
import type { AuditEvent, DiagnosisSource, WorkItem } from "@/lib/types";
import { humanise } from "@/lib/types";

import { EMPTY_NOTE, ENDPOINT, PANEL, PANEL_TITLE } from "./chrome";

/**
 * One work item, opened: how far it walked, and every transition it made.
 *
 * The pipeline is drawn from the item's own state — nothing is animated or
 * simulated here, so a dot is lit if and only if the state machine actually
 * reached that node. A gate refusal recolours the pipeline from node 3 onward
 * and relabels node 4 "Escalate", because past the refusal this run is no
 * longer a recovery.
 *
 * Below it is the audit chain PRD 8.8 asks for, one row per transition:
 * `Event → Diagnosis → Action → Constraint Check → Result`. The diagnosis cell
 * carries its confidence and a rules-vs-LLM source badge, which is what makes
 * the two-tier engine (PRD 11) visible rather than merely claimed — a reader
 * can see which rows the deterministic table answered and which ones needed a
 * model. Clicking a row opens the full rationale that was recorded with it.
 */

const CHAIN_COLUMNS = "68px 132px minmax(150px, 1.1fr) minmax(110px, 0.8fr) 74px minmax(90px, 0.8fr)";

export default function ItemDetailPanel({
  item,
  events,
  refused,
  diagnosisSource,
}: {
  item: WorkItem | null;
  events: AuditEvent[];
  refused: boolean;
  diagnosisSource: DiagnosisSource | null;
}) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (!item) {
    return (
      <div style={{ ...PANEL, padding: "20px 22px 24px" }}>
        <h2 style={PANEL_TITLE}>No work item selected</h2>
        <div style={{ ...EMPTY_NOTE, padding: "14px 0 0" }}>
          Select a row above to read its transitions.
        </div>
      </div>
    );
  }

  const stage = stateStage(item.state);
  const hue = stateHue(item.state);
  const [stateColor] = stateColors(item.state);

  return (
    <div style={{ ...PANEL, padding: "20px 22px 24px", display: "grid", gap: 20 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <h2 style={PANEL_TITLE}>{item.txn_id}</h2>
        <span style={ENDPOINT}>GET /api/workitems/{"{id}"}/audit</span>
        <span
          style={{
            marginLeft: "auto",
            fontFamily: "var(--font-mono)",
            fontSize: 11.5,
            color: stateColor,
          }}
        >
          {item.state}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)" }}>
        {NODE_LABELS.map((baseLabel, index) => {
          // From the gate onward, a refused run is drawn in the refusal hue.
          const isRefusedNode = refused && index >= 3;
          const nodeHue = isRefusedNode ? 75 : hue;
          const label = index === 4 && refused ? "Escalate" : baseLabel;
          const reached = stage >= index;
          const current = stage === index;
          const c = (lightness: number, alpha: number) =>
            `oklch(${lightness} 0.13 ${nodeHue} / ${alpha})`;

          return (
            <div key={baseLabel} style={{ display: "grid", gap: 10, paddingRight: 10 }}>
              <div
                style={{ position: "relative", height: 10, display: "flex", alignItems: "center" }}
              >
                <div
                  style={{
                    position: "absolute",
                    left: 0,
                    right: 0,
                    height: 1,
                    background: reached
                      ? `linear-gradient(90deg, ${c(0.65, 0.5)}, ${c(0.65, 0.22)})`
                      : "rgba(255,255,255,0.06)",
                  }}
                />
                <div
                  style={{
                    position: "relative",
                    width: 10,
                    height: 10,
                    borderRadius: "50%",
                    background: reached ? c(current ? 0.84 : 0.68, 1) : "rgba(255,255,255,0.14)",
                    boxShadow: current && reached ? `0 0 16px ${c(0.8, 0.85)}` : "none",
                  }}
                />
              </div>
              <div
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  color: reached
                    ? current
                      ? "#fff"
                      : "rgba(233,233,240,0.68)"
                    : "rgba(233,233,240,0.28)",
                }}
              >
                {label}
              </div>
            </div>
          );
        })}
      </div>

      {/* The audit chain. Scrolls sideways rather than squeezing the columns,
          so a narrow window never truncates a rejection reason. */}
      <div style={{ overflowX: "auto" }}>
        <div style={{ minWidth: 660, display: "grid", gap: 6 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: CHAIN_COLUMNS,
              gap: 12,
              padding: "0 12px 4px",
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "rgba(233,233,240,0.35)",
            }}
          >
            <span>time</span>
            <span>event</span>
            <span>diagnosis</span>
            <span>action</span>
            <span>gate</span>
            <span>result</span>
          </div>

          {events.length === 0 ? (
            <div style={{ ...EMPTY_NOTE, padding: "6px 12px" }}>
              No transitions recorded for this item yet.
            </div>
          ) : (
            events.map((event) => {
              const type = auditEventType(event);
              const isOpen = expanded === event.id;
              return (
                <div key={event.id} style={{ display: "grid", gap: 0 }}>
                  <div
                    data-testid="transition-row"
                    role="button"
                    tabIndex={0}
                    aria-expanded={isOpen}
                    onClick={() => setExpanded(isOpen ? null : event.id)}
                    onKeyDown={(keyEvent) => {
                      if (keyEvent.key === "Enter" || keyEvent.key === " ") {
                        keyEvent.preventDefault();
                        setExpanded(isOpen ? null : event.id);
                      }
                    }}
                    style={{
                      display: "grid",
                      gridTemplateColumns: CHAIN_COLUMNS,
                      gap: 12,
                      alignItems: "center",
                      padding: "9px 12px",
                      borderRadius: isOpen ? "10px 10px 0 0" : 10,
                      background: isOpen ? "rgba(255,255,255,0.05)" : "rgba(255,255,255,0.028)",
                      fontFamily: "var(--font-mono)",
                      fontSize: 12,
                      cursor: "pointer",
                    }}
                  >
                    <span style={{ color: "rgba(233,233,240,0.35)" }}>
                      {formatClock(event.timestamp)}
                    </span>

                    <span style={{ color: eventColor(type) }}>{type}</span>

                    {/* Diagnosis: cause, confidence, and which tier produced it. */}
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 6,
                        flexWrap: "wrap",
                        color: "rgba(233,233,240,0.75)",
                      }}
                    >
                      {event.diagnosis_cause === null ? (
                        <span style={{ color: "rgba(233,233,240,0.3)" }}>—</span>
                      ) : (
                        <>
                          <span>{humanise(event.diagnosis_cause)}</span>
                          {event.diagnosis_confidence !== null && (
                            <span style={{ color: "rgba(233,233,240,0.45)" }}>
                              {formatConfidence(event.diagnosis_confidence)}
                            </span>
                          )}
                          {diagnosisSource !== null && <SourceBadge source={diagnosisSource} />}
                        </>
                      )}
                    </span>

                    <span style={{ color: "rgba(233,233,240,0.7)" }}>
                      {event.action_chosen === null ? (
                        <span style={{ color: "rgba(233,233,240,0.3)" }}>—</span>
                      ) : (
                        humanise(event.action_chosen)
                      )}
                    </span>

                    <ConstraintBadge result={event.constraint_result} />

                    <span
                      style={{
                        color: event.constraint_result === "FAIL"
                          ? "oklch(0.84 0.16 32)"
                          : "rgba(233,233,240,0.62)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={auditEventDetail(event)}
                    >
                      {auditEventDetail(event)}
                    </span>
                  </div>

                  {isOpen && (
                    <div
                      style={{
                        padding: "10px 14px 12px",
                        borderRadius: "0 0 10px 10px",
                        background: "rgba(255,255,255,0.05)",
                        borderTop: "1px solid rgba(255,255,255,0.06)",
                        fontFamily: "var(--font-mono)",
                        fontSize: 11.5,
                        lineHeight: 1.7,
                        color: "rgba(233,233,240,0.6)",
                      }}
                    >
                      <span style={{ color: "rgba(233,233,240,0.35)" }}>
                        {event.from_state ?? "—"} → {event.to_state} · rationale:{" "}
                      </span>
                      {event.rationale}
                      {event.constraint_reason !== null && (
                        <>
                          <br />
                          <span style={{ color: "oklch(0.84 0.16 32)" }}>
                            {event.constraint_reason}
                          </span>
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
