import type { CauseMetric, ChannelMetric } from "@/lib/types";
import { humanise } from "@/lib/types";
import { formatPaise } from "@/lib/format";

export interface CauseBreakdownProps {
  byCause: CauseMetric[];
  byChannel: ChannelMetric[];
}

/**
 * Two small categorical comparisons rendered as labelled horizontal bars —
 * no chart library (design direction): CSS bars load instantly, need no
 * dependency, and a labelled bar beats a library for two series this short.
 * Recovered counts render as a filled sub-segment of green inside the bar,
 * so "how much of this cause recovers" is visible without a legend.
 */
export default function CauseBreakdown({ byCause, byChannel }: CauseBreakdownProps) {
  const causeMax = Math.max(1, ...byCause.map((c) => c.count));
  const channelMax = Math.max(1, ...byChannel.map((c) => c.attempted));

  return (
    <div className="rounded-lg border border-console-border bg-console-panel p-5">
      <h2 className="text-sm font-medium tracking-tight text-console-text">Breakdown</h2>

      <section className="mt-4" aria-label="Recovery by cause">
        <h3 className="font-mono text-[11px] uppercase tracking-wider text-console-muted">Recovery by cause</h3>
        <ul className="mt-2 space-y-2.5">
          {byCause.map((c) => (
            <li key={c.cause}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs text-console-text">{humanise(c.cause)}</span>
                <span className="font-mono text-[11px] text-console-muted">
                  {c.recovered}/{c.count} · {formatPaise(c.recovered_paise)}
                </span>
              </div>
              <div className="mt-1 h-2 w-full overflow-hidden rounded-sm bg-console-panel-raised">
                <div
                  className="h-full rounded-sm bg-console-border"
                  style={{ width: `${(c.count / causeMax) * 100}%` }}
                >
                  <div
                    className="h-full rounded-sm bg-console-accent"
                    style={{ width: c.count === 0 ? "0%" : `${(c.recovered / c.count) * 100}%` }}
                  />
                </div>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-5" aria-label="Actions by channel">
        <h3 className="font-mono text-[11px] uppercase tracking-wider text-console-muted">Actions by channel</h3>
        <ul className="mt-2 space-y-2.5">
          {byChannel.map((c) => (
            <li key={c.channel}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs text-console-text">{humanise(c.channel)}</span>
                <span className="font-mono text-[11px] text-console-muted">
                  {c.recovered}/{c.attempted} · {formatPaise(c.recovered_paise)}
                </span>
              </div>
              <div className="mt-1 h-2 w-full overflow-hidden rounded-sm bg-console-panel-raised">
                <div
                  className="h-full rounded-sm bg-console-border"
                  style={{ width: `${(c.attempted / channelMax) * 100}%` }}
                >
                  <div
                    className="h-full rounded-sm bg-console-accent"
                    style={{ width: c.attempted === 0 ? "0%" : `${(c.recovered / c.attempted) * 100}%` }}
                  />
                </div>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
