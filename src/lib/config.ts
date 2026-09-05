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

/**
 * Optional pre-fill for the console's live-nudge control, so a demo machine can
 * be set up once from `.env.local` rather than typed into the UI each time.
 *
 * These are read only as *defaults* — whatever the operator saves in the console
 * wins, and is kept in that browser's local storage. Nothing personal is ever
 * committed to the repository, which is why there is no fallback value here.
 */
export const DEMO_CONTACT_PHONE = process.env.NEXT_PUBLIC_DEMO_PHONE ?? "";
export const DEMO_CONTACT_EMAIL = process.env.NEXT_PUBLIC_DEMO_EMAIL ?? "";
