"use client";

import Link from "next/link";

/**
 * The fixed landing header: mark, wordmark, the discipline in three words, and
 * the two anchors plus the console link. It sits above the aurora field on a
 * blurred gradient that fades to transparent, so the page scrolls under it
 * rather than behind a hard bar.
 */
export default function LandingHeader() {
  return (
    <header
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 20,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "18px 32px",
        backdropFilter: "blur(14px)",
        WebkitBackdropFilter: "blur(14px)",
        background: "linear-gradient(180deg, rgba(6,6,10,0.82), rgba(6,6,10,0.25))",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-0.01em" }}>Recoup</span>
      </div>
      <nav style={{ display: "flex", alignItems: "center", gap: 26, fontSize: 14 }}>
        <a href="#flow" style={{ color: "rgba(233,233,240,0.62)", textDecoration: "none" }}>
          How it works
        </a>
        <a href="#why" style={{ color: "rgba(233,233,240,0.62)", textDecoration: "none" }}>
          Why it holds
        </a>
        <Link
          href="/console"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            padding: "9px 16px",
            borderRadius: 999,
            border: "1px solid oklch(0.78 0.13 197 / 0.4)",
            background: "oklch(0.78 0.13 197 / 0.1)",
            color: "oklch(0.88 0.1 197)",
            fontWeight: 500,
            textDecoration: "none",
          }}
        >
          Open console →
        </Link>
      </nav>
    </header>
  );
}
