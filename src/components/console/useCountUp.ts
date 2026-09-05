"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Animates a number from wherever it currently sits to a new target.
 *
 * PRD 8.8 asks for a *running* recovered counter and 16.2 wants it to climb in
 * near-real-time as the batch flows through — a figure that simply swaps from
 * one value to the next reads as a page refresh, not as money being recovered.
 *
 * The starting display is 0 rather than the target, so the figure climbs on
 * first paint as well as on every later update. That is deterministic on both
 * server and client, so it costs no hydration mismatch.
 *
 * The value is only ever *displayed* — every figure is still computed by the
 * backend, and this never rounds money into or out of existence: the final
 * frame assigns the exact target.
 */
export function useCountUp(target: number, durationMs = 900): number {
  const [display, setDisplay] = useState(0);
  const fromRef = useRef(0);

  useEffect(() => {
    const from = fromRef.current;
    if (from === target) return;

    let raf = 0;

    const settle = () => {
      fromRef.current = target;
      setDisplay(target);
    };

    // Reduced motion: land on the figure next frame rather than counting to it.
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      raf = requestAnimationFrame(settle);
      return () => cancelAnimationFrame(raf);
    }

    const start = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - k, 3);
      if (k < 1) {
        setDisplay(Math.round(from + (target - from) * eased));
        raf = requestAnimationFrame(step);
      } else {
        settle();
      }
    };
    raf = requestAnimationFrame(step);

    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);

  return display;
}
