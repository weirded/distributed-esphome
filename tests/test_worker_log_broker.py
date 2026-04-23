"""Tests for WorkerLogBroker (WL.2 server side).

The broker owns per-worker log buffers, WS subscriber counts, and the
1 h eviction task. It's the piece the heartbeat handler calls to answer
"is someone watching this worker?" — the reply drives the stream_logs
flag that flips log pushes on and off.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from worker_log_broker import WorkerLogBroker, RESTART_SEPARATOR


# ---------------------------------------------------------------------------
# is_watched / subscribe / unsubscribe
# ---------------------------------------------------------------------------


class TestSubscriberCounting:
    def test_is_watched_false_when_nobody_watching(self) -> None:
        broker = WorkerLogBroker()
        assert broker.is_watched("w1") is False

    def test_subscribe_flips_is_watched_true(self) -> None:
        broker = WorkerLogBroker()
        fake_ws = object()
        broker.subscribe("w1", fake_ws)
        assert broker.is_watched("w1") is True

    def test_unsubscribe_flips_back_to_false(self) -> None:
        broker = WorkerLogBroker()
        fake_ws = object()
        broker.subscribe("w1", fake_ws)
        broker.unsubscribe("w1", fake_ws)
        assert broker.is_watched("w1") is False

    def test_two_subscribers_still_watched_when_one_leaves(self) -> None:
        broker = WorkerLogBroker()
        ws_a, ws_b = object(), object()
        broker.subscribe("w1", ws_a)
        broker.subscribe("w1", ws_b)
        broker.unsubscribe("w1", ws_a)
        assert broker.is_watched("w1") is True
        broker.unsubscribe("w1", ws_b)
        assert broker.is_watched("w1") is False

    def test_is_watched_is_per_worker(self) -> None:
        broker = WorkerLogBroker()
        broker.subscribe("w1", object())
        assert broker.is_watched("w1") is True
        assert broker.is_watched("w2") is False

    def test_unsubscribe_of_unknown_subscriber_is_noop(self) -> None:
        # A WS that closes before we saw it shouldn't blow up teardown.
        broker = WorkerLogBroker()
        broker.unsubscribe("w1", object())
        assert broker.is_watched("w1") is False

    def test_unsubscribe_of_wrong_instance_keeps_subscription(self) -> None:
        # Subscribe with ws_a; unsubscribe is identity-based, so calling
        # with ws_b must NOT remove ws_a.
        broker = WorkerLogBroker()
        ws_a, ws_b = object(), object()
        broker.subscribe("w1", ws_a)
        broker.unsubscribe("w1", ws_b)
        assert broker.is_watched("w1") is True


# ---------------------------------------------------------------------------
# append() — offset math, restart detection, buffer bounds
# ---------------------------------------------------------------------------


class TestAppend:
    def test_append_from_empty_state_accepts(self) -> None:
        broker = WorkerLogBroker()
        broker.append("w1", offset=0, lines="hello\n")
        assert broker.snapshot("w1") == "hello\n"

    def test_append_happy_path_concatenates(self) -> None:
        broker = WorkerLogBroker()
        broker.append("w1", offset=0, lines="one\n")
        broker.append("w1", offset=4, lines="two\n")
        assert broker.snapshot("w1") == "one\ntwo\n"

    def test_append_replay_past_chunk_deduplicates(self) -> None:
        # Pusher retry after a lost response: first push succeeded and
        # advanced the server offset, but the worker never got the ack
        # so the pusher retries with the same (offset, lines).
        broker = WorkerLogBroker()
        broker.append("w1", offset=0, lines="one\n")
        broker.append("w1", offset=4, lines="two\n")  # advances to 8
        broker.append("w1", offset=4, lines="two\n")  # retry, dedupe
        assert broker.snapshot("w1") == "one\ntwo\n"

    def test_append_offset_gap_accepts_with_warning(self) -> None:
        # Server state lost mid-session; worker's next push has a large
        # offset. Accept and move on (lines are bounded by the ring anyway).
        broker = WorkerLogBroker()
        broker.append("w1", offset=0, lines="one\n")
        broker.append("w1", offset=1000, lines="later\n")
        snap = broker.snapshot("w1")
        assert "one" in snap
        assert "later" in snap

    def test_append_offset_backwards_is_restart(self) -> None:
        # Worker restarted: first push after restart uses offset=0 again
        # but server's _next_offset is non-zero. Inject the separator.
        broker = WorkerLogBroker()
        broker.append("w1", offset=0, lines="boot msg\n")
        broker.append("w1", offset=9, lines="later\n")
        broker.append("w1", offset=0, lines="fresh boot\n")  # restart
        snap = broker.snapshot("w1")
        assert "boot msg" in snap
        assert RESTART_SEPARATOR in snap
        assert "fresh boot" in snap
        # And subsequent pushes from the new session append normally.
        broker.append("w1", offset=11, lines="after restart\n")
        assert "after restart" in broker.snapshot("w1")

    def test_snapshot_of_unknown_worker_is_empty(self) -> None:
        broker = WorkerLogBroker()
        assert broker.snapshot("nobody") == ""

    def test_buffer_maxlen_drops_oldest(self) -> None:
        broker = WorkerLogBroker(buffer_maxlen=3)
        for i in range(5):
            broker.append("w1", offset=i * 2, lines=f"{i}\n")
        snap = broker.snapshot("w1")
        # Oldest two lines gone, newest three kept.
        assert "0\n" not in snap
        assert "1\n" not in snap
        assert "2\n" in snap
        assert "3\n" in snap
        assert "4\n" in snap


# ---------------------------------------------------------------------------
# Fanout to WS subscribers
# ---------------------------------------------------------------------------


class _FakeWS:
    """Minimal stand-in for aiohttp WebSocketResponse.send_str()."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_str(self, data: str) -> None:
        self.sent.append(data)


class TestFanout:
    async def test_append_fans_out_to_subscribers(self) -> None:
        broker = WorkerLogBroker()
        ws = _FakeWS()
        broker.subscribe("w1", ws)
        await broker.append_async("w1", offset=0, lines="streamed\n")
        assert ws.sent == ["streamed\n"]

    async def test_restart_separator_is_fanned_out(self) -> None:
        broker = WorkerLogBroker()
        ws = _FakeWS()
        broker.subscribe("w1", ws)
        await broker.append_async("w1", offset=0, lines="initial\n")
        await broker.append_async("w1", offset=8, lines="more\n")
        await broker.append_async("w1", offset=0, lines="post-restart\n")
        # Separator appears in the fan-out stream between "more" and the
        # post-restart content.
        joined = "".join(ws.sent)
        assert "initial" in joined
        assert RESTART_SEPARATOR in joined
        assert "post-restart" in joined
        # Order: separator lands before post-restart content.
        assert joined.index(RESTART_SEPARATOR) < joined.index("post-restart")

    async def test_fanout_skips_unsubscribed(self) -> None:
        broker = WorkerLogBroker(evict_after_seconds=3600)
        ws = _FakeWS()
        broker.subscribe("w1", ws)
        broker.unsubscribe("w1", ws)
        await broker.append_async("w1", offset=0, lines="nope\n")
        assert ws.sent == []
        await broker.aclose()


# ---------------------------------------------------------------------------
# 1-hour eviction after last unsubscribe
# ---------------------------------------------------------------------------


class TestEviction:
    async def test_unsubscribe_schedules_eviction(self) -> None:
        broker = WorkerLogBroker(evict_after_seconds=0.05)
        ws = object()
        broker.subscribe("w1", ws)
        broker.append("w1", offset=0, lines="data\n")
        broker.unsubscribe("w1", ws)  # triggers eviction timer
        # Wait long enough for the eviction task to fire.
        await asyncio.sleep(0.15)
        assert broker.snapshot("w1") == ""

    async def test_resubscribe_cancels_pending_eviction(self) -> None:
        broker = WorkerLogBroker(evict_after_seconds=0.05)
        ws_a = object()
        broker.subscribe("w1", ws_a)
        broker.append("w1", offset=0, lines="data\n")
        broker.unsubscribe("w1", ws_a)
        # User reopens the dialog before the eviction fires.
        await asyncio.sleep(0.01)
        broker.subscribe("w1", object())
        await asyncio.sleep(0.1)  # past the eviction deadline
        assert "data" in broker.snapshot("w1")

    async def test_eviction_does_not_fire_while_watched(self) -> None:
        broker = WorkerLogBroker(evict_after_seconds=0.05)
        broker.subscribe("w1", object())
        broker.append("w1", offset=0, lines="data\n")
        await asyncio.sleep(0.1)
        assert "data" in broker.snapshot("w1")
