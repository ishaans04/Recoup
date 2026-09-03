/**
 * Pure display-formatting helpers. Nothing here reaches the network, nothing
 * here is money-authoritative — every value comes from the backend, formatted
 * for a human at the very last step. See `docs/interface-contract.md` section 5
 * rule 2: the frontend never computes money, it only divides by 100 to render.
 */

import { humanise, type State } from "./types";

/**
 * Format integer paise as Indian lakh-grouped rupees: `Rs 75,000`,
 * `Rs 1,20,500`, `Rs 1,00,00,000` — grouping by 2 after the first 3 digits,
 * not by 3s. `Intl.NumberFormat("en-IN")` already implements this grouping
 * natively, so this function only needs to strip the currency symbol Intl
 * would otherwise use (`₹`) in favour of the ASCII `Rs ` the brief and the
 * demo script (PRD 12.4, 16.5) use in every worked example, and to decide how
 * whole vs fractional rupees are shown.
 *
 * Paise that divide evenly into rupees render with no decimal places
 * (`100` paise -> `Rs 1`, not `Rs 1.00`) — audit amounts in this system are
 * always whole rupees in practice, and a trailing `.00` on every figure in a
 * dense table is noise. A genuine fractional rupee (an odd paise remainder)
 * still renders with up to 2 decimal places so no precision is silently lost.
 */
export function formatPaise(paise: number): string {
  if (!Number.isFinite(paise)) {
    return "Rs 0";
  }

  const negative = paise < 0;
  const rupees = Math.abs(paise) / 100;
  const grouped = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(rupees);

  return `${negative ? "-" : ""}Rs ${grouped}`;
}

/**
 * Format a diagnosis confidence (0..1) as a whole-number percentage. Rounded
 * rather than truncated so 0.965 reads as the more honest "97%" instead of
 * "96%".
 */
export function formatConfidence(confidence: number): string {
  if (!Number.isFinite(confidence)) {
    return "0%";
  }
  const clamped = Math.min(1, Math.max(0, confidence));
  return `${Math.round(clamped * 100)}%`;
}

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * Format an ISO-8601 timestamp as a short relative time ("just now", "2m
 * ago", "3h ago", "5d ago"). Falls back to the raw string for a timestamp
 * that fails to parse, so a malformed value never renders as `NaN ago` —
 * consistent with the contract's rule that an unrecognised value is shown
 * verbatim, not hidden.
 */
export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) {
    return iso;
  }

  const diffMs = now.getTime() - then.getTime();
  const abs = Math.abs(diffMs);
  const suffix = diffMs < 0 ? "from now" : "ago";

  if (abs < 10 * SECOND) {
    return "just now";
  }
  if (abs < MINUTE) {
    return `${Math.floor(abs / SECOND)}s ${suffix}`;
  }
  if (abs < HOUR) {
    return `${Math.floor(abs / MINUTE)}m ${suffix}`;
  }
  if (abs < DAY) {
    return `${Math.floor(abs / HOUR)}h ${suffix}`;
  }
  return `${Math.floor(abs / DAY)}d ${suffix}`;
}

/** Human label for a contract `state` value: `ACTION_CHOSEN` -> `Action Chosen`. */
export function formatState(state: State): string {
  return humanise(state);
}
