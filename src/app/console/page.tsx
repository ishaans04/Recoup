"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import AuroraBackdrop from "@/components/landing/AuroraBackdrop";
import CauseBreakdownPanel from "@/components/console/CauseBreakdownPanel";
import ConstraintRejectionsPanel, {
  type GateRejectionView,
} from "@/components/console/ConstraintRejectionsPanel";
import ConsoleTabs, {
  type ConsoleSection,
  type TabSpec,
} from "@/components/console/ConsoleTabs";
import GatePanel from "@/components/console/GatePanel";
import HumanQueuePanel from "@/components/console/HumanQueuePanel";
import ItemDetailPanel from "@/components/console/ItemDetailPanel";
import LiveNudgeControl from "@/components/console/LiveNudgeControl";
import LiveStreamPanel from "@/components/console/LiveStreamPanel";
import MetricCards from "@/components/console/MetricCards";
import WorkItemsPanel from "@/components/console/WorkItemsPanel";
import { ENDPOINT, PILL_BUTTON, PILL_BUTTON_ACCENT } from "@/components/console/chrome";
import { getHealth, getWorkItemAudit, injectDemoCase, isApiClientError, runBatch } from "@/lib/api";
import { matchesFilter, type WorkItemFilter } from "@/lib/console-view";
import {
  FIXTURE_AUDIT_EVENTS,
  FIXTURE_ESCALATIONS,
  FIXTURE_GATE_REJECTIONS,
  FIXTURE_METRICS,
  FIXTURE_WORK_ITEMS,
} from "@/lib/fixtures";
import type { AuditEvent, Cause, Channel, Metrics, WorkItem } from "@/lib/types";
import { useRecoupStream } from "@/lib/ws";

/**
 * The operations console.
 *
 * Everything on this page is the backend's own data. `useRecoupStream` hydrates
 * a snapshot from REST and then follows `/ws`, so the metrics, the work items,
 * the audit stream, the human queue and the gate tally all move together off one
 * sequenced feed. When the backend is not reachable the page falls back to the
 * twenty-transaction preview batch in `lib/fixtures` and says so in the header —
 * it never renders an empty console that looks like a working one, and never
 * renders preview data that looks live.
 *
 * The two buttons in the header are the demo: `POST /api/batch/run` drives a
 * fresh batch through the state machine, and `POST /api/demo/inject` posts the
 * ₹75,000 case the constraint gate must refuse (PRD 16.5).
 */

const ALL_CAUSES: Cause[] = [
  "insufficient_funds",
  "gateway_degradation",
  "soft_decline",
  "expired_instrument",
  "fraud_flagged",
  "unknown",
];
const ALL_CHANNELS: Channel[] = ["payment_retry", "voice", "sms", "email", "human_queue"];

/** A zeroed metrics object, for a live backend that has not run anything yet. */
function zeroMetrics(): Metrics {
  return {
    total_failed: 0,
    total_failed_paise: 0,
    attempted: 0,
    recovered: 0,
    recovered_paise: 0,
    recovery_rate: 0,
    escalated: 0,
    gate_rejections: 0,
    in_flight: 0,
    by_cause: ALL_CAUSES.map((cause) => ({ cause, count: 0, recovered: 0, recovered_paise: 0 })),
    by_channel: ALL_CHANNELS.map((channel) => ({
      channel,
      attempted: 0,
      recovered: 0,
      recovered_paise: 0,
    })),
    generated_at: new Date().toISOString(),
  };
}

/**
 * The demo injection: ₹75,000, which is ₹25,000 over the amount cap. The gate
 * must refuse it and the item must land in the human queue without any money
 * moving. Nothing else about it is unusual — that is the point.
 */
/** Two panels of comparable weight; two where the right one carries the detail.
 *  Both collapse to a single column under 1100px so nothing is squeezed. */
const SPLIT_EVEN = "repeat(auto-fit, minmax(min(100%, 480px), 1fr))";
const SPLIT_WEIGHTED = "repeat(auto-fit, minmax(min(100%, 380px), 1fr))";

const DEMO_INJECT_CASE = {
  amount_paise: 7_500_000,
  failure_code: "GATEWAY_ERROR",
  failure_message: "Payment processing failed at the issuing bank.",
  failure_type: "one_time" as const,
  method: "netbanking",
  issuer: "ICICI",
  fraud_flag: false,
};

export default function ConsolePage() {
  const stream = useRecoupStream();

  const [section, setSection] = useState<ConsoleSection>("work-items");
  const [filter, setFilter] = useState<WorkItemFilter>("all");
  const [selectedTxnId, setSelectedTxnId] = useState<string | null>(null);
  const [streamLive, setStreamLive] = useState(true);
  const [frozenEvents, setFrozenEvents] = useState<AuditEvent[] | null>(null);
  const [mode, setMode] = useState<"mock" | "live" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"batch" | "inject" | null>(null);
  const [fullTrail, setFullTrail] = useState<Record<string, AuditEvent[]>>({});

  /*
   * Fixtures are for one situation only: no backend answered. A backend that is
   * up but has recorded nothing yet shows its real, empty state — otherwise the
   * console would display twenty invented transactions while the database holds
   * zero, and the figures would lurch from fiction to fact the moment a batch
   * finished. Starting from a true zero is also what lets the recovered counter
   * climb on camera (PRD 16.2) instead of jumping between two datasets.
   */
  const isLive = stream.connected;
  const hasData = stream.lastSeq > 0;

  const workItems: WorkItem[] = useMemo(
    () => (isLive ? Object.values(stream.workItems) : FIXTURE_WORK_ITEMS),
    [isLive, stream.workItems],
  );
  const auditEvents = isLive ? stream.auditEvents : FIXTURE_AUDIT_EVENTS;
  const metrics = isLive ? (stream.metrics ?? zeroMetrics()) : FIXTURE_METRICS;
  const escalations = isLive ? stream.escalations : FIXTURE_ESCALATIONS;
  const gateRejections = isLive ? stream.gateRejections : FIXTURE_GATE_REJECTIONS;

  // Read the real mode rather than asserting one: a mocked run must never be
  // mistakable for a live one (contract 3.1).
  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((health) => {
        if (!cancelled) setMode(health.mode);
      })
      .catch(() => {
        if (!cancelled) setMode(null);
      });
    return () => {
      cancelled = true;
    };
  }, [isLive]);

  const visibleItems = useMemo(
    () => workItems.filter((item) => matchesFilter(item, filter)),
    [workItems, filter],
  );

  // Default the selection to the most interesting row: the first escalation if
  // there is one, since that is the row a reviewer came to read.
  const effectiveSelectedId =
    selectedTxnId && workItems.some((item) => item.txn_id === selectedTxnId)
      ? selectedTxnId
      : (workItems.find((item) => item.state === "ESCALATED")?.txn_id ??
        visibleItems[0]?.txn_id ??
        workItems[0]?.txn_id ??
        null);

  const selectedItem = workItems.find((item) => item.txn_id === effectiveSelectedId) ?? null;

  // The in-memory feed only holds the most recent rows, so pull the selected
  // item's complete trail from its own endpoint when a backend is there.
  useEffect(() => {
    if (!isLive || !effectiveSelectedId) return;
    let cancelled = false;
    getWorkItemAudit(effectiveSelectedId)
      .then((response) => {
        if (!cancelled) {
          setFullTrail((prev) => ({ ...prev, [response.txn_id]: response.events }));
        }
      })
      .catch(() => {
        // Fall back to whatever the live feed already holds for this item.
      });
    return () => {
      cancelled = true;
    };
  }, [isLive, effectiveSelectedId, stream.lastSeq]);

  const selectedEvents = useMemo(() => {
    if (!effectiveSelectedId) return [];
    const fetched = fullTrail[effectiveSelectedId];
    if (fetched) return fetched;
    // The feeds are newest-first; a transition list reads oldest-first.
    return auditEvents
      .filter((event) => event.txn_id === effectiveSelectedId)
      .slice()
      .reverse();
  }, [effectiveSelectedId, fullTrail, auditEvents]);

  /** The gate's refusals, each carrying the customer name for a readable row. */
  const rejectionViews: GateRejectionView[] = useMemo(
    () =>
      gateRejections.map((rejection) => ({
        ...rejection,
        customerName: workItems.find((item) => item.txn_id === rejection.txn_id)?.customer.name,
      })),
    [gateRejections, workItems],
  );

  /** Which transactions the gate actually refused, from both available sources. */
  const refusedTxnIds = useMemo(() => {
    const refused = new Set<string>();
    for (const rejection of gateRejections) refused.add(rejection.txn_id);
    for (const event of auditEvents) {
      if (event.constraint_result === "FAIL") refused.add(event.txn_id);
    }
    return refused;
  }, [gateRejections, auditEvents]);

  // Pausing freezes what is on screen; the socket keeps running underneath.
  const streamEvents = streamLive ? auditEvents : (frozenEvents ?? auditEvents);
  const toggleStream = useCallback(() => {
    setStreamLive((wasLive) => {
      setFrozenEvents(wasLive ? auditEvents : null);
      return !wasLive;
    });
  }, [auditEvents]);

  const lastAuditId = auditEvents.length > 0 ? auditEvents[0].id : 0;

  const handleRunBatch = useCallback(async () => {
    setActionError(null);
    setBusy("batch");
    try {
      await runBatch({ size: 50 });
    } catch (error) {
      setActionError(
        isApiClientError(error) ? error.message : "Could not start the batch.",
      );
    } finally {
      setBusy(null);
    }
  }, []);

  const handleInject = useCallback(async () => {
    setActionError(null);
    setBusy("inject");
    try {
      const response = await injectDemoCase(DEMO_INJECT_CASE);
      // Land on the row that was just created, so the refusal is the next thing
      // on screen rather than something to go looking for.
      setSelectedTxnId(response.txn_id);
      setFilter("all");
      setSection("work-items");
    } catch (error) {
      setActionError(
        isApiClientError(error) ? error.message : "Could not inject the demo case.",
      );
    } finally {
      setBusy(null);
    }
  }, []);

  /**
   * Reset clears only what this page owns — selection, filter, the paused
   * stream, the cached trails — and re-hydrates from the backend. It never
   * deletes server state: `audit_events` is append-only, so a console button
   * that appeared to wipe a run would be lying about what the system can do.
   */
  const handleReset = useCallback(() => {
    setSelectedTxnId(null);
    setFilter("all");
    setSection("work-items");
    setStreamLive(true);
    setFrozenEvents(null);
    setFullTrail({});
    setActionError(null);
  }, []);

  /** The five sections, in the order an operator works through them. */
  const tabs: TabSpec[] = [
    { id: "work-items", label: "Work items", count: workItems.length },
    {
      id: "human-queue",
      label: "Human Queue",
      count: escalations.length,
      alert: escalations.length > 0,
    },
    { id: "live-audit", label: "Live audit stream", count: auditEvents.length },
    {
      id: "gate",
      label: "Constraint gate & Rejections",
      count: rejectionViews.length,
      alert: rejectionViews.length > 0,
    },
    { id: "by-cause", label: "Recovery by cause" },
  ];

  const batchProgress = stream.batchProgress;
  const batchLabel = batchProgress
    ? `running ${batchProgress.processed}/${batchProgress.size}`
    : busy === "batch"
      ? "starting…"
      : "POST /api/batch/run";

  return (
    <div style={{ position: "relative", minHeight: "100vh" }}>
      <AuroraBackdrop variant="console" />

      <header
        style={{
          position: "sticky",
          top: 0,
          zIndex: 20,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 24,
          padding: "16px 28px",
          backdropFilter: "blur(24px) saturate(170%)",
          WebkitBackdropFilter: "blur(24px) saturate(170%)",
          background:
            "linear-gradient(180deg, rgba(12,12,20,0.88) 0%, rgba(6,6,10,0.72) 100%)",
          borderBottom: "1px solid rgba(255,255,255,0.09)",
          boxShadow: "inset 0 -1px 0 rgba(255,255,255,0.05), 0 12px 32px -24px rgba(0,0,0,0.9)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <Link
            href="/"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              color: "#e9e9f0",
              textDecoration: "none",
            }}
          >
            <span style={{ fontSize: 16, fontWeight: 600 }}>Recoup</span>
          </Link>
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "rgba(233,233,240,0.4)",
            }}
          >
            operations console
          </span>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            fontFamily: "var(--font-mono)",
            fontSize: 11.5,
            flexWrap: "wrap",
          }}
        >
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 12px",
              borderRadius: 999,
              border: "1px solid rgba(255,255,255,0.1)",
              background: "rgba(255,255,255,0.035)",
              color: "rgba(233,233,240,0.65)",
            }}
          >
            <span
              className={isLive && stream.status === "open" ? "rc-pulse" : undefined}
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: isLive
                  ? stream.status === "open"
                    ? "oklch(0.8 0.14 145)"
                    : "oklch(0.86 0.14 75)"
                  : "rgba(233,233,240,0.35)",
              }}
            />
            {isLive ? `api · ${stream.status}` : "preview data · api offline"}
          </span>

          <span
            style={{
              padding: "6px 12px",
              borderRadius: 999,
              border: "1px solid oklch(0.8 0.14 75 / 0.3)",
              background: "oklch(0.8 0.14 75 / 0.1)",
              color: "oklch(0.88 0.12 75)",
            }}
          >
            MODE · {(mode ?? "mock").toUpperCase()}
          </span>

          <button
            type="button"
            onClick={handleRunBatch}
            disabled={!isLive || busy !== null}
            style={{
              ...PILL_BUTTON,
              padding: "8px 14px",
              fontSize: 11.5,
              opacity: !isLive || busy !== null ? 0.45 : 1,
              cursor: !isLive || busy !== null ? "not-allowed" : "pointer",
            }}
            title={isLive ? "Run a 50-transaction batch" : "Backend not reachable"}
          >
            {batchLabel}
          </button>

          <button
            type="button"
            onClick={handleInject}
            disabled={!isLive || busy !== null}
            style={{
              ...PILL_BUTTON_ACCENT,
              opacity: !isLive || busy !== null ? 0.45 : 1,
              cursor: !isLive || busy !== null ? "not-allowed" : "pointer",
            }}
            title={
              isLive
                ? "Inject the ₹75,000 case the gate must refuse"
                : "Backend not reachable"
            }
          >
            {busy === "inject" ? "injecting…" : "POST /api/demo/inject"}
          </button>

          <LiveNudgeControl
            disabled={!isLive || busy !== null}
            onInjected={(txnId) => {
              setSelectedTxnId(txnId);
              setFilter("all");
              setSection("work-items");
            }}
          />

          <button
            type="button"
            onClick={handleReset}
            style={PILL_BUTTON}
            title="Drop local view state and re-hydrate from the backend"
          >
            reset view
          </button>
        </div>
      </header>

      <main
        style={{
          position: "relative",
          zIndex: 1,
          padding: "26px 28px 60px",
          display: "grid",
          gap: 22,
        }}
      >
        {actionError !== null && (
          <div
            role="alert"
            style={{
              padding: "12px 18px",
              borderRadius: 12,
              border: "1px solid oklch(0.72 0.17 32 / 0.4)",
              background: "oklch(0.72 0.17 32 / 0.1)",
              color: "oklch(0.86 0.14 40)",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
            }}
          >
            {actionError}
          </div>
        )}

        {!isLive && (
          <div style={{ ...ENDPOINT, fontSize: 11.5 }}>
            No backend answered on <code>:8000</code> — showing the 20-transaction preview
            batch. Start the API to drive this console live.
          </div>
        )}

        {isLive && !hasData && (
          <div style={{ ...ENDPOINT, fontSize: 11.5 }}>
            Connected to the API. No transitions recorded yet — run a batch, or inject the
            ₹75,000 case, to populate the console.
          </div>
        )}

        <MetricCards metrics={metrics} lastAuditId={lastAuditId} />

        <ConsoleTabs tabs={tabs} active={section} onSelect={setSection} />

        <div id={`section-${section}`} role="tabpanel">
          {section === "work-items" && (
            // The table and the transaction it has open, side by side: choosing a
            // row and reading its trail is one motion, not a scroll between two
            // parts of the page.
            <div style={{ display: "grid", gridTemplateColumns: SPLIT_EVEN, gap: 22, alignItems: "start" }}>
              <WorkItemsPanel
                items={visibleItems}
                total={workItems.length}
                filter={filter}
                onFilterChange={setFilter}
                selectedTxnId={effectiveSelectedId}
                onSelect={setSelectedTxnId}
              />
              <ItemDetailPanel
                item={selectedItem}
                events={selectedEvents}
                refused={selectedItem ? refusedTxnIds.has(selectedItem.txn_id) : false}
                diagnosisSource={selectedItem?.diagnosis?.source ?? null}
              />
            </div>
          )}

          {section === "human-queue" && <HumanQueuePanel escalations={escalations} />}

          {section === "live-audit" && (
            <LiveStreamPanel events={streamEvents} live={streamLive} onToggle={toggleStream} />
          )}

          {section === "gate" && (
            // The rules and what they actually refused, together: a tally means
            // little without the refusals it counted.
            <div style={{ display: "grid", gridTemplateColumns: SPLIT_WEIGHTED, gap: 22, alignItems: "start" }}>
              <GatePanel rejections={gateRejections} />
              <ConstraintRejectionsPanel rejections={rejectionViews} />
            </div>
          )}

          {section === "by-cause" && (
            <CauseBreakdownPanel byCause={metrics.by_cause} byChannel={metrics.by_channel} />
          )}
        </div>
      </main>
    </div>
  );
}
