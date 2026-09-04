"""Tests for the sequenced event bus (PRD §8.8, §13.3).

The two properties that matter on stage: a reconnecting client can be backfilled
exactly (sequence + replay buffer), and one stalled subscriber never stalls the
publisher (per-subscriber bounded queues that overflow instead of blocking).
"""

from __future__ import annotations

import asyncio

import pytest

from recoup.clock import SimulatedClock
from recoup.events import EventBus, SubscriberOverflow
from tests.conftest import CREATED_AT


def _bus(**kwargs: int) -> EventBus:
    return EventBus(SimulatedClock(start=CREATED_AT), **kwargs)


def test_publish_assigns_strictly_increasing_seq() -> None:
    bus = _bus()
    first = bus.publish("audit.appended", {"id": 1})
    second = bus.publish("audit.appended", {"id": 2})
    assert (first.seq, second.seq) == (1, 2)
    assert bus.current_seq == 2


def test_since_returns_only_newer_events_in_order() -> None:
    bus = _bus()
    for i in range(5):
        bus.publish("audit.appended", {"id": i})
    tail = bus.since(2)
    assert [e.seq for e in tail] == [3, 4, 5]


def test_since_respects_the_limit() -> None:
    bus = _bus()
    for i in range(10):
        bus.publish("audit.appended", {"id": i})
    assert [e.seq for e in bus.since(0, limit=3)] == [1, 2, 3]


def test_has_gap_is_false_for_a_fresh_client_and_within_the_buffer() -> None:
    bus = _bus()
    for i in range(3):
        bus.publish("x", {"i": i})
    assert bus.has_gap(0) is False  # fresh page: nothing missed
    assert bus.has_gap(1) is False  # 2,3 still buffered


def test_has_gap_is_true_when_last_seq_fell_out_of_the_buffer() -> None:
    bus = _bus(buffer_size=3)
    for i in range(10):  # only seq 8,9,10 remain
        bus.publish("x", {"i": i})
    assert bus.earliest_seq() == 8
    assert bus.has_gap(2) is True  # client at 2 cannot be replayed from a 8.. buffer


async def test_a_subscriber_receives_published_events_in_order() -> None:
    bus = _bus()
    received: list[int] = []

    async def consume() -> None:
        with bus.subscribe() as sub:
            async for event in sub.events():
                received.append(event.seq)
                if event.seq == 3:
                    return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let the consumer subscribe before we publish
    for _ in range(3):
        bus.publish("x", {})
    await asyncio.wait_for(task, timeout=1)
    assert received == [1, 2, 3]


async def test_a_slow_subscriber_overflows_without_blocking_the_publisher() -> None:
    bus = _bus(subscriber_queue_size=2)
    with bus.subscribe() as sub:
        # Publish more than the subscriber's queue can hold without it draining.
        for _ in range(5):
            bus.publish("x", {})  # must not block or raise
        # The publisher kept its sequence moving despite the stalled subscriber.
        assert bus.current_seq == 5
        with pytest.raises(SubscriberOverflow):
            async for _ in sub.events():
                pass


async def test_one_overflowing_subscriber_does_not_affect_another() -> None:
    # A small queue plus a consumer that drains between publishes: the fast
    # consumer stays current while the never-draining one overflows and is dropped.
    bus = _bus(subscriber_queue_size=2)
    fast_received: list[int] = []

    async def fast_consumer(ready: asyncio.Event) -> None:
        with bus.subscribe() as sub:
            ready.set()
            async for event in sub.events():
                fast_received.append(event.seq)
                if event.seq == 4:
                    return

    with bus.subscribe() as stalled:  # never drains -> will overflow
        ready = asyncio.Event()
        task = asyncio.create_task(fast_consumer(ready))
        await ready.wait()
        for _ in range(4):
            bus.publish("x", {})
            await asyncio.sleep(0)  # let the fast consumer drain this frame
        await asyncio.wait_for(task, timeout=1)
    assert fast_received == [1, 2, 3, 4]
    assert stalled.overflowed is True


def test_subscriber_count_tracks_active_subscriptions() -> None:
    bus = _bus()
    assert bus.subscriber_count == 0
    with bus.subscribe():
        assert bus.subscriber_count == 1
    assert bus.subscriber_count == 0
