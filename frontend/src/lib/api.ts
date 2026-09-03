/**
 * Typed REST client for `docs/interface-contract.md` section 3.
 *
 * Every function here returns the contract's response shape or throws an
 * `ApiClientError` — never a raw `TypeError` from a rejected `fetch`, a
 * `DOMException` from an aborted request, or an unparsed HTTP body. Components
 * never see a fetch failure that doesn't already know what kind of failure it
 * is; they see a shape they can render a message from.
 */

import { API_BASE_URL } from "./config";
import type {
  AuditFeedResponse,
  BatchRun,
  BatchRunAccepted,
  BatchRunRequest,
  Cause,
  DemoInjectRequest,
  DemoInjectResponse,
  EscalationsResponse,
  HealthResponse,
  Metrics,
  State,
  WorkItem,
  WorkItemAuditResponse,
  WorkItemsResponse,
} from "./types";

const DEFAULT_TIMEOUT_MS = 8000;

export type ApiErrorKind =
  | "http_error"
  | "network_error"
  | "timeout"
  | "invalid_response";

/**
 * Every failure mode the client can hit, normalised to one shape. `code`
 * carries the contract's `error.code` (section 2.3) when the server sent one;
 * `kind` distinguishes that from a failure that never reached the server at
 * all, which components need to tell apart (a 404 means "ask something
 * else"; a network error means "the backend is not there yet").
 */
export class ApiClientError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly code: string | null;
  readonly detail: string | null;

  constructor(
    message: string,
    opts: { kind: ApiErrorKind; status?: number | null; code?: string | null; detail?: string | null },
  ) {
    super(message);
    this.name = "ApiClientError";
    this.kind = opts.kind;
    this.status = opts.status ?? null;
    this.code = opts.code ?? null;
    this.detail = opts.detail ?? null;
  }
}

export function isApiClientError(value: unknown): value is ApiClientError {
  return value instanceof ApiClientError;
}

interface RequestOptions {
  method?: "GET" | "POST";
  query?: Record<string, string | number | boolean | readonly (string | number)[] | undefined>;
  body?: unknown;
  timeoutMs?: number;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(path, API_BASE_URL.endsWith("/") ? API_BASE_URL : `${API_BASE_URL}/`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined) continue;
      if (Array.isArray(value)) {
        for (const item of value) url.searchParams.append(key, String(item));
      } else {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", query, body, timeoutMs = DEFAULT_TIMEOUT_MS, signal } = options;
  const url = buildUrl(path.startsWith("/") ? path.slice(1) : path, query);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  // Let an external abort (e.g. a component unmounting) cancel the request too.
  const externalAbort = () => controller.abort();
  signal?.addEventListener("abort", externalAbort);

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      cache: "no-store",
    });
  } catch (error) {
    const aborted = error instanceof DOMException && error.name === "AbortError";
    throw new ApiClientError(
      aborted ? `Request to ${path} timed out after ${timeoutMs}ms` : `Could not reach ${path}`,
      {
        kind: aborted ? "timeout" : "network_error",
        detail: error instanceof Error ? error.message : String(error),
      },
    );
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", externalAbort);
  }

  let json: unknown = null;
  const text = await response.text();
  if (text.length > 0) {
    try {
      json = JSON.parse(text);
    } catch {
      if (!response.ok) {
        throw new ApiClientError(`${path} returned HTTP ${response.status} with a non-JSON body`, {
          kind: "http_error",
          status: response.status,
        });
      }
      throw new ApiClientError(`${path} returned a response that could not be parsed as JSON`, {
        kind: "invalid_response",
        status: response.status,
      });
    }
  }

  if (!response.ok) {
    const errorBody = json as { error?: { code?: string; message?: string; detail?: string | null } } | null;
    throw new ApiClientError(errorBody?.error?.message ?? `${path} returned HTTP ${response.status}`, {
      kind: "http_error",
      status: response.status,
      code: errorBody?.error?.code ?? null,
      detail: errorBody?.error?.detail ?? null,
    });
  }

  return json as T;
}

/** `GET /api/health`. */
export function getHealth(opts: { timeoutMs?: number; signal?: AbortSignal } = {}): Promise<HealthResponse> {
  return request<HealthResponse>("/api/health", { timeoutMs: opts.timeoutMs ?? 3000, signal: opts.signal });
}

/** `GET /api/workitems`. */
export function listWorkItems(
  params: { state?: State[]; cause?: Cause[]; limit?: number; cursor?: string } = {},
): Promise<WorkItemsResponse> {
  return request<WorkItemsResponse>("/api/workitems", {
    query: { state: params.state, cause: params.cause, limit: params.limit, cursor: params.cursor },
  });
}

/** `GET /api/workitems/{txn_id}`. */
export function getWorkItem(txnId: string): Promise<WorkItem> {
  return request<WorkItem>(`/api/workitems/${encodeURIComponent(txnId)}`);
}

/** `GET /api/workitems/{txn_id}/audit`. */
export function getWorkItemAudit(txnId: string): Promise<WorkItemAuditResponse> {
  return request<WorkItemAuditResponse>(`/api/workitems/${encodeURIComponent(txnId)}/audit`);
}

/** `GET /api/audit`. */
export function getAudit(params: { sinceId?: number; limit?: number } = {}): Promise<AuditFeedResponse> {
  return request<AuditFeedResponse>("/api/audit", {
    query: { since_id: params.sinceId ?? 0, limit: params.limit },
  });
}

/** `GET /api/metrics`. */
export function getMetrics(): Promise<Metrics> {
  return request<Metrics>("/api/metrics");
}

/** `GET /api/escalations`. */
export function getEscalations(): Promise<EscalationsResponse> {
  return request<EscalationsResponse>("/api/escalations");
}

/** `POST /api/batch/run`. */
export function runBatch(body: BatchRunRequest = {}): Promise<BatchRunAccepted> {
  return request<BatchRunAccepted>("/api/batch/run", { method: "POST", body });
}

/** `GET /api/batch/{run_id}`. */
export function getBatchRun(runId: string): Promise<BatchRun> {
  return request<BatchRun>(`/api/batch/${encodeURIComponent(runId)}`);
}

/** `POST /api/demo/inject`. */
export function injectDemoCase(body: DemoInjectRequest): Promise<DemoInjectResponse> {
  return request<DemoInjectResponse>("/api/demo/inject", { method: "POST", body });
}
