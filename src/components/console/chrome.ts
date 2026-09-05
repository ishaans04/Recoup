import type { CSSProperties } from "react";

/**
 * The console's shared chrome: the liquid-glass panel shell, its header strip,
 * and the type scales every panel uses. Defined once so a dozen panels cannot
 * drift a pixel apart from each other.
 *
 * "Liquid glass" here is four layers stacked in a specific order, and every
 * surface on the console is built from the same four:
 *
 *   1. a *saturating* backdrop blur, so the aurora field behind the panel
 *      bleeds through as colour rather than as grey mush;
 *   2. a diagonal white gradient for the sheet itself, brighter at the top-left
 *      where a light source would strike it;
 *   3. an inset top highlight — a single hairline of white along the upper
 *      edge, which is what actually reads as "glass" rather than "translucent
 *      rectangle";
 *   4. a wide, soft drop shadow beneath, so the sheet floats off the ground
 *      instead of being painted onto it.
 *
 * Take away layer 3 and the whole effect collapses into flat tint, which is why
 * it is in the shared recipe and not left to each panel to remember.
 */

/** Layers 1–4: the base glass sheet every panel is cut from. */
export const GLASS: CSSProperties = {
  background:
    "linear-gradient(155deg, rgba(255,255,255,0.075) 0%, rgba(255,255,255,0.028) 38%, rgba(255,255,255,0.012) 100%)",
  backdropFilter: "blur(22px) saturate(165%)",
  WebkitBackdropFilter: "blur(22px) saturate(165%)",
  border: "1px solid rgba(255,255,255,0.1)",
  boxShadow:
    "inset 0 1px 0 rgba(255,255,255,0.16), inset 0 -1px 0 rgba(0,0,0,0.25), 0 24px 48px -28px rgba(0,0,0,0.8)",
};

/** The glass panel every card on the console is built from. */
export const PANEL: CSSProperties = {
  ...GLASS,
  borderRadius: 18,
  overflow: "hidden",
};

/**
 * A tinted variant, for the two panels that carry a meaning rather than just
 * content — the human queue (amber) and the gate's refusals (red). The hue is
 * mixed into the sheet itself so the panel reads as coloured glass, not as a
 * white panel with a coloured border.
 */
export function tintedPanel(hue: "amber" | "danger"): CSSProperties {
  // `L C H` only — the alpha is appended per stop, so the tint stays one value.
  const lch = hue === "amber" ? "0.8 0.14 75" : "0.72 0.17 32";
  const at = (alpha: number) => `oklch(${lch} / ${alpha})`;
  return {
    ...PANEL,
    border: `1px solid ${at(hue === "amber" ? 0.28 : 0.42)}`,
    background: `linear-gradient(155deg, ${at(0.14)} 0%, ${at(0.05)} 45%, rgba(255,255,255,0.012) 100%)`,
    boxShadow: `inset 0 1px 0 rgba(255,255,255,0.14), 0 24px 48px -30px ${at(hue === "amber" ? 0.18 : 0.3)}`,
  };
}

/** A panel's top strip, holding its title and the endpoint it reads from. */
export const PANEL_HEAD: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 16,
  padding: "16px 20px",
  borderBottom: "1px solid rgba(255,255,255,0.07)",
  background: "linear-gradient(180deg, rgba(255,255,255,0.05), transparent)",
};

export const PANEL_TITLE: CSSProperties = {
  margin: 0,
  fontSize: 15,
  fontWeight: 600,
};

/** The endpoint annotation beside a panel title — this panel's provenance. */
export const ENDPOINT: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  color: "rgba(233,233,240,0.38)",
};

/** An uppercase micro-label above a figure or a column. */
export const MICRO_LABEL: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 10.5,
  letterSpacing: "0.14em",
  textTransform: "uppercase",
  color: "rgba(233,233,240,0.42)",
};

/** The monospace body used by every technical row. */
export const MONO_ROW: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 12.5,
};

/** A pill button, used by the filters, the stream toggle and the header actions. */
export const PILL_BUTTON: CSSProperties = {
  padding: "6px 12px",
  borderRadius: 999,
  border: "1px solid rgba(255,255,255,0.14)",
  background: "linear-gradient(160deg, rgba(255,255,255,0.09), rgba(255,255,255,0.03))",
  backdropFilter: "blur(14px) saturate(150%)",
  WebkitBackdropFilter: "blur(14px) saturate(150%)",
  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.14)",
  color: "rgba(233,233,240,0.7)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  cursor: "pointer",
};

/** The accented variant, for an action that changes server state. */
export const PILL_BUTTON_ACCENT: CSSProperties = {
  ...PILL_BUTTON,
  padding: "8px 14px",
  border: "1px solid oklch(0.78 0.13 197 / 0.45)",
  background:
    "linear-gradient(160deg, oklch(0.78 0.13 197 / 0.26), oklch(0.78 0.13 197 / 0.08))",
  boxShadow:
    "inset 0 1px 0 rgba(255,255,255,0.18), 0 8px 20px -12px oklch(0.78 0.13 197 / 0.6)",
  color: "oklch(0.92 0.1 197)",
  fontSize: 11.5,
};

/** The column template shared by the work-items header and its rows. */
export const WORK_ITEM_COLUMNS = "1.35fr 0.85fr 1.2fr 1fr 1.2fr";

/** An empty panel's message. */
export const EMPTY_NOTE: CSSProperties = {
  padding: "18px 20px",
  fontFamily: "var(--font-mono)",
  fontSize: 11.5,
  color: "rgba(233,233,240,0.35)",
};
