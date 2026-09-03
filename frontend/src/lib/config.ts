/**
 * Where the backend lives.
 *
 * Read from `NEXT_PUBLIC_API_BASE_URL` so a deployed dashboard can point at a
 * different host without a rebuild, and defaulted to the local FastAPI port so
 * that a fresh clone works with no environment file at all — the same rule the
 * backend follows for its own settings.
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/+$/, "") ?? "http://localhost:8000";

/** The WebSocket endpoint, derived from the API base so the two cannot disagree. */
export const WS_URL = `${API_BASE_URL.replace(/^http/, "ws")}/ws`;
