"use client";

import { useEffect, useRef } from "react";

/**
 * The fixed field every page sits on: two or three heavily blurred colour blobs
 * that drift toward the cursor, a faint masked grid over them, and (on the
 * landing page) a vignette closing the bottom edge.
 *
 * The blobs are moved by writing `transform` directly on the nodes inside a
 * single `requestAnimationFrame` loop, never through React state. A cursor that
 * moves across the screen would otherwise re-render the whole page tree sixty
 * times a second; here it touches three DOM nodes and nothing else. The easing
 * is a plain lerp toward the pointer, so the field lags the cursor rather than
 * snapping to it.
 *
 * Each blob takes a different parallax coefficient — and blob C's is negative —
 * so they separate as the pointer travels instead of sliding as one sheet.
 */

export type BackdropVariant = "landing" | "console";

interface BlobSpec {
  size: string;
  blur: string;
  opacity: number;
  background: string;
  /** Parallax coefficients: how far this blob travels per unit of cursor offset. */
  px: number;
  py: number;
}

interface VariantSpec {
  ground: string;
  top: string;
  gridSize: string;
  gridAlpha: string;
  gridMask: string;
  vignette: string | null;
  blobs: BlobSpec[];
}

const VARIANTS: Record<BackdropVariant, VariantSpec> = {
  landing: {
    ground: "radial-gradient(120% 90% at 50% 0%, #0c0c14 0%, #06060a 60%, #040407 100%)",
    top: "40%",
    gridSize: "72px 72px",
    gridAlpha: "rgba(255,255,255,0.032)",
    gridMask: "radial-gradient(80% 60% at 50% 35%, #000 0%, transparent 85%)",
    vignette: "radial-gradient(100% 70% at 50% 110%, transparent 40%, #040407 100%)",
    blobs: [
      {
        size: "78vw",
        blur: "90px",
        opacity: 0.5,
        background:
          "radial-gradient(circle at 50% 50%, oklch(0.62 0.16 258 / 0.85) 0%, oklch(0.55 0.14 258 / 0.25) 45%, transparent 70%)",
        px: 0.55,
        py: 0.5,
      },
      {
        size: "58vw",
        blur: "80px",
        opacity: 0.42,
        background:
          "radial-gradient(circle at 50% 50%, oklch(0.7 0.15 197 / 0.8) 0%, oklch(0.6 0.13 197 / 0.2) 45%, transparent 70%)",
        px: 0.95,
        py: 0.85,
      },
      {
        size: "46vw",
        blur: "70px",
        opacity: 0.34,
        background:
          "radial-gradient(circle at 50% 50%, oklch(0.72 0.15 328 / 0.8) 0%, oklch(0.62 0.12 328 / 0.18) 45%, transparent 70%)",
        px: -0.7,
        py: -0.55,
      },
    ],
  },
  console: {
    ground: "radial-gradient(120% 90% at 50% -10%, #0b0b13 0%, #06060a 55%, #040407 100%)",
    top: "30%",
    gridSize: "64px 64px",
    gridAlpha: "rgba(255,255,255,0.03)",
    gridMask: "radial-gradient(90% 70% at 50% 0%, #000 0%, transparent 90%)",
    vignette: null,
    blobs: [
      {
        size: "70vw",
        blur: "100px",
        opacity: 0.35,
        background:
          "radial-gradient(circle at 50% 50%, oklch(0.6 0.15 258 / 0.8) 0%, transparent 68%)",
        px: 0.5,
        py: 0.45,
      },
      {
        size: "48vw",
        blur: "90px",
        opacity: 0.28,
        background:
          "radial-gradient(circle at 50% 50%, oklch(0.7 0.14 197 / 0.8) 0%, transparent 68%)",
        px: -0.8,
        py: -0.6,
      },
    ],
  },
};

export default function AuroraBackdrop({ variant = "landing" }: { variant?: BackdropVariant }) {
  const spec = VARIANTS[variant];
  const blobRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    // A pointer-driven parallax is motion the viewer causes rather than motion
    // the page inflicts, but someone who has asked for reduced motion still gets
    // the field at rest rather than a drifting one.
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;

    const startY = variant === "landing" ? 0.4 : 0.3;
    const pos = { x: 0.5, y: startY, tx: 0.5, ty: startY };

    const onMove = (event: MouseEvent) => {
      pos.tx = event.clientX / window.innerWidth;
      pos.ty = event.clientY / window.innerHeight;
    };
    window.addEventListener("mousemove", onMove, { passive: true });

    let raf = 0;
    const loop = () => {
      pos.x += (pos.tx - pos.x) * 0.06;
      pos.y += (pos.ty - pos.y) * 0.06;
      const dx = (pos.x - 0.5) * window.innerWidth;
      const dy = (pos.y - 0.5) * window.innerHeight;
      spec.blobs.forEach((blob, index) => {
        const node = blobRefs.current[index];
        if (node) {
          node.style.transform = `translate3d(${dx * blob.px}px, ${dy * blob.py}px, 0)`;
        }
      });
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);

    return () => {
      window.removeEventListener("mousemove", onMove);
      cancelAnimationFrame(raf);
    };
  }, [spec, variant]);

  return (
    <div
      aria-hidden="true"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 0,
        pointerEvents: "none",
        overflow: "hidden",
        background: spec.ground,
      }}
    >
      {spec.blobs.map((blob, index) => (
        <div
          key={index}
          ref={(node) => {
            blobRefs.current[index] = node;
          }}
          style={{
            position: "absolute",
            left: "50%",
            top: spec.top,
            width: blob.size,
            height: blob.size,
            margin: `calc(${blob.size} / -2) 0 0 calc(${blob.size} / -2)`,
            borderRadius: "50%",
            filter: `blur(${blob.blur})`,
            opacity: blob.opacity,
            background: blob.background,
            willChange: "transform",
          }}
        />
      ))}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: `linear-gradient(${spec.gridAlpha} 1px, transparent 1px), linear-gradient(90deg, ${spec.gridAlpha} 1px, transparent 1px)`,
          backgroundSize: spec.gridSize,
          maskImage: spec.gridMask,
          WebkitMaskImage: spec.gridMask,
        }}
      />
      {spec.vignette !== null && (
        <div style={{ position: "absolute", inset: 0, background: spec.vignette }} />
      )}
    </div>
  );
}
