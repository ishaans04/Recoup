"use client";

import { useCallback, useMemo, useState } from "react";

import { injectDemoCase, isApiClientError, runBatch } from "@/lib/api";
import {
  FIXTURE_AUDIT_EVENTS,
  FIXTURE_BATCH_RUN,
  FIXTURE_ESCALATIONS,
  FIXTURE_EXCEPTIONS,
  FIXTURE_GATE_REJECTIONS,
  FIXTURE_METRICS,
  FIXTURE_WORK_ITEMS,
} from "@/lib/fixtures";
import type { Cause, Channel, DiagnosisSource, Metrics, WorkItem } from "@/lib/types";
import { useRecoupStream } from "@/lib/ws";

import AuditTable from "@/components/AuditTable";
import BatchControls, { type BatchControlsStatus } from "@/components/BatchControls";
import CauseBreakdown from "@/components/CauseBreakdown";
import ConnectionStatus, { type ConnectionStatusValue } from "@/components/ConnectionStatus";
import ConstraintRejections, { type GateRejectionView } from "@/components/ConstraintRejections";
import EscalationQueue from "@/components/EscalationQueue";
import ExceptionList from "@/components/ExceptionList";
import RecoveryCounter from "@/components/RecoveryCounter";

const ALL_CAUSES: Cause[] = [
  "insufficient_funds",
  "gateway_degradation",
  "soft_decline",
  "expired_instrument",
  "fraud_flagged",
  "unknown",
];
const ALL_CHANNELS: Channel[] = ["payment_retry", "voice", "sms", "email", "human_queue"];

/** An honest zero — used only in the unlikely gap between a live socket
 * connecting and its first metrics.updated frame arriving. Never shown as
 * preview data; the connection badge already reads "live" at that point. */
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
    by_channel: ALL_CHANNELS.map((channel) => ({ channel, attempted: 0, recovered: 0, recovered_paise: 0 })),
    generated_at: new Date().toISOString(),
  };
}

const DEMO_INJECT_CASE = {
  amount_paise: 7_500_000,
  failure_code: "GATEWAY_ERROR",
  failure_message: "Payment processing failed at the issuing bank.",
  failure_type: "one_time" as const,
  method: "netbanking",
  issuer: "ICICI",
  fraud_flag: false,
};

export default function Home() {
  const stream = useRecoupStream();
  const [actionError, setActionError] = useState<string | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [injecting, setInjecting] = useState(false);

  // lastSeq only moves once either the REST snapshot or the WS handshake has
  // genuinely reached a backend — see useRecoupStream's doc comment. Until
  // then there is nothing real to show, so the console runs on the preview
  // dataset instead of an empty shell.
  const isLive = stream.lastSeq > 0;

  const connectionStatus: ConnectionStatusValue = isLive
    ? stream.status === "open"
      ? "live"
      : "reconnecting"
    : "preview";

  const workItemsMap: Record<string, WorkItem> = isLive
    ? stream.workItems
    : Object.fromEntries(FIXTURE_WORK_ITEMS.map((w) => [w.txn_id, w]));

  const auditEvents = isLive ? stream.auditEvents : FIXTURE_AUDIT_EVENTS;
  const metrics = isLive ? (stream.metrics ?? zeroMetrics()) : FIXTURE_METRICS;
  const escalations = isLive ? stream.escalations : FIXTURE_ESCALATIONS;
  const exceptions = isLive ? stream.escalations : FIXTURE_EXCEPTIONS;
  const batch = isLive ? stream.batch : FIXTURE_BATCH_RUN;

  // Derived, not stored: a run counts as in progress from the moment its
  // POST is accepted until a batch.completed frame with a matching run_id
  // arrives with a non-"running" status. No effect needed to "notice" that
  // transition — it falls out of the values already in scope on any render.
  const batchRunning = activeRunId !== null && !(batch?.run_id === activeRunId && batch.status !== "running");

  const diagnosisSourceByTxnId = useMemo(() => {
    const map: Record<string, DiagnosisSource> = {};
    for (const item of Object.values(workItemsMap)) {
      if (item.diagnosis) map[item.txn_id] = item.diagnosis.source;
    }
    return map;
  }, [workItemsMap]);

  const amountByTxnId = useMemo(() => {
    const map: Record<string, number> = {};
    for (const item of Object.values(workItemsMap)) map[item.txn_id] = item.amount_paise;
    return map;
  }, [workItemsMap]);

  const gateRejections: GateRejectionView[] = useMemo(() => {
    const source = isLive ? stream.gateRejections : FIXTURE_GATE_REJECTIONS;
    return source.map((r) => ({ ...r, customerName: workItemsMap[r.txn_id]?.customer.name }));
  }, [isLive, stream.gateRejections, workItemsMap]);

  const liveBatchProgress = isLive ? stream.batchProgress : null;
  const batchControlsStatus: BatchControlsStatus = !isLive ? "unavailable" : batchRunning ? "running" : "idle";

  const handleRunBatch = useCallback(async () => {
    setActionError(null);
    try {
      const accepted = await runBatch({ size: 50 });
      setActiveRunId(accepted.run_id);
    } catch (error) {
      setActionError(isApiClientError(error) ? error.message : "Could not start the batch.");
    }
  }, []);

  const handleInjectCase = useCallback(async () => {
    setActionError(null);
    setInjecting(true);
    try {
      await injectDemoCase(DEMO_INJECT_CASE);
    } catch (error) {
      setActionError(isApiClientError(error) ? error.message : "Could not inject the demo case.");
    } finally {
      setInjecting(false);
    }
  }, []);

  const handleReset = useCallback(() => {
    // The contract has no server-side reset endpoint (see the phase 10
    // report) — a reload re-runs the REST snapshot + WS handshake from
    // scratch, which is the closest honest equivalent of "start over" the
    // client can offer on its own.
    window.location.reload();
  }, []);

  return (
    <div className="console-grid flex min-h-screen flex-col">
      <header className="border-b border-console-border bg-console-panel/70 backdrop-blur">
        <div className="mx-auto flex w-full max-w-[1600px] flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div className="flex items-baseline gap-3">
            <h1 className="text-xl font-semibold tracking-tight text-console-text">Recoup</h1>
            <span className="font-mono text-xs uppercase tracking-[0.2em] text-console-accent">
              Recovery Console
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <BatchControls
              status={batchControlsStatus}
              disabledReason={
                !isLive
                  ? "Backend not connected — showing preview data."
                  : injecting
                    ? "Injecting demo case..."
                    : undefined
              }
              progress={liveBatchProgress ? { processed: liveBatchProgress.processed, size: liveBatchProgress.size } : null}
              onRunBatch={handleRunBatch}
              onInjectCase={handleInjectCase}
              onReset={handleReset}
            />
            <ConnectionStatus
              status={connectionStatus}
              detail={isLive ? `mode ${stream.status}` : "sample batch"}
            />
          </div>
        </div>
        {actionError && (
          <div className="border-t border-console-danger/40 bg-console-danger/10 px-6 py-2">
            <p className="mx-auto w-full max-w-[1600px] font-mono text-xs text-console-danger">{actionError}</p>
          </div>
        )}
      </header>

      <main className="mx-auto w-full max-w-[1600px] flex-1 px-6 py-6">
        <RecoveryCounter
          recoveredPaise={metrics.recovered_paise}
          recoveredCount={metrics.recovered}
          totalAtRisk={metrics.total_failed}
          recoveryRate={metrics.recovery_rate}
        />

        <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_400px] lg:items-start">
          <AuditTable
            events={auditEvents}
            amountByTxnId={amountByTxnId}
            diagnosisSourceByTxnId={diagnosisSourceByTxnId}
          />

          <div className="flex flex-col gap-5">
            <ConstraintRejections rejections={gateRejections} />
            <EscalationQueue escalations={escalations} />
            <ExceptionList exceptions={exceptions} totalAtRisk={metrics.total_failed} />
            <CauseBreakdown byCause={metrics.by_cause} byChannel={metrics.by_channel} />
          </div>
        </div>
      </main>

      <footer className="border-t border-console-border px-6 py-4">
        <p className="mx-auto w-full max-w-[1600px] font-mono text-[11px] text-console-muted">
          All money in integer paise · every action gated · every transition logged
        </p>
      </footer>
    </div>
  );
}
