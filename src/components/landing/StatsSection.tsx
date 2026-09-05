"use client";

import { type CSSProperties, useEffect, useRef, useState } from "react";

import { TARGETS, inr } from "./content";

/**
 * The honest numbers, counted up once when the section first scrolls into view.
 *
 * The count-up is driven by a single rAF loop writing one piece of state, eased
 * cubic-out over 1.8s, and the IntersectionObserver unobserves itself on the
 * first hit so the figures settle rather than replaying on every scroll past.
 *
 * Note on the float: the comp gives each card both a static `translateY` and an
 * `rc-float` animation whose keyframes start at `translate3d(0,0,0)`. The
 * animation wins outright, so the static offsets never render; only the
 * per-card duration and delay do. They are reproduced here, and the dead offset
 * is left out so the cards also sit correctly when a viewer has asked for
 * reduced motion and the animation is switched off.
 */

const CARD_BASE: CSSProperties = {
  borderRadius: 20,
  border: "1px solid rgba(255,255,255,0.09)",
  background: "rgba(255,255,255,0.03)",
  backdropFilter: "blur(18px)",
  WebkitBackdropFilter: "blur(18px)",
};

const LABEL: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  letterSpacing: "0.14em",
  textTransform: "uppercase",
  color: "rgba(233,233,240,0.45)",
};

const SUB: CSSProperties = { fontSize: 14, color: "rgba(233,233,240,0.5)" };
const SUB_SMALL: CSSProperties = { fontSize: 13, color: "rgba(233,233,240,0.48)" };

const BIG: CSSProperties = {
  marginTop: 14,
  fontSize: 42,
  fontWeight: 600,
  letterSpacing: "-0.03em",
  lineHeight: 1,
};

function useCountUpOnView<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    let raf = 0;

    // Someone who has asked for reduced motion gets the final figures rather
    // than a number spinning up at them. Settling it on the next frame instead
    // of inline keeps the first render's markup identical on server and client.
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      raf = requestAnimationFrame(() => setProgress(1));
      return () => cancelAnimationFrame(raf);
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          observer.unobserve(entry.target);
          const duration = 1800;
          const start = performance.now();
          const step = (now: number) => {
            const k = Math.min(1, (now - start) / duration);
            setProgress(1 - Math.pow(1 - k, 3));
            if (k < 1) raf = requestAnimationFrame(step);
          };
          raf = requestAnimationFrame(step);
        }
      },
      { threshold: 0.25 },
    );
    observer.observe(node);

    return () => {
      observer.disconnect();
      cancelAnimationFrame(raf);
    };
  }, []);

  return { ref, progress };
}

export default function StatsSection() {
  const { ref, progress } = useCountUpOnView<HTMLElement>();

  const recovered = `₹${inr((TARGETS.recoveredPaise / 100) * progress)}`;
  const recoveredTxns = inr(TARGETS.recoveredTxns * progress);
  const rate = `${(TARGETS.rate * progress).toFixed(1)}%`;
  const processed = inr(TARGETS.processed * progress);
  const escalations = Math.round(TARGETS.escalations * progress);
  const exceptions = Math.round(TARGETS.exceptions * progress);
  const rejections = Math.round(TARGETS.rejections * progress);
  const auditEvents = inr(TARGETS.auditEvents * progress);

  return (
    <section ref={ref} style={{ position: "relative", zIndex: 1, padding: "60px 32px 150px" }}>
      <div style={{ maxWidth: 1180, margin: "0 auto" }}>
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: 18,
            flexWrap: "wrap",
            marginBottom: 66,
          }}
        >
          <h2
            style={{
              margin: 0,
              fontSize: "clamp(30px, 4vw, 52px)",
              fontWeight: 600,
              letterSpacing: "-0.03em",
            }}
          >
            One batch run, honestly reported
          </h2>
          <span
            style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "rgba(233,233,240,0.4)" }}
          >
            exceptions included — a 100% recovery rate is a bug, not a win
          </span>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(12, 1fr)",
            gap: "72px 26px",
          }}
        >
          <div className="rc-float" style={{ gridColumn: "span 5", animationDuration: "7s" }}>
            <div
              style={{
                ...CARD_BASE,
                padding: "30px 30px 26px",
                background:
                  "linear-gradient(160deg, rgba(255,255,255,0.06), rgba(255,255,255,0.015))",
                boxShadow: "0 30px 70px -40px oklch(0.6 0.16 258 / 0.55)",
              }}
            >
              <div style={LABEL}>Total recovered volume</div>
              <div
                style={{
                  marginTop: 16,
                  fontSize: "clamp(40px, 5.4vw, 68px)",
                  fontWeight: 600,
                  letterSpacing: "-0.04em",
                  lineHeight: 1,
                  color: "#fff",
                }}
              >
                {recovered}
              </div>
              <div style={{ ...SUB, marginTop: 14 }}>
                across {recoveredTxns} recovered transactions
              </div>
            </div>
          </div>

          <div
            className="rc-float"
            style={{ gridColumn: "span 4", animationDuration: "8.5s", animationDelay: "0.6s" }}
          >
            <div
              style={{
                ...CARD_BASE,
                padding: 30,
                border: "1px solid oklch(0.78 0.13 197 / 0.22)",
                background:
                  "linear-gradient(160deg, oklch(0.78 0.13 197 / 0.1), rgba(255,255,255,0.015))",
              }}
            >
              <div style={LABEL}>Recovery rate</div>
              <div
                style={{
                  marginTop: 16,
                  fontSize: "clamp(40px, 5vw, 62px)",
                  fontWeight: 600,
                  letterSpacing: "-0.04em",
                  lineHeight: 1,
                  color: "oklch(0.9 0.1 197)",
                }}
              >
                {rate}
              </div>
              <div style={{ ...SUB, marginTop: 14 }}>of attempted recoveries reach RESOLVED</div>
            </div>
          </div>

          <div
            className="rc-float"
            style={{ gridColumn: "span 3", animationDuration: "9.5s", animationDelay: "1.2s" }}
          >
            <div style={{ ...CARD_BASE, padding: 26 }}>
              <div style={LABEL}>Payments processed</div>
              <div style={BIG}>{processed}</div>
            </div>
          </div>

          <div
            className="rc-float"
            style={{ gridColumn: "span 3", animationDuration: "8s", animationDelay: "0.3s" }}
          >
            <div
              style={{
                ...CARD_BASE,
                padding: 26,
                border: "1px solid oklch(0.8 0.14 75 / 0.28)",
                background:
                  "linear-gradient(160deg, oklch(0.8 0.14 75 / 0.1), rgba(255,255,255,0.015))",
              }}
            >
              <div style={LABEL}>Active escalations</div>
              <div style={{ ...BIG, color: "oklch(0.86 0.14 75)" }}>{escalations}</div>
              <div style={{ ...SUB_SMALL, marginTop: 12 }}>waiting in the human queue</div>
            </div>
          </div>

          <div
            className="rc-float"
            style={{ gridColumn: "span 4", animationDuration: "7.5s", animationDelay: "0.9s" }}
          >
            <div style={{ ...CARD_BASE, padding: 26 }}>
              <div style={LABEL}>Exceptions reported</div>
              <div style={BIG}>{exceptions}</div>
              <div style={{ ...SUB_SMALL, marginTop: 12 }}>
                every one carries its refusal reason
              </div>
            </div>
          </div>

          <div
            className="rc-float"
            style={{ gridColumn: "span 5", animationDuration: "9s", animationDelay: "1.6s" }}
          >
            <div
              style={{
                ...CARD_BASE,
                padding: "26px 30px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 24,
              }}
            >
              <div>
                <div style={LABEL}>Gate rejections</div>
                <div style={BIG}>{rejections}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={LABEL}>Audit events</div>
                <div style={BIG}>{auditEvents}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
