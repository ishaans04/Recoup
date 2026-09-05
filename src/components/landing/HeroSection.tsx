"use client";

import Link from "next/link";

/**
 * The opening screen: the claim, the discipline underneath it, and the two ways
 * in. The wordmark is a gradient clipped to the text, running white → blue →
 * violet down the glyphs so it reads as lit from above by the aurora behind it.
 */
export default function HeroSection() {
  return (
    <section
      style={{
        position: "relative",
        zIndex: 1,
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "140px 32px 90px",
        textAlign: "center",
      }}
    >
      <div style={{ maxWidth: 940, display: "grid", gap: 30, justifyItems: "center" }}>
        <h1
          style={{
            margin: 0,
            fontSize: "clamp(64px, 12vw, 168px)",
            fontWeight: 700,
            letterSpacing: "-0.05em",
            lineHeight: 0.9,
            background:
              "linear-gradient(175deg, #ffffff 10%, oklch(0.82 0.09 240) 55%, oklch(0.6 0.1 300) 100%)",
            WebkitBackgroundClip: "text",
            backgroundClip: "text",
            color: "transparent",
          }}
        >
          Recoup
        </h1>

        <p
          style={{
            margin: 0,
            maxWidth: 720,
            fontSize: "clamp(20px, 2.4vw, 30px)",
            lineHeight: 1.35,
            color: "rgba(233,233,240,0.82)",
            textWrap: "pretty",
          }}
        >
          Recovery is a state machine, not a chatbot. Recoup finds the{" "}
          <em style={{ fontStyle: "normal", color: "#fff" }}>root cause</em> of every failed payment
          and takes one bounded action — never a blind retry loop.
        </p>

        <p
          style={{
            margin: 0,
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            lineHeight: 1.9,
            color: "rgba(233,233,240,0.45)",
          }}
        >
          The LLM diagnoses. The state machine decides.
          <br />
          The constraint gate guards. The audit log proves it.
        </p>

        <div
          style={{
            display: "flex",
            gap: 14,
            flexWrap: "wrap",
            justifyContent: "center",
            marginTop: 6,
          }}
        >
          <Link
            href="/console"
            style={{
              padding: "14px 26px",
              borderRadius: 999,
              background: "#f2f2f7",
              color: "#06060a",
              fontWeight: 600,
              fontSize: 15,
              textDecoration: "none",
            }}
          >
            Open the live console
          </Link>
          <a
            href="#flow"
            style={{
              padding: "14px 26px",
              borderRadius: 999,
              border: "1px solid rgba(255,255,255,0.16)",
              color: "rgba(233,233,240,0.8)",
              fontSize: 15,
              textDecoration: "none",
            }}
          >
            Watch a recovery run
          </a>
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          bottom: 34,
          left: "50%",
          transform: "translateX(-50%)",
          display: "grid",
          gap: 10,
          justifyItems: "center",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: "0.18em",
          color: "rgba(233,233,240,0.3)",
        }}
      >
        SCROLL
        <div
          style={{
            width: 1,
            height: 46,
            background: "linear-gradient(180deg, rgba(255,255,255,0.35), transparent)",
            overflow: "hidden",
          }}
        />
      </div>
    </section>
  );
}
