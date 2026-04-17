"""Server event bus — #41 real-time push tests."""

from __future__ import annotations

import asyncio

import pytest

import event_bus


@pytest.fixture(autouse=True)
def _reset_subscribers():
    """Clear the module-level subscriber set between tests."""
    event_bus._subscribers.clear()
    yield
    event_bus._subscribers.clear()


async def test_broadcast_delivers_to_subscriber() -> None:
    q = event_bus.subscribe()
    event_bus.broadcast(event_bus.EVENT_QUEUE_CHANGED)
    msg = await asyncio.wait_for(q.get(), timeout=1.0)
    assert msg == {"type": "queue_changed"}


async def test_broadcast_delivers_to_multiple_subscribers() -> None:
    q1 = event_bus.subscribe()
    q2 = event_bus.subscribe()
    event_bus.broadcast(event_bus.EVENT_WORKERS_CHANGED)
    m1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    m2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert m1 == m2 == {"type": "workers_changed"}


def test_broadcast_no_subscribers_is_noop() -> None:
    # Should not raise or block with no subscribers.
    event_bus.broadcast(event_bus.EVENT_TARGETS_CHANGED)
    assert event_bus.subscriber_count() == 0


async def test_broadcast_drops_oldest_on_full_queue() -> None:
    q = event_bus.subscribe()
    # Fill the queue to _QUEUE_MAX.
    for i in range(event_bus._QUEUE_MAX):
        event_bus.broadcast(event_bus.EVENT_QUEUE_CHANGED, seq=i)
    # Next broadcast should drop the oldest and deliver the new one.
    event_bus.broadcast(event_bus.EVENT_QUEUE_CHANGED, seq=999)
    # Drain.
    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    assert len(msgs) == event_bus._QUEUE_MAX
    # Last message should be the 999-seq one (newest preserved).
    assert msgs[-1]["seq"] == 999
    # First message should be seq=1 (seq=0 was dropped to make room).
    assert msgs[0]["seq"] == 1


def test_unsubscribe_removes_queue() -> None:
    q = event_bus.subscribe()
    assert event_bus.subscriber_count() == 1
    event_bus.unsubscribe(q)
    assert event_bus.subscriber_count() == 0
    # Idempotent — second unsubscribe is a no-op.
    event_bus.unsubscribe(q)
    assert event_bus.subscriber_count() == 0


async def test_broadcast_carries_payload() -> None:
    q = event_bus.subscribe()
    event_bus.broadcast(event_bus.EVENT_DEVICES_CHANGED, device="living-room", online=True)
    msg = await asyncio.wait_for(q.get(), timeout=1.0)
    assert msg == {"type": "devices_changed", "device": "living-room", "online": True}
