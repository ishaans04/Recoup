"use client";

import { useState } from "react";

import { BENEFITS } from "./content";

/**
 * The argument, with the constraint gate pinned beside it.
 *
 * The left column sticks while the six claims scroll past it, so the gate — the
 * single door every rupee passes through — stays on screen for the whole
 * argument that depends on it. Behind the card, a conic gradient rotates and a
 * soft band sweeps down, which reads as a surface being continuously scanned.
 */
export default function WhySection() {
  const [hovered, setHovered] = useState<string | null>(null);

  return (
    <section id="why" style={{ position: "relative", zIndex: 1, padding: "40px 32px 160px" }}>
      <div
        style={{
          maxWidth: 1180,
          margin: "0 auto",
          display: "grid",
          gridTemplateColumns: "minmax(0, 0.85fr) minmax(0, 1.15fr)",
          gap: 70,
          alignItems: "start",
        }}
      >
        <div style={{ position: "sticky", top: 120, display: "grid", gap: 26 }}>
          <h2
            style={{
              margin: 0,
              fontSize: "clamp(30px, 3.6vw, 48px)",
              fontWeight: 600,
              letterSpacing: "-0.03em",
              lineHeight: 1.05,
            }}
          >
            Why merchants keep the money
          </h2>
          <p
            style={{
              margin: 0,
              fontSize: 17,
              lineHeight: 1.65,
              color: "rgba(233,233,240,0.6)",
              textWrap: "pretty",
            }}
          >
            A blind retry loop annoys customers, hammers degraded banks and recovers little. Recoup
            spends one action per failure, chosen from the cause, and can prove afterwards exactly
            why it made that choice.
          </p>

          <div
            style={{
              position: "relative",
              height: 260,
              borderRadius: 20,
              border: "1px solid rgba(255,255,255,0.08)",
              overflow: "hidden",
              background:
                "radial-gradient(120% 120% at 20% 0%, oklch(0.5 0.14 258 / 0.35), transparent 60%), rgba(255,255,255,0.02)",
            }}
          >
            <div
              data-rc-motion
              style={{
                position: "absolute",
                left: "50%",
                top: "50%",
                width: 420,
                height: 420,
                margin: "-210px 0 0 -210px",
                borderRadius: "50%",
                background:
                  "conic-gradient(from 0deg, transparent 0deg, oklch(0.8 0.13 197 / 0.55) 40deg, transparent 120deg)",
                animation: "rc-spin 9s linear infinite",
                filter: "blur(2px)",
              }}
            />
            <div
              style={{
                position: "absolute",
                inset: 22,
                borderRadius: 14,
                background: "rgba(6,6,10,0.72)",
                backdropFilter: "blur(10px)",
                WebkitBackdropFilter: "blur(10px)",
                border: "1px solid rgba(255,255,255,0.07)",
                display: "grid",
                placeItems: "center",
                padding: 24,
                textAlign: "center",
              }}
            >
              <div style={{ display: "grid", gap: 12, fontFamily: "var(--font-mono)" }}>
                <div
                  style={{
                    fontSize: 11,
                    letterSpacing: "0.16em",
                    textTransform: "uppercase",
                    color: "rgba(233,233,240,0.45)",
                  }}
                >
                  the only door
                </div>
                <div style={{ fontSize: 19, color: "#fff" }}>ConstraintGate.check()</div>
                <div style={{ fontSize: 12, lineHeight: 1.8, color: "rgba(233,233,240,0.55)" }}>
                  retry_count ≤ 3 · amount ≤ ₹50,000
                  <br />
                  fraud_flag == false
                </div>
                <div style={{ fontSize: 11, color: "oklch(0.86 0.14 75)" }}>
                  breach → escalate to human
                </div>
              </div>
            </div>
            <div
              data-rc-motion
              style={{
                position: "absolute",
                left: 0,
                right: 0,
                top: 0,
                height: 60,
                background: "linear-gradient(180deg, oklch(0.8 0.13 197 / 0.16), transparent)",
                animation: "rc-sweep 5s linear infinite",
              }}
            />
          </div>
        </div>

        <div style={{ display: "grid", gap: 16 }}>
          {BENEFITS.map((benefit) => {
            const isHovered = hovered === benefit.num;
            return (
              <div
                key={benefit.num}
                onMouseEnter={() => setHovered(benefit.num)}
                onMouseLeave={() => setHovered(null)}
                style={{
                  padding: "26px 28px",
                  borderRadius: 18,
                  border: `1px solid ${
                    isHovered ? "oklch(0.78 0.13 197 / 0.4)" : "rgba(255,255,255,0.08)"
                  }`,
                  background: isHovered ? "rgba(255,255,255,0.05)" : "rgba(255,255,255,0.028)",
                  backdropFilter: "blur(14px)",
                  WebkitBackdropFilter: "blur(14px)",
                  display: "grid",
                  gap: 10,
                  transition: "border-color 200ms ease, background 200ms ease",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <span
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 11,
                      color: "oklch(0.8 0.12 197)",
                    }}
                  >
                    {benefit.num}
                  </span>
                  <h3
                    style={{
                      margin: 0,
                      fontSize: 20,
                      fontWeight: 600,
                      letterSpacing: "-0.02em",
                    }}
                  >
                    {benefit.title}
                  </h3>
                </div>
                <p
                  style={{
                    margin: 0,
                    fontSize: 15.5,
                    lineHeight: 1.6,
                    color: "rgba(233,233,240,0.58)",
                    textWrap: "pretty",
                  }}
                >
                  {benefit.body}
                </p>
                <div
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 11.5,
                    color: "rgba(233,233,240,0.38)",
                  }}
                >
                  {benefit.proof}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
