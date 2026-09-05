"use client";

import { formatPaise } from "@/lib/format";
import type { Metrics } from "@/lib/types";

import { GLASS, MICRO_LABEL } from "./chrome";
import { useCountUp } from "./useCountUp";

/**
 * The five figures across the top of the console, straight from
 * `GET /api/metrics` (and refreshed by every `metrics.updated` frame).
 *
 * The recovery rate is shown to one decimal and never rounded up to a whole
 * number, because the difference between "53%" and "52.7%" is the difference
 * between a claim and a measurement. `lastAuditId` is the highest audit row id
 * the page has seen, which doubles as the append-only log's length.
 */
export default function MetricCards({
  metrics,
  lastAuditId,
}: {
  metrics: Metrics;
  lastAuditId: number;
}) {
  // The headline number climbs rather than jumping, so a batch running behind
  // it is visible as money arriving (PRD 8.8, 16.2).
  const climbingPaise = useCountUp(metrics.recovered_paise);
  const climbingRate = useCountUp(Math.round(metrics.recovery_rate * 1000));

  const cards = [
    {
      label: "Recovered volume",
      value: formatPaise(climbingPaise),
      sub: `${metrics.recovered} recovered txns`,
      color: "#fff",
      testId: "recovery-counter-value",
    },
    {
      label: "Recovery rate",
      value: `${(climbingRate / 10).toFixed(1)}%`,
      sub: "exceptions included",
      color: "oklch(0.9 0.1 197)",
    },
    {
      label: "In flight",
      value: String(metrics.in_flight),
      sub: "diagnosing · scheduled · executing",
      color: "#fff",
    },
    {
      label: "Escalations",
      value: String(metrics.escalated),
      sub: "human queue depth",
      color: "oklch(0.88 0.12 75)",
    },
    {
      label: "Audit events",
      value: lastAuditId > 0 ? `#${lastAuditId}` : "—",
      sub: "append-only · never mutated",
      color: "#fff",
    },
  ];

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(215px, 1fr))",
        gap: 16,
      }}
    >
      {cards.map((card) => (
        <div
          key={card.label}
          style={{
            ...GLASS,
            padding: "20px 22px",
            borderRadius: 16,
            display: "grid",
            gap: 12,
          }}
        >
          <div style={MICRO_LABEL}>{card.label}</div>
          <div
            data-testid={card.testId}
            style={{
              fontSize: 32,
              fontWeight: 600,
              letterSpacing: "-0.03em",
              lineHeight: 1,
              color: card.color,
            }}
          >
            {card.value}
          </div>
          <div
            style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "rgba(233,233,240,0.4)" }}
          >
            {card.sub}
          </div>
        </div>
      ))}
    </div>
  );
}
