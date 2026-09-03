export type BatchControlsStatus = "idle" | "running" | "unavailable";

export interface BatchControlsProps {
  status: BatchControlsStatus;
  /** Shown next to the controls whenever they're disabled, so "why can't I
   * click this" always has an answer on screen. */
  disabledReason?: string | null;
  /** Only meaningful while status === "running". */
  progress?: { processed: number; size: number } | null;
  onRunBatch: () => void;
  onInjectCase: () => void;
  onReset: () => void;
}

/**
 * The three actions a judge (or the operator) can take: run the synthetic
 * batch, inject the ₹75,000 case that the constraint gate is guaranteed to
 * reject (PRD §16.5 — the live guardrail demo), and reset. Every button is
 * disabled with a stated reason rather than silently doing nothing, both
 * while a run is in flight and while the backend isn't reachable at all.
 */
export default function BatchControls({
  status,
  disabledReason,
  progress,
  onRunBatch,
  onInjectCase,
  onReset,
}: BatchControlsProps) {
  const busy = status === "running";
  const disabled = status !== "idle";
  const reason = disabled ? (disabledReason ?? (busy ? "A batch is running." : "Backend not connected.")) : null;

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        onClick={onRunBatch}
        disabled={disabled}
        className="rounded-md bg-console-accent px-3.5 py-2 font-mono text-xs font-semibold uppercase tracking-wider text-console-bg transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy && progress ? `Running ${progress.processed}/${progress.size}...` : "Run batch"}
      </button>

      <button
        type="button"
        onClick={onInjectCase}
        disabled={disabled}
        title="Injects one hand-crafted ₹75,000 failure that the amount cap is guaranteed to reject"
        className="rounded-md border border-console-warn/50 bg-console-warn/10 px-3.5 py-2 font-mono text-xs font-semibold uppercase tracking-wider text-console-warn transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
      >
        Inject Rs 75,000 case
      </button>

      <button
        type="button"
        onClick={onReset}
        disabled={disabled}
        className="rounded-md border border-console-border px-3.5 py-2 font-mono text-xs font-semibold uppercase tracking-wider text-console-muted transition-colors hover:text-console-text disabled:cursor-not-allowed disabled:opacity-40"
      >
        Reset
      </button>

      {reason && <span className="font-mono text-[11px] text-console-muted">{reason}</span>}

      {busy && progress && (
        <div className="h-1.5 w-40 overflow-hidden rounded-full bg-console-panel-raised" role="progressbar" aria-valuenow={progress.processed} aria-valuemin={0} aria-valuemax={progress.size}>
          <div
            className="h-full rounded-full bg-console-accent transition-[width]"
            style={{ width: `${Math.min(100, (progress.processed / Math.max(1, progress.size)) * 100)}%` }}
          />
        </div>
      )}
    </div>
  );
}
