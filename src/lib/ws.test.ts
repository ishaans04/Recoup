import { afterEach, describe, expect, it, vi } from "vitest";

import {
  RecoupStreamClient,
  initialStreamState,
  reduceStreamState,
  type WebSocketLike,
} from "@/lib/ws";
import type { AuditEvent, WorkItem, WsEnvelope } from "@/lib/types";

function envelope(type: string, seq: number, payload: unknown): WsEnvelope {
  return { type, seq, ts: "2026-09-04T10:00:00+05:30", payload } as WsEnvelope;
}

function auditRow(id: number, txn: string): AuditEvent {
  return {
    id,
    timestamp: "2026-09-04T10:00:00+05:30",
    txn_id: txn,
    from_state: "DETECTED",
    to_state: "DIAGNOSED",
    diagnosis_cause: null,
    diagnosis_confidence: null,
    action_chosen: null,
    constraint_result: null,
    constraint_reason: null,
    outcome: null,
    rationale: `row ${id}`,
  };
}

describe("reduceStreamState — contract §5 ordering rules", () => {
  it("prepends audit rows newest-first and advances the resume cursor", () => {
    let state = initialStreamState();
    state = reduceStreamState(state, envelope("audit.appended", 1, auditRow(1, "pay_a")));
    state = reduceStreamState(state, envelope("audit.appended", 2, auditRow(2, "pay_b")));
    expect(state.auditEvents.map((e) => e.id)).toEqual([2, 1]);
    expect(state.lastSeq).toBe(2);
  });

  it("drops a frame whose seq was already applied (backfill/live overlap)", () => {
    let state = initialStreamState();
    state = reduceStreamState(state, envelope("audit.appended", 5, auditRow(5, "pay_a")));
    const before = state;
    // A replayed frame at or below lastSeq must be a no-op, not a duplicate row.
    state = reduceStreamState(state, envelope("audit.appended", 5, auditRow(5, "pay_a")));
    state = reduceStreamState(state, envelope("audit.appended", 3, auditRow(3, "pay_x")));
    expect(state).toBe(before);
    expect(state.auditEvents).toHaveLength(1);
  });

  it("advances seq for an unknown, additive message type without desyncing", () => {
    let state = initialStreamState();
    state = reduceStreamState(state, envelope("some.future.type", 9, { anything: true }));
    expect(state.lastSeq).toBe(9);
    expect(state.auditEvents).toHaveLength(0);
  });

  it("upserts a work item by txn_id and accumulates gate rejections", () => {
    let state = initialStreamState();
    const item = { txn_id: "pay_a", state: "ESCALATED" } as unknown as WorkItem;
    state = reduceStreamState(state, envelope("workitem.updated", 1, item));
    state = reduceStreamState(
      state,
      envelope("gate.rejected", 2, { txn_id: "pay_a", constraint: "amount_cap", reason: "over" }),
    );
    expect(state.workItems["pay_a"].state).toBe("ESCALATED");
    expect(state.gateRejections[0]).toMatchObject({ constraint: "amount_cap", seq: 2 });
  });
});

// A controllable fake socket so the reconnect path is testable with no real server.
class FakeSocket implements WebSocketLike {
  readyState = 0;
  onopen: ((ev: unknown) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  sent: string[] = [];

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = 3;
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.({});
  }
}

describe("RecoupStreamClient — reconnect carries the last applied seq", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("reconnects and sends hello with the seq it reached before the drop", () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const client = new RecoupStreamClient("ws://test/ws", {
      webSocketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      initialLastSeq: 5,
      initialBackoffMs: 500,
    });

    client.connect();
    sockets[0].open();
    // First handshake carries the seeded cursor.
    expect(JSON.parse(sockets[0].sent[0])).toEqual({ type: "hello", last_seq: 5 });

    // A live frame advances the cursor, then the socket drops.
    sockets[0].onmessage?.({ data: JSON.stringify(envelope("audit.appended", 6, auditRow(6, "p"))) });
    sockets[0].onclose?.({});

    // After the backoff, a new socket opens and resumes from seq 6 — nothing missed.
    vi.advanceTimersByTime(500);
    expect(sockets).toHaveLength(2);
    sockets[1].open();
    expect(JSON.parse(sockets[1].sent[0])).toEqual({ type: "hello", last_seq: 6 });

    client.close();
  });
});
