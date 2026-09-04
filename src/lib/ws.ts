"use client";

/**
 * WebSocket client for `docs/interface-contract.md` section 4.
 *
 * Split into three layers so each is testable on its own:
 *
 * 1. `reduceStreamState` — a pure reducer. Given the state built so far and one
 *    envelope, returns the next state. No I/O, no timers, no React. This is
 *    what `ws.test.ts` drives directly to prove ordering and dedup.
 * 2. `RecoupStreamClient` — owns one browser `WebSocket`, the `hello` handshake,
 *    and reconnect-with-backoff carrying the last applied `seq`. It never
 *    touches React. It accepts an injectable WebSocket constructor so tests can
 *    supply a fake transport and control time.
 * 3. `useRecoupStream` — the hook components actually use. On mount it hydrates
 *    a starting snapshot from REST (GET /api/metrics, /api/escalations,
 *    /api/audit, /api/workitems — each has a direct snapshot endpoint, so
 *    there is no need to lean on the WS buffer's retention window for
 *    correctness), then opens a `RecoupStreamClient` seeded with that
 *    snapshot's cursor so the live socket only backfills what the snapshot
 *    didn't already cover. If the snapshot fetch fails outright (the backend
 *    isn't reachable), it starts from empty state and keeps trying — the
 *    page falls back to fixtures until `lastSeq` moves off zero.
 */

import { useEffect, useState } from "react";

import { getAudit, getEscalations, getMetrics, listWorkItems } from "./api";
import { WS_URL } from "./config";
import type {
  AuditEvent,
  BatchRun,
  Escalation,
  Metrics,
  WorkItem,
  WsBatchProgressPayload,
  WsEnvelope,
  WsGateRejectedPayload,
  WsMessageType,
} from "./types";

/** How many rows the live feeds keep in memory. Older rows are still on the
 * server and reachable via `GET /api/audit?since_id=`; the dashboard only
 * needs enough history to read as a table, not the whole run. */
const MAX_AUDIT_EVENTS = 500;
const MAX_GATE_REJECTIONS = 100;
const MAX_ESCALATIONS = 200;

export interface StreamState {
  /** Newest first, capped at MAX_AUDIT_EVENTS. */
  auditEvents: AuditEvent[];
  workItems: Record<string, WorkItem>;
  metrics: Metrics | null;
  /** Newest first, capped at MAX_ESCALATIONS. */
  escalations: Escalation[];
  /** Newest first, capped at MAX_GATE_REJECTIONS. */
  gateRejections: (WsGateRejectedPayload & { seq: number; ts: string })[];
  batchProgress: WsBatchProgressPayload | null;
  batch: BatchRun | null;
  /** The highest `seq` applied so far. 0 before any frame lands. */
  lastSeq: number;
}

export function initialStreamState(): StreamState {
  return {
    auditEvents: [],
    workItems: {},
    metrics: null,
    escalations: [],
    gateRejections: [],
    batchProgress: null,
    batch: null,
    lastSeq: 0,
  };
}

/**
 * Applies one envelope to the running state. Pure: same inputs, same output,
 * every time.
 *
 * Ordering rule (contract section 5.6): apply in `seq` order, drop any frame
 * whose `seq` has already been applied. Since a single WebSocket connection
 * delivers frames in order, the only way an "out of order" frame can reach
 * this function is a duplicate replay after a reconnect's backfill overlaps
 * live delivery — dropping non-increasing `seq` handles that case exactly.
 *
 * Unknown `type` values still advance `seq` (rule 5.5) so a future,
 * additive message type never desyncs the resume cursor.
 */
export function reduceStreamState(state: StreamState, envelope: WsEnvelope): StreamState {
  if (envelope.seq <= state.lastSeq) {
    return state;
  }

  const next: StreamState = { ...state, lastSeq: envelope.seq };

  switch (envelope.type as WsMessageType) {
    case "audit.appended": {
      const event = envelope.payload as AuditEvent;
      next.auditEvents = [event, ...state.auditEvents].slice(0, MAX_AUDIT_EVENTS);
      return next;
    }
    case "workitem.updated": {
      const item = envelope.payload as WorkItem;
      next.workItems = { ...state.workItems, [item.txn_id]: item };
      return next;
    }
    case "metrics.updated": {
      next.metrics = envelope.payload as Metrics;
      return next;
    }
    case "gate.rejected": {
      const payload = envelope.payload as WsGateRejectedPayload;
      next.gateRejections = [
        { ...payload, seq: envelope.seq, ts: envelope.ts },
        ...state.gateRejections,
      ].slice(0, MAX_GATE_REJECTIONS);
      return next;
    }
    case "escalation.created": {
      const escalation = envelope.payload as Escalation;
      next.escalations = [escalation, ...state.escalations].slice(0, MAX_ESCALATIONS);
      return next;
    }
    case "batch.progress": {
      next.batchProgress = envelope.payload as WsBatchProgressPayload;
      return next;
    }
    case "batch.completed": {
      next.batch = envelope.payload as BatchRun;
      next.batchProgress = null;
      return next;
    }
    case "hello.ack":
      // Handshake bookkeeping only; RecoupStreamClient consumes this directly.
      return next;
    default:
      // Unknown type: seq already advanced above, payload deliberately ignored.
      return next;
  }
}

export type StreamStatus = "connecting" | "open" | "reconnecting" | "closed";

/** The minimal surface of `WebSocket` this client depends on, so tests can
 * inject a fake transport without a real socket or a real server. */
export interface WebSocketLike {
  readyState: number;
  onopen: ((ev: unknown) => void) | null;
  onclose: ((ev: unknown) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  send(data: string): void;
  close(): void;
}

export type WebSocketFactory = (url: string) => WebSocketLike;

const defaultFactory: WebSocketFactory = (url) => new WebSocket(url) as unknown as WebSocketLike;

export interface RecoupStreamClientOptions {
  webSocketFactory?: WebSocketFactory;
  onEnvelope?: (envelope: WsEnvelope) => void;
  onStatusChange?: (status: StreamStatus) => void;
  initialBackoffMs?: number;
  maxBackoffMs?: number;
  /** Starting resume cursor, e.g. hydrated from a prior REST fetch. */
  initialLastSeq?: number;
}

/**
 * Owns one logical connection to `/ws`, including reconnects. A socket
 * dropped mid-demo recovers silently: `onclose`/`onerror` schedule a
 * reconnect with exponential backoff, and the next `hello` carries the
 * highest `seq` this client has actually applied, so the server's backfill
 * picks up exactly where the dropped connection left off.
 */
export class RecoupStreamClient {
  private readonly url: string;
  private readonly factory: WebSocketFactory;
  private readonly onEnvelope: (envelope: WsEnvelope) => void;
  private readonly onStatusChange: (status: StreamStatus) => void;
  private readonly initialBackoffMs: number;
  private readonly maxBackoffMs: number;

  private socket: WebSocketLike | null = null;
  private lastSeq: number;
  private backoffMs: number;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByCaller = false;

  constructor(url: string, options: RecoupStreamClientOptions = {}) {
    this.url = url;
    this.factory = options.webSocketFactory ?? defaultFactory;
    this.onEnvelope = options.onEnvelope ?? (() => {});
    this.onStatusChange = options.onStatusChange ?? (() => {});
    this.initialBackoffMs = options.initialBackoffMs ?? 500;
    this.maxBackoffMs = options.maxBackoffMs ?? 15000;
    this.backoffMs = this.initialBackoffMs;
    this.lastSeq = options.initialLastSeq ?? 0;
  }

  /** The highest seq this client has applied. Exposed so a caller can persist
   * it across full page reloads if it ever wants to (not required by the
   * contract — a fresh page load sends `last_seq: 0`). */
  getLastSeq(): number {
    return this.lastSeq;
  }

  connect(): void {
    this.closedByCaller = false;
    this.openSocket();
  }

  close(): void {
    this.closedByCaller = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
    this.socket = null;
  }

  private openSocket(): void {
    this.onStatusChange(this.backoffMs === this.initialBackoffMs ? "connecting" : "reconnecting");
    const socket = this.factory(this.url);
    this.socket = socket;

    socket.onopen = () => {
      this.backoffMs = this.initialBackoffMs;
      socket.send(JSON.stringify({ type: "hello", last_seq: this.lastSeq }));
      this.onStatusChange("open");
    };

    socket.onmessage = (event: { data: string }) => {
      let envelope: WsEnvelope;
      try {
        envelope = JSON.parse(event.data) as WsEnvelope;
      } catch {
        return;
      }
      if (typeof envelope.seq === "number" && envelope.seq > this.lastSeq) {
        this.lastSeq = envelope.seq;
      }
      this.onEnvelope(envelope);
    };

    const handleDrop = () => {
      if (this.socket !== socket) return; // a newer socket has already replaced this one
      this.socket = null;
      if (this.closedByCaller) return;
      this.onStatusChange("reconnecting");
      this.scheduleReconnect();
    };

    socket.onclose = handleDrop;
    socket.onerror = handleDrop;
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket();
    }, this.backoffMs);
    this.backoffMs = Math.min(this.backoffMs * 2, this.maxBackoffMs);
  }
}

export interface UseRecoupStreamResult extends StreamState {
  status: StreamStatus;
}

/**
 * React hook wiring a `RecoupStreamClient` to component state. One client per
 * mount; the effect tears it down on unmount so navigating away from the
 * console never leaks a live socket.
 *
 * `lastSeq` stays `0` until either the REST snapshot or the WS handshake
 * actually succeeds, so `lastSeq > 0` is the page's honest signal that it is
 * looking at a real backend rather than needing a separate "am I live" flag.
 */
export function useRecoupStream(url: string = WS_URL): UseRecoupStreamResult {
  const [state, setState] = useState<StreamState>(initialStreamState);
  const [status, setStatus] = useState<StreamStatus>("connecting");

  useEffect(() => {
    let cancelled = false;
    let client: RecoupStreamClient | null = null;

    async function hydrateThenConnect() {
      let seed = initialStreamState();
      try {
        const [metrics, escalationsResponse, auditResponse, workItemsResponse] = await Promise.all([
          getMetrics(),
          getEscalations(),
          getAudit({ limit: 500 }),
          listWorkItems({ limit: 200 }),
        ]);
        const workItems: Record<string, WorkItem> = {};
        for (const item of workItemsResponse.items) workItems[item.txn_id] = item;
        seed = {
          ...seed,
          metrics,
          escalations: escalationsResponse.escalations,
          // GET /api/audit is oldest-first; every in-memory state here is
          // newest-first, matching how a live audit.appended stream arrives.
          auditEvents: [...auditResponse.events].reverse(),
          workItems,
          lastSeq: auditResponse.last_id,
        };
      } catch {
        // Backend unreachable (or one snapshot call failed): start empty.
        // The page falls back to fixtures until lastSeq genuinely moves.
      }
      if (cancelled) return;
      setState(seed);
      client = new RecoupStreamClient(url, {
        initialLastSeq: seed.lastSeq,
        onEnvelope: (envelope) => setState((prev) => reduceStreamState(prev, envelope)),
        onStatusChange: setStatus,
      });
      client.connect();
    }

    void hydrateThenConnect();
    return () => {
      cancelled = true;
      client?.close();
    };
  }, [url]);

  return { ...state, status };
}
