"""The WebSocket stream ``/ws`` (contract §4, PRD §8.8, §13.3).

The dashboard subscribes here and never writes: every mutation goes over REST. The
server sends the contract envelope ``{type, seq, ts, payload}`` and nothing else.

The reconnect guarantee is the point of this file. On connect the client sends
``{type:"hello", last_seq}``; the server replays every buffered frame after
``last_seq`` and then streams live, so a socket dropped mid-demo loses nothing. Two
subtleties make that airtight:

- **Subscribe before snapshotting.** The live subscription is opened *before* the
  backfill is read from the buffer, and live frames whose ``seq`` was already in the
  backfill are skipped. Otherwise an event published in the gap between "read
  backfill" and "start streaming" would be lost.
- **A slow client is dropped, not tolerated forever.** If this connection falls far
  enough behind that its bus queue overflows, the socket is closed; the client
  reconnects with its ``last_seq`` and backfills. That is what stops one stalled tab
  from growing an unbounded queue or stalling the publisher.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from recoup.clock import IST
from recoup.events import Event, EventBus, SubscriberOverflow, Subscription

router = APIRouter()

_HELLO_TIMEOUT_SECONDS = 5.0
_HEARTBEAT_SECONDS = 15.0


def _frame(event: Event) -> dict[str, object]:
    """The contract envelope for one bus event, with the timestamp in IST."""
    return {
        "type": event.type,
        "seq": event.seq,
        "ts": event.ts.astimezone(IST).isoformat(),
        "payload": event.payload,
    }


async def _read_last_seq(websocket: WebSocket) -> int:
    """Read the opening ``hello`` frame's ``last_seq``; default to 0 if absent/invalid."""
    try:
        message = await asyncio.wait_for(websocket.receive_json(), timeout=_HELLO_TIMEOUT_SECONDS)
    except (TimeoutError, WebSocketDisconnect, ValueError):
        return 0
    if isinstance(message, dict) and message.get("type") == "hello":
        try:
            return max(0, int(message.get("last_seq", 0)))
        except (TypeError, ValueError):
            return 0
    return 0


@router.websocket("/ws")
async def stream(websocket: WebSocket) -> None:
    """Accept a subscriber, backfill from its ``last_seq``, then stream live frames."""
    ctx = websocket.app.state.ctx
    bus: EventBus = ctx.bus
    await websocket.accept()

    last_seq = await _read_last_seq(websocket)

    # Subscribe first, so nothing published between the backfill read and the live
    # stream can slip through the gap; overlap is de-duplicated by seq below.
    with bus.subscribe() as subscription:
        gap = bus.has_gap(last_seq)
        backfill = [] if gap else bus.since(last_seq)
        current_seq = bus.current_seq

        await websocket.send_json(
            {
                "type": "hello.ack",
                "seq": current_seq,
                "ts": ctx.clock.now().astimezone(IST).isoformat(),
                "payload": {
                    "backfill_count": -1 if gap else len(backfill),
                    "current_seq": current_seq,
                    "mode": ctx.settings.recoup_mode,
                },
            }
        )

        for event in backfill:
            await websocket.send_json(_frame(event))
        last_sent = backfill[-1].seq if backfill else last_seq

        with contextlib.suppress(WebSocketDisconnect):
            await _run_until_closed(websocket, subscription, bus, last_sent)


async def _run_until_closed(
    websocket: WebSocket, subscription: Subscription, bus: EventBus, last_sent: int
) -> None:
    """Stream live frames while watching for disconnect, with a periodic heartbeat.

    A single loop races two futures — the next client message (which, for a
    read-only subscriber, only ever resolves as a disconnect) and the next bus event
    — so a vanished client is noticed promptly and its subscription torn down without
    leaking a task. When neither resolves within the heartbeat interval, a heartbeat
    frame is sent so a silent connection is still detectable.
    """
    ctx = websocket.app.state.ctx
    events = subscription.events()
    recv_task: asyncio.Task[object] = asyncio.ensure_future(websocket.receive())
    event_task: asyncio.Task[Event] = asyncio.ensure_future(anext(events))
    try:
        while True:
            done, _pending = await asyncio.wait(
                {recv_task, event_task},
                timeout=_HEARTBEAT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if not done:
                await websocket.send_json(
                    {
                        "type": "heartbeat",
                        "seq": bus.current_seq,
                        "ts": ctx.clock.now().astimezone(IST).isoformat(),
                        "payload": {},
                    }
                )
                continue

            if recv_task in done:
                if recv_task.exception() is not None:
                    break  # WebSocketDisconnect: the client is gone
                message = recv_task.result()
                if isinstance(message, dict) and message.get("type") == "websocket.disconnect":
                    break
                recv_task = asyncio.ensure_future(websocket.receive())

            if event_task in done:
                try:
                    event = event_task.result()
                except StopAsyncIteration:
                    break
                except SubscriberOverflow:
                    await websocket.close(code=1011)  # client reconnects and backfills
                    break
                if event.seq > last_sent:
                    await websocket.send_json(_frame(event))
                event_task = asyncio.ensure_future(anext(events))
    finally:
        recv_task.cancel()
        event_task.cancel()
        await asyncio.gather(recv_task, event_task, return_exceptions=True)
