"use client";

import Link from "next/link";

/**
 * The closing panel and the footer line. The invitation is the demo's own hero
 * moment (PRD 16.5): inject the ₹75,000 case and watch the gate refuse it in
 * front of you, rather than being told that it would.
 */
export default function CtaSection() {
  return (
    <section style={{ position: "relative", zIndex: 1, padding: "0 32px 120px" }}>
      <div
        style={{
          maxWidth: 1180,
          margin: "0 auto",
          padding: "60px 48px",
          borderRadius: 26,
          border: "1px solid rgba(255,255,255,0.1)",
          background:
            "linear-gradient(150deg, oklch(0.55 0.14 258 / 0.22), rgba(255,255,255,0.02))",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 40,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "grid", gap: 14, maxWidth: 620 }}>
          <h2
            style={{
              margin: 0,
              fontSize: "clamp(28px, 3.4vw, 44px)",
              fontWeight: 600,
              letterSpacing: "-0.03em",
              lineHeight: 1.08,
            }}
          >
            Inject the ₹75,000 case and watch the gate say no.
          </h2>
          <p
            style={{
              margin: 0,
              fontSize: 16,
              lineHeight: 1.6,
              color: "rgba(233,233,240,0.62)",
            }}
          >
            The operations console reads the append-only log live over WebSocket — work items, gate
            refusals, the human queue and honest metrics.
          </p>
        </div>
        <Link
          href="/console"
          style={{
            padding: "16px 30px",
            borderRadius: 999,
            background: "#f2f2f7",
            color: "#06060a",
            fontWeight: 600,
            fontSize: 16,
            whiteSpace: "nowrap",
            textDecoration: "none",
          }}
        >
          Open console →
        </Link>
      </div>

      <div
        style={{
          maxWidth: 1180,
          margin: "40px auto 0",
          display: "flex",
          justifyContent: "space-between",
          gap: 20,
          flexWrap: "wrap",
          fontFamily: "var(--font-mono)",
          fontSize: 11.5,
          color: "rgba(233,233,240,0.32)",
        }}
      >
        <span>Recoup · FastAPI + SQLite append-only audit · Next.js console</span>
      </div>
    </section>
  );
}
