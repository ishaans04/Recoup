"""The in-process event bus and the sink the domain layer publishes through.

The dashboard's live recovery counter must survive a dropped connection mid-demo
(PRD §13.3 treats a venue network failure as a real risk), and one slow browser
tab must never stall the batch run feeding every other tab. Both properties come
from the same two mechanisms here:

**A monotonic sequence number and a replay buffer.** Every published :class:`Event`
gets a strictly increasing ``seq``, and the bus retains the last N events. A client
that reconnects sends the highest ``seq`` it applied; the WebSocket layer replays
everything after it from the buffer, so a socket dropped mid-run loses nothing.

**Per-subscriber bounded queues.** Each subscriber has its own queue. The publisher
never blocks on a subscriber: if a queue overflows (a stalled client), that one
subscriber is marked overflowed and forced to re-sync from its ``last_seq`` rather
than holding up the publisher or any other subscriber.

The bus itself carries no domain knowledge — it moves ``{type, seq, ts, payload}``
frames. The domain layer (the state machine, the gate pipeline) speaks to it only
through :class:`EventSink`, an interface with no import back into the API, so the
batch CLI can run with no sink at all and the API can supply one that builds the
contract's payload shapes.
"""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from recoup.clock import Clock
from recoup.domain.models import Action, AuditEvent, WorkItem

__all__ = [
    "Event",
    "EventBus",
    "EventSink",
    "Subscription",
    "SubscriberOverflow",
]


@dataclass(frozen=True)
class Event:
    """One frame on the bus: the contract's ``{type, seq, ts, payload}`` envelope."""

    type: str
    seq: int
    ts: datetime
    payload: dict[str, object]


class SubscriberOverflow(Exception):
    """Raised to a subscriber whose queue overflowed while it was too slow to drain.

    The subscriber must stop consuming live frames and re-sync from its last applied
    ``seq`` (the WebSocket layer does this by closing the socket so the client
    reconnects and backfills). It is never raised to the publisher.
    """


_OVERFLOW = object()
"""Sentinel enqueued to wake a consumer whose queue was dropped for overflow."""


class Subscription:
    """One consumer's view of the bus: a bounded queue plus an overflow flag.

    Created by :meth:`EventBus.subscribe`; never instantiated directly. The
    publisher offers events without ever blocking — a full queue trips
    :attr:`overflowed` and enqueues a single wake-up sentinel instead of waiting.
    """

    def __init__(self, maxsize: int) -> None:
        # Imported lazily so the module is importable without a running loop; the
        # queue itself is only ever touched from within the event loop.
        import asyncio

        self._queue: asyncio.Queue[object] = asyncio.Queue(maxsize=maxsize)
        self.overflowed = False

    def _offer(self, event: Event) -> None:
        """Publisher-side, non-blocking. Marks overflow rather than waiting."""
        import asyncio

        if self.overflowed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.overflowed = True
            # Free the backed-up memory; the sentinel wakes the consumer so it can
            # observe the overflow promptly rather than on its next natural read.
            while True:
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            self._queue.put_nowait(_OVERFLOW)

    async def events(self) -> AsyncIterator[Event]:
        """Yield live events until the subscription overflows.

        Raises :class:`SubscriberOverflow` if this subscriber fell too far behind,
        so the caller can force a re-sync instead of silently skipping frames.
        """
        while True:
            item = await self._queue.get()
            if item is _OVERFLOW:
                raise SubscriberOverflow(
                    "subscriber fell behind and its queue was dropped; re-sync from last_seq"
                )
            assert isinstance(item, Event)
            yield item


class EventBus:
    """A sequenced, replayable, non-blocking in-process publish/subscribe bus."""

    def __init__(
        self,
        clock: Clock,
        *,
        buffer_size: int = 2000,
        subscriber_queue_size: int = 1000,
    ) -> None:
        """Configure the bus.

        ``buffer_size`` defaults to 2000 — comfortably more than the frames a full
        50-transaction batch emits, so a client that reconnects at any point during
        a demo can always be backfilled from the buffer rather than told to refetch.
        """
        self._clock = clock
        self._seq = 0
        self._buffer: deque[Event] = deque(maxlen=buffer_size)
        self._subscriber_queue_size = subscriber_queue_size
        self._subscribers: set[Subscription] = set()

    def publish(self, type: str, payload: dict[str, object]) -> Event:
        """Assign the next ``seq``, buffer the event, and offer it to every subscriber.

        Never blocks: a subscriber too slow to keep up is marked overflowed rather
        than allowed to stall this call, so one stuck client cannot freeze the batch.
        """
        self._seq += 1
        event = Event(type=type, seq=self._seq, ts=self._clock.now(), payload=payload)
        self._buffer.append(event)
        for subscriber in list(self._subscribers):
            subscriber._offer(event)
        return event

    def since(self, last_seq: int, limit: int = 500) -> list[Event]:
        """Buffered events with ``seq > last_seq``, oldest first, capped at ``limit``."""
        return [event for event in self._buffer if event.seq > last_seq][:limit]

    @property
    def current_seq(self) -> int:
        """The highest ``seq`` assigned so far (``0`` before anything is published)."""
        return self._seq

    def earliest_seq(self) -> int:
        """The lowest ``seq`` still in the replay buffer, or ``0`` if it is empty.

        The WebSocket handshake compares a client's ``last_seq`` against this: if the
        client is older than the buffer's oldest frame, the gap cannot be replayed
        and the client is told to refetch via ``GET /api/audit`` instead.
        """
        return self._buffer[0].seq if self._buffer else 0

    def has_gap(self, last_seq: int) -> bool:
        """Whether ``last_seq`` is too old to be backfilled from the buffer.

        ``last_seq == 0`` (a fresh page) is never a gap — there is nothing missed to
        replay. Otherwise a gap exists when the buffer no longer retains the frame
        immediately after ``last_seq``.
        """
        if last_seq <= 0:
            return False
        earliest = self.earliest_seq()
        return earliest > last_seq + 1

    @contextmanager
    def subscribe(self) -> Iterator[Subscription]:
        """Register a subscriber for the duration of the ``with`` block.

        The subscription is removed on exit, so a client that disconnects leaks
        neither a queue nor a slot in the publisher's fan-out set.
        """
        subscription = Subscription(self._subscriber_queue_size)
        self._subscribers.add(subscription)
        try:
            yield subscription
        finally:
            self._subscribers.discard(subscription)

    @property
    def subscriber_count(self) -> int:
        """How many subscribers are currently connected (for the health endpoint)."""
        return len(self._subscribers)


class EventSink(Protocol):
    """How the domain layer reports what happened, without knowing about the bus.

    The state machine calls :meth:`record_transition` after every committed
    transition; the gate pipeline calls :meth:`record_gate_rejection` when the gate
    refuses an action. Both take domain objects only — the concrete sink (in the API
    layer) turns them into the contract's WebSocket payloads. Both are ``None``-able
    at the call sites, so the batch CLI runs with no sink attached.
    """

    def record_transition(
        self, previous_state: object, item: WorkItem, audit_event: AuditEvent
    ) -> None:
        """A work item moved from ``previous_state`` to ``item.state``, logged as
        ``audit_event`` (which already carries its assigned ``id``)."""
        ...

    def record_gate_rejection(
        self,
        item: WorkItem,
        action: Action,
        *,
        constraint: str,
        reason: str,
        limit_paise: int,
        max_retries: int,
    ) -> None:
        """The constraint gate refused ``action`` for ``item``; ``constraint`` is the
        rule that decided and ``reason`` its human-readable explanation."""
        ...
