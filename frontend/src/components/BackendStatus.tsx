"use client";

import { useEffect, useState } from "react";

import { API_BASE_URL } from "@/lib/config";
import type { HealthResponse } from "@/lib/types";

type Connection =
  | { status: "checking" }
  | { status: "connected"; health: HealthResponse }
  | { status: "disconnected"; reason: string };

const POLL_INTERVAL_MS = 5000;
const REQUEST_TIMEOUT_MS = 3000;

/**
 * The link light for the FastAPI backend.
 *
 * It polls `GET /api/health` rather than displaying a fixed label. The backend
 * does not exist until phase 9, so today this reports "backend disconnected" —
 * but it reports it because it looked, which is the same reason it will report a
 * genuine outage during the demo. A hardcoded label would have to be replaced
 * later and would say nothing true in the meantime.
 *
 * It also surfaces `mode`, so a mocked backend is never mistaken for a live one
 * (PRD section 13.4).
 */
export default function BackendStatus() {
  const [connection, setConnection] = useState<Connection>({ status: "checking" });

  useEffect(() => {
    let cancelled = false;

    async function probe() {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
      try {
        const response = await fetch(`${API_BASE_URL}/api/health`, {
          signal: controller.signal,
          cache: "no-store",
        });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const health = (await response.json()) as HealthResponse;
        if (!cancelled) {
          setConnection({ status: "connected", health });
        }
      } catch (error) {
        if (!cancelled) {
          const reason =
            error instanceof DOMException && error.name === "AbortError"
              ? "no response"
              : error instanceof Error
                ? error.message
                : "unreachable";
          setConnection({ status: "disconnected", reason });
        }
      } finally {
        clearTimeout(timeout);
      }
    }

    void probe();
    const interval = setInterval(() => void probe(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const { dotClass, label, detail } = describe(connection);

  return (
    <div
      className="flex items-center gap-2.5 rounded-full border border-console-border bg-console-panel-raised px-3.5 py-1.5"
      role="status"
      aria-live="polite"
    >
      <span className={`h-2 w-2 shrink-0 rounded-full ${dotClass}`} aria-hidden="true" />
      <span className="font-mono text-xs tracking-wide text-console-text">{label}</span>
      <span className="font-mono text-xs text-console-muted">{detail}</span>
    </div>
  );
}

function describe(connection: Connection): {
  dotClass: string;
  label: string;
  detail: string;
} {
  switch (connection.status) {
    case "checking":
      return {
        dotClass: "bg-console-warn status-pulse",
        label: "connecting",
        detail: API_BASE_URL,
      };
    case "connected":
      return {
        dotClass: "bg-console-accent",
        label: "backend connected",
        detail: `${connection.health.mode} · v${connection.health.version}`,
      };
    case "disconnected":
      return {
        dotClass: "bg-console-danger status-pulse",
        label: "backend disconnected",
        detail: connection.reason,
      };
  }
}
