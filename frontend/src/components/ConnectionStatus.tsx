export type ConnectionStatusValue = "live" | "connecting" | "reconnecting" | "preview";

export interface ConnectionStatusProps {
  status: ConnectionStatusValue;
  /** Free-form detail shown next to the label — backend mode/version when
   * live, the reason preview data is showing when not. */
  detail?: string;
}

const VISUALS: Record<ConnectionStatusValue, { dot: string; label: string; pulse: boolean }> = {
  live: { dot: "bg-console-accent", label: "live", pulse: false },
  connecting: { dot: "bg-console-warn", label: "connecting", pulse: true },
  reconnecting: { dot: "bg-console-warn", label: "reconnecting", pulse: true },
  preview: { dot: "bg-console-info", label: "preview data", pulse: false },
};

/**
 * Always visible in the header. Three real states (live / connecting /
 * reconnecting) plus preview — and preview gets an unmistakable badge of its
 * own, not just a dot, because the one failure mode this screen cannot allow
 * is a judge mistaking sample data for a live run.
 */
export default function ConnectionStatus({ status, detail }: ConnectionStatusProps) {
  const visual = VISUALS[status];

  return (
    <div className="flex items-center gap-2">
      <div
        className="flex items-center gap-2.5 rounded-full border border-console-border bg-console-panel-raised px-3.5 py-1.5"
        role="status"
        aria-live="polite"
      >
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${visual.dot} ${visual.pulse ? "status-pulse" : ""}`}
          aria-hidden="true"
        />
        <span className="font-mono text-xs tracking-wide text-console-text">{visual.label}</span>
        {detail && <span className="font-mono text-xs text-console-muted">{detail}</span>}
      </div>
      {status === "preview" && (
        <span
          className="rounded border border-console-info/60 bg-console-info/10 px-2 py-1 font-mono text-[10px] font-bold uppercase tracking-widest text-console-info"
          data-testid="preview-data-badge"
        >
          Preview data
        </span>
      )}
    </div>
  );
}
