"use client";

import { useEffect, useRef, useState } from "react";

import { LANES, type Lane, NODE_LABELS, TICKERS } from "./content";

/**
 * Three real transactions from the preview batch, each walking the same six
 * stages — Detect, Diagnose, Decide, Gate, Act, Audit — and arriving somewhere
 * different. That is the whole argument of the product in one graphic: same
 * pipeline, different cause, different bounded action.
 *
 * The lanes are offset by one stage each (`stage - laneIndex`), so the pulse
 * cascades down the three rows rather than firing in unison. The third lane's
 * pipeline turns amber from the gate onward, because the gate refuses it: past
 * that point the run is an escalation, and it is coloured like one.
 */

interface NodeStyle {
  label: string;
  dot: string;
  glow: string;
  line: string;
  text: string;
}

function nodeStyle(index: number, stage: number, lane: Lane): NodeStyle {
  const label = index === 4 ? lane.actLabel : NODE_LABELS[index];
  // Everything from the gate onward on a refused lane is drawn in the refusal
  // hue, so the eye sees where the run stopped being a recovery.
  const refused = lane.refuse && index >= 3;
  const hue = refused ? 75 : lane.hue;
  const c = (lightness: number, alpha: number) => `oklch(${lightness} 0.13 ${hue} / ${alpha})`;

  if (stage === index) {
    return {
      label,
      dot: c(0.82, 1),
      glow: `0 0 18px ${c(0.8, 0.9)}`,
      line: `linear-gradient(90deg, ${c(0.7, 0.6)}, rgba(255,255,255,0.07))`,
      text: "#fff",
    };
  }
  if (stage > index) {
    return {
      label,
      dot: c(0.66, 0.9),
      glow: "none",
      line: `linear-gradient(90deg, ${c(0.6, 0.4)}, ${c(0.6, 0.25)})`,
      text: refused ? c(0.86, 0.95) : "rgba(233,233,240,0.7)",
    };
  }
  return {
    label,
    dot: "rgba(255,255,255,0.14)",
    glow: "none",
    line: "rgba(255,255,255,0.06)",
    text: "rgba(233,233,240,0.3)",
  };
}

export default function FlowSection() {
  const sectionRef = useRef<HTMLElement>(null);
  const [stage, setStage] = useState(-1);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const node = sectionRef.current;
    if (!node) return;

    let timer: ReturnType<typeof setInterval> | null = null;

    // Reduced motion: show every lane at its final state rather than cycling.
    // Settled on the next frame so the first render matches the server's.
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      const raf = requestAnimationFrame(() => setStage(8));
      return () => cancelAnimationFrame(raf);
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          observer.unobserve(entry.target);
          setStage(0);
          timer = setInterval(() => {
            setStage((previous) => {
              const next = previous >= 8 ? 0 : previous + 1;
              if (next === 0) setTick((t) => t + 1);
              return next;
            });
          }, 820);
        }
      },
      { threshold: 0.25 },
    );
    observer.observe(node);

    return () => {
      observer.disconnect();
      if (timer) clearInterval(timer);
    };
  }, []);

  return (
    <section
      id="flow"
      ref={sectionRef}
      style={{ position: "relative", zIndex: 1, padding: "40px 32px 150px" }}
    >
      <div style={{ maxWidth: 1180, margin: "0 auto" }}>
        <div style={{ maxWidth: 760, marginBottom: 54 }}>
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              letterSpacing: "0.16em",
              textTransform: "uppercase",
              color: "oklch(0.8 0.12 197)",
            }}
          >
            A run in progress
          </div>
          <h2
            style={{
              margin: "16px 0 0",
              fontSize: "clamp(30px, 4vw, 52px)",
              fontWeight: 600,
              letterSpacing: "-0.03em",
              lineHeight: 1.05,
            }}
          >
            Three failures, three causes, three different actions.
          </h2>
          <p
            style={{
              margin: "18px 0 0",
              fontSize: 17,
              lineHeight: 1.6,
              color: "rgba(233,233,240,0.6)",
              textWrap: "pretty",
            }}
          >
            Detect from the webhook. Diagnose with rules first, a model only for the ambiguous tail.
            Decide one bounded action. Pass the constraint gate — the only door to moving money.
            Append every transition to the immutable log.
          </p>
        </div>

        <div style={{ display: "grid", gap: 18 }}>
          {LANES.map((lane, laneIndex) => {
            const laneStage = stage < 0 ? -1 : stage - laneIndex;
            const finished = laneStage >= 6;
            return (
              <div
                key={lane.id}
                style={{
                  padding: "22px 26px 24px",
                  borderRadius: 18,
                  border: "1px solid rgba(255,255,255,0.08)",
                  background:
                    "linear-gradient(150deg, rgba(255,255,255,0.045), rgba(255,255,255,0.012))",
                  backdropFilter: "blur(16px)",
                  WebkitBackdropFilter: "blur(16px)",
                  display: "grid",
                  gap: 20,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 16,
                    flexWrap: "wrap",
                    fontFamily: "var(--font-mono)",
                    fontSize: 12.5,
                  }}
                >
                  <span style={{ color: "#fff" }}>{lane.id}</span>
                  <span style={{ color: "rgba(233,233,240,0.5)" }}>{lane.amount}</span>
                  <span
                    style={{
                      padding: "4px 10px",
                      borderRadius: 6,
                      border: "1px solid rgba(255,255,255,0.12)",
                      background: "rgba(255,255,255,0.04)",
                      color: "rgba(233,233,240,0.72)",
                    }}
                  >
                    {lane.cause}
                  </span>
                  <span style={{ marginLeft: "auto", color: "rgba(233,233,240,0.35)" }}>
                    {lane.tier}
                  </span>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 0 }}>
                  {NODE_LABELS.map((_, index) => {
                    const n = nodeStyle(index, laneStage, lane);
                    return (
                      <div
                        key={index}
                        style={{
                          position: "relative",
                          display: "grid",
                          gap: 12,
                          paddingRight: 12,
                        }}
                      >
                        <div
                          style={{
                            position: "relative",
                            height: 12,
                            display: "flex",
                            alignItems: "center",
                          }}
                        >
                          <div
                            style={{
                              position: "absolute",
                              left: 0,
                              right: 0,
                              height: 1,
                              background: n.line,
                            }}
                          />
                          <div
                            style={{
                              position: "relative",
                              width: 12,
                              height: 12,
                              borderRadius: "50%",
                              background: n.dot,
                              boxShadow: n.glow,
                              transition: "background 240ms ease, box-shadow 240ms ease",
                            }}
                          />
                        </div>
                        <div
                          style={{
                            fontFamily: "var(--font-mono)",
                            fontSize: 11,
                            letterSpacing: "0.06em",
                            textTransform: "uppercase",
                            color: n.text,
                            transition: "color 240ms ease",
                          }}
                        >
                          {n.label}
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    fontFamily: "var(--font-mono)",
                    fontSize: 13,
                    opacity: finished ? 1 : 0.12,
                    color: lane.refuse ? "oklch(0.86 0.14 75)" : "oklch(0.86 0.13 145)",
                    transition: "opacity 320ms ease",
                  }}
                >
                  <span style={{ letterSpacing: "0.1em" }}>{lane.outState}</span>
                  <span style={{ color: "rgba(233,233,240,0.62)" }}>
                    {finished ? lane.outcome : "—"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        <div
          style={{
            marginTop: 28,
            display: "flex",
            alignItems: "center",
            gap: 14,
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "rgba(233,233,240,0.42)",
          }}
        >
          <span
            className="rc-pulse"
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: "oklch(0.8 0.14 145)",
              animationDuration: "1.6s",
            }}
          />
          {TICKERS[tick % TICKERS.length]}
        </div>
      </div>
    </section>
  );
}
