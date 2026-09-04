"use client";

import { useEffect, useRef, useState } from "react";

import { formatPaise } from "@/lib/format";

const ANIMATION_MS = 700;

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

export interface RecoveryCounterProps {
  recoveredPaise: number;
  recoveredCount: number;
  /** Total at-risk transactions this run has seen — `metrics.total_failed`. */
  totalAtRisk: number;
  /** `metrics.recovery_rate`: recovered / attempted, 0..1. */
  recoveryRate: number;
}

/**
 * The headline. A large rupee figure that counts up as recoveries land
 * (PRD §16.2 — this is the number that climbs live during a batch run), with
 * the recovery rate and an honest "X of Y at-risk recovered" beneath it so
 * the headline number never reads as bigger than the batch it came from.
 */
export default function RecoveryCounter({
  recoveredPaise,
  recoveredCount,
  totalAtRisk,
  recoveryRate,
}: RecoveryCounterProps) {
  const [displayedPaise, setDisplayedPaise] = useState(0);
  const fromRef = useRef(0);
  const startRef = useRef<number | null>(null);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    const from = fromRef.current;
    const to = recoveredPaise;
    if (from === to) return;

    startRef.current = null;
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);

    const step = (timestamp: number) => {
      if (startRef.current === null) startRef.current = timestamp;
      const elapsed = timestamp - startRef.current;
      const progress = Math.min(1, elapsed / ANIMATION_MS);
      const eased = easeOutCubic(progress);
      const value = Math.round(from + (to - from) * eased);
      setDisplayedPaise(value);
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(step);
      } else {
        fromRef.current = to;
      }
    };
    frameRef.current = requestAnimationFrame(step);

    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [recoveredPaise]);

  const recoveryRatePct = `${Math.round(Math.min(1, Math.max(0, recoveryRate)) * 100)}%`;

  return (
    <div className="rounded-lg border border-console-border bg-console-panel p-6">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-console-muted">Recovered</p>
      <p
        className="mt-2 font-mono text-5xl font-semibold tabular-nums text-console-accent tracking-tight"
        aria-live="polite"
        data-testid="recovery-counter-value"
      >
        {formatPaise(displayedPaise)}
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-console-muted">
        <span>
          <span className="font-mono font-medium text-console-text">{recoveryRatePct}</span> recovery rate
        </span>
        <span aria-hidden="true" className="text-console-border">
          |
        </span>
        <span>
          <span className="font-mono font-medium text-console-text">{recoveredCount}</span> of{" "}
          <span className="font-mono font-medium text-console-text">{totalAtRisk}</span> at-risk recovered
        </span>
      </div>
    </div>
  );
}
