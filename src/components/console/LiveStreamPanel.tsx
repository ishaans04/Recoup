"use client";

import { auditEventDetail, auditEventType, eventColor, formatClock } from "@/lib/console-view";
import type { AuditEvent } from "@/lib/types";

import { EMPTY_NOTE, ENDPOINT, PANEL, PANEL_HEAD, PANEL_TITLE, PILL_BUTTON } from "./chrome";

/**
 * The append-only log as it arrives, newest at the top.
 *
 * Every row here is a real `audit.appended` frame off `/ws` (or, before the
 * backend is reachable, a row of the preview batch). The sequence number shown
 * is the audit row's own id, which is the same number the WebSocket resume
 * cursor is built from — so a reader can watch the log advance and know that
 * nothing between two ids was skipped.
 *
 * Pausing freezes the view without closing the socket: frames keep arriving and
 * keep their place, and resuming shows the log as it now stands rather than
 * replaying what was missed. That is what an operator wants when they pause —
 * to read one row without the list moving under them.
 */
export default function LiveStreamPanel({
  events,
  live,
  onToggle,
}: {
  events: AuditEvent[];
  live: boolean;
  onToggle: () => void;
}) {
  return (
    <div style={PANEL}>
      <div style={PANEL_HEAD}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <h2 style={PANEL_TITLE}>Live audit stream</h2>
          <span style={ENDPOINT}>WS /ws</span>
        </div>
        <button type="button" onClick={onToggle} style={PILL_BUTTON}>
          {live ? "❙❙ pause" : "▶ resume"}
        </button>
      </div>

      <div style={{ maxHeight: 372, overflowY: "auto" }}>
        {events.length === 0 ? (
          <div style={EMPTY_NOTE}>Waiting for the first transition.</div>
        ) : (
          events.map((event) => {
            const type = auditEventType(event);
            return (
              <div
                key={event.id}
                data-testid="stream-row"
                className="rc-in"
                style={{
                  display: "grid",
                  gap: 6,
                  padding: "12px 20px",
                  borderBottom: "1px solid rgba(255,255,255,0.045)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "baseline",
                    gap: 10,
                    fontFamily: "var(--font-mono)",
                    fontSize: 11.5,
                  }}
                >
                  <span style={{ color: "rgba(233,233,240,0.3)" }}>#{event.id}</span>
                  <span style={{ color: eventColor(type) }}>{type}</span>
                  <span style={{ marginLeft: "auto", color: "rgba(233,233,240,0.3)" }}>
                    {formatClock(event.timestamp)}
                  </span>
                </div>
                <div
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 12,
                    color: "rgba(233,233,240,0.62)",
                  }}
                >
                  {event.txn_id} · {auditEventDetail(event)}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
