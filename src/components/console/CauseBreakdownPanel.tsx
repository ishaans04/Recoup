"use client";

import { formatPaise } from "@/lib/format";
import type { CauseMetric, ChannelMetric } from "@/lib/types";
import { humanise } from "@/lib/types";

import { EMPTY_NOTE, ENDPOINT, PANEL, PANEL_HEAD, PANEL_TITLE } from "./chrome";

/**
 * Two of PRD 15.1's six required figures: **recovery by cause** (which failure
 * types we recover best) and **actions taken by channel** (retry / voice / SMS
 * / email).
 *
 * Both are rendered as proportion bars rather than bare counts, because the
 * question each answers is comparative — "which cause recovers best" is a
 * shape, not a number. The bar is the recovered fraction of what was attempted,
 * and the count beside it is the honest denominator, so a cause that recovered
 * 1 of 1 cannot masquerade as a cause that recovered 40 of 40.
 *
 * Rows with no activity are kept, not filtered out. A cause the batch never saw
 * is information; hiding it would make the breakdown look more complete than
 * the run actually was.
 */

function Bar({ recovered, total, hue }: { recovered: number; total: number; hue: number }) {
  const fraction = total === 0 ? 0 : recovered / total;
  return (
    <div
      style={{
        position: "relative",
        height: 4,
        borderRadius: 2,
        background: "rgba(255,255,255,0.07)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          right: `${(1 - fraction) * 100}%`,
          borderRadius: 2,
          background: `oklch(0.78 0.13 ${hue})`,
          transition: "right 400ms ease",
        }}
      />
    </div>
  );
}

function Row({
  label,
  recovered,
  total,
  paise,
  hue,
}: {
  label: string;
  recovered: number;
  total: number;
  paise: number;
  hue: number;
}) {
  const dimmed = total === 0;
  return (
    <div style={{ display: "grid", gap: 7, opacity: dimmed ? 0.4 : 1 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 10,
          fontFamily: "var(--font-mono)",
          fontSize: 12,
        }}
      >
        <span style={{ color: "rgba(233,233,240,0.78)" }}>{label}</span>
        <span style={{ marginLeft: "auto", color: "rgba(233,233,240,0.45)" }}>
          {recovered}/{total}
        </span>
        <span style={{ color: "#fff", minWidth: 88, textAlign: "right" }}>
          {formatPaise(paise)}
        </span>
      </div>
      <Bar recovered={recovered} total={total} hue={hue} />
    </div>
  );
}

export default function CauseBreakdownPanel({
  byCause,
  byChannel,
}: {
  byCause: CauseMetric[];
  byChannel: ChannelMetric[];
}) {
  return (
    <div style={PANEL}>
      <div style={{ ...PANEL_HEAD, gap: 10 }}>
        <h2 style={PANEL_TITLE}>Recovery by cause</h2>
        <span style={ENDPOINT}>GET /api/metrics</span>
      </div>

      <div style={{ padding: "18px 22px", display: "grid", gap: 14 }}>
        {byCause.length === 0 ? (
          <div style={{ ...EMPTY_NOTE, padding: 0 }}>No causes diagnosed yet.</div>
        ) : (
          byCause.map((row) => (
            <Row
              key={row.cause}
              label={humanise(row.cause)}
              recovered={row.recovered}
              total={row.count}
              paise={row.recovered_paise}
              hue={197}
            />
          ))
        )}
      </div>

      <div
        style={{
          ...PANEL_HEAD,
          gap: 10,
          borderTop: "1px solid rgba(255,255,255,0.07)",
          borderBottom: "1px solid rgba(255,255,255,0.07)",
        }}
      >
        <h2 style={PANEL_TITLE}>Actions by channel</h2>
        <span style={ENDPOINT}>retry · voice · sms · email</span>
      </div>

      <div style={{ padding: "18px 22px", display: "grid", gap: 14 }}>
        {byChannel.length === 0 ? (
          <div style={{ ...EMPTY_NOTE, padding: 0 }}>No actions executed yet.</div>
        ) : (
          byChannel.map((row) => (
            <Row
              key={row.channel}
              label={humanise(row.channel)}
              recovered={row.recovered}
              total={row.attempted}
              paise={row.recovered_paise}
              hue={258}
            />
          ))
        )}
      </div>
    </div>
  );
}
