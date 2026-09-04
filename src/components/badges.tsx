/**
 * Small, shared visual vocabulary used across every panel: state pills,
 * pass/fail gate badges, and the rules-vs-LLM source badge.
 *
 * Colour is reserved for the five meanings the design direction defines and
 * nothing else: green = recovered/pass, amber = escalated/exception, red =
 * gate rejection/fraud block, blue = scheduled/parked, default foreground =
 * neutral/in-progress. The diagnosis source badge (rules/llm/fallback) is a
 * different axis — which tier produced a diagnosis, not a status — so it is
 * differentiated by icon, label and weight instead of borrowing one of those
 * five colours for a sixth meaning. `fallback` is the one exception: a
 * fallback diagnosis means the LLM's output could not be used, which *is* a
 * caution, so it legitimately carries the amber that caution already means
 * elsewhere on the page.
 *
 * Every colour-coded element also carries a text label, so the meaning
 * survives greyscale and colour blindness (design direction, accessibility).
 */

import type { ConstraintResult, DiagnosisSource, State } from "@/lib/types";
import { humanise } from "@/lib/types";
import { formatState } from "@/lib/format";

type StateVisual = { dot: string; text: string };

const STATE_VISUALS: Record<State, StateVisual> = {
  DETECTED: { dot: "bg-console-muted", text: "text-console-muted" },
  DIAGNOSED: { dot: "bg-console-muted", text: "text-console-muted" },
  ACTION_CHOSEN: { dot: "bg-console-muted", text: "text-console-muted" },
  CONSTRAINT_CHECKED: { dot: "bg-console-muted", text: "text-console-muted" },
  SCHEDULED: { dot: "bg-console-info", text: "text-console-info" },
  EXECUTED: { dot: "bg-console-info", text: "text-console-info" },
  RESOLVED: { dot: "bg-console-accent", text: "text-console-accent" },
  ESCALATED: { dot: "bg-console-warn", text: "text-console-warn" },
};

/** A compact state pill: a coloured dot plus the human label, never colour alone. */
export function StateBadge({ state }: { state: State }) {
  const visual = STATE_VISUALS[state] ?? { dot: "bg-console-muted", text: "text-console-muted" };
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap font-mono text-xs">
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${visual.dot}`} aria-hidden="true" />
      <span className={visual.text}>{formatState(state)}</span>
    </span>
  );
}

/** The gate's verdict. PASS is green with a check; FAIL is red with a cross —
 * this is the one badge on the page that is allowed to shout. */
export function ConstraintBadge({ result }: { result: ConstraintResult | null }) {
  if (result === null) {
    return <span className="font-mono text-xs text-console-muted">&mdash;</span>;
  }
  if (result === "FAIL") {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-console-danger/50 bg-console-danger/10 px-1.5 py-0.5 font-mono text-xs font-semibold text-console-danger">
        <span aria-hidden="true">&#10007;</span> FAIL
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded border border-console-accent/40 bg-console-accent/10 px-1.5 py-0.5 font-mono text-xs font-semibold text-console-accent">
      <span aria-hidden="true">&#10003;</span> PASS
    </span>
  );
}

const SOURCE_LABEL: Record<DiagnosisSource, string> = {
  rules: "RULES",
  llm: "LLM",
  fallback: "FALLBACK",
};

const SOURCE_ICON: Record<DiagnosisSource, string> = {
  rules: "▦", // ▦ — structured / deterministic
  llm: "✦", // ✦ — model-produced
  fallback: "⚠", // ⚠ — degraded, needs caution
};

/**
 * Distinguishes a Tier-1 (rules table) diagnosis from a Tier-2 (LLM) one at a
 * glance — PRD §11's two-tier engine made visible in the audit table. `rules`
 * and `llm` are neutral, differentiated by icon and letter-spacing rather
 * than colour; `fallback` carries amber because it means the diagnosis
 * degraded to a safe default rather than a considered classification.
 */
export function SourceBadge({ source }: { source: DiagnosisSource }) {
  const isFallback = source === "fallback";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold tracking-widest ${
        isFallback
          ? "border-console-warn/50 bg-console-warn/10 text-console-warn"
          : "border-console-border bg-console-panel-raised text-console-text"
      }`}
      title={
        source === "rules"
          ? "Diagnosed by the deterministic Tier-1 rules table"
          : source === "llm"
            ? "Diagnosed by the Tier-2 LLM"
            : "LLM output was unusable; fell back to a safe default"
      }
    >
      <span aria-hidden="true">{SOURCE_ICON[source]}</span>
      {SOURCE_LABEL[source] ?? source.toUpperCase()}
    </span>
  );
}

/** Renders any contract enum value as a human label, including one this
 * build doesn't recognise (contract rule 5.4 — an audit view must never
 * silently drop a row for an unfamiliar value; it just can't title-case a
 * meaning it doesn't know, only the words). */
export function CauseLabel({ cause }: { cause: string }) {
  return <span className="text-console-text">{humanise(cause)}</span>;
}
