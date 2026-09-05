"use client";

import { useState } from "react";

import { GLASS } from "./chrome";

/**
 * The console's five sections, in the order an operator works through them:
 * what failed, who is waiting on a human, what the log is saying live, what the
 * gate refused, and how the batch performed by cause.
 *
 * Deliberately small. These are signposts, not cards — they name the section
 * below and carry its count, and nothing else. A tab that grows into a tile
 * competes with the panel it is introducing.
 */

export type ConsoleSection =
  | "work-items"
  | "human-queue"
  | "live-audit"
  | "gate"
  | "by-cause";

export interface TabSpec {
  id: ConsoleSection;
  label: string;
  /** Shown as a small badge; omitted when the count carries no meaning. */
  count?: number;
  /** Draws the badge in the refusal hue rather than the neutral one. */
  alert?: boolean;
}

export default function ConsoleTabs({
  tabs,
  active,
  onSelect,
}: {
  tabs: TabSpec[];
  active: ConsoleSection;
  onSelect: (section: ConsoleSection) => void;
}) {
  const [hovered, setHovered] = useState<ConsoleSection | null>(null);

  return (
    <div
      role="tablist"
      aria-label="Console sections"
      style={{ display: "flex", flexWrap: "wrap", gap: 10 }}
    >
      {tabs.map((tab) => {
        const isActive = tab.id === active;
        const isHovered = hovered === tab.id;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            aria-controls={`section-${tab.id}`}
            data-testid="console-tab"
            onClick={() => onSelect(tab.id)}
            onMouseEnter={() => setHovered(tab.id)}
            onMouseLeave={() => setHovered(null)}
            style={{
              ...GLASS,
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 14px",
              borderRadius: 12,
              cursor: "pointer",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              letterSpacing: "0.01em",
              whiteSpace: "nowrap",
              transition: "color 160ms ease, border-color 160ms ease, transform 160ms ease",
              transform: isActive || isHovered ? "translateY(-1px)" : "none",
              color: isActive ? "oklch(0.94 0.09 197)" : "rgba(233,233,240,0.6)",
              border: `1px solid ${
                isActive
                  ? "oklch(0.78 0.13 197 / 0.5)"
                  : isHovered
                    ? "rgba(255,255,255,0.18)"
                    : "rgba(255,255,255,0.1)"
              }`,
              background: isActive
                ? "linear-gradient(155deg, oklch(0.78 0.13 197 / 0.26) 0%, oklch(0.78 0.13 197 / 0.07) 55%, rgba(255,255,255,0.012) 100%)"
                : GLASS.background,
              boxShadow: isActive
                ? "inset 0 1px 0 rgba(255,255,255,0.2), 0 10px 26px -14px oklch(0.78 0.13 197 / 0.7)"
                : GLASS.boxShadow,
            }}
          >
            {/* A lit dot on the active tab, so the selection survives greyscale. */}
            <span
              aria-hidden="true"
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: isActive ? "oklch(0.85 0.13 197)" : "rgba(233,233,240,0.28)",
                boxShadow: isActive ? "0 0 10px oklch(0.85 0.13 197 / 0.9)" : "none",
              }}
            />
            {tab.label}
            {tab.count !== undefined && (
              <span
                style={{
                  padding: "1px 7px",
                  borderRadius: 999,
                  fontSize: 10.5,
                  border: `1px solid ${
                    tab.alert ? "oklch(0.8 0.14 75 / 0.4)" : "rgba(255,255,255,0.14)"
                  }`,
                  background: tab.alert
                    ? "oklch(0.8 0.14 75 / 0.14)"
                    : "rgba(255,255,255,0.06)",
                  color: tab.alert ? "oklch(0.88 0.12 75)" : "rgba(233,233,240,0.6)",
                }}
              >
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
