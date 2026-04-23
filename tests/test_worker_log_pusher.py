"""Tests for the WL.2 worker-side pusher-thread lifecycle.

The pusher is started/stopped by heartbeat-response transitions of
``stream_logs``. It drains the LogCaptureHandler ring and POSTs chunks
at 1 Hz while the flag is set.

Rather than exercise ``client.py``'s module-level state (which carries
a lot of configuration dependencies), these tests cover the pure
offset/chunk contract between ``LogCaptureHandler.drain_since`` and
``WorkerLogAppend`` — the ingredients the pusher assembles.
"""

from __future__ import annotations

import logging
import os
import threading

import pytest

from log_capture import LogCaptureHandler
from protocol import WorkerLogAppend

# client.py reads SERVER_URL + SERVER_TOKEN at import time. Ensure
# they're present so the client module can load in tests that exercise
# its _update_log_streaming helper.
os.environ.setdefault("SERVER_URL", "http://localhost:0")
os.environ.setdefault("SERVER_TOKEN", "test-token")


def _record(text: str) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, "", 0, text, None, None)


def _emit_n(handler: LogCaptureHandler, n: int, prefix: str = "L") -> None:
    handler.setFormatter(logging.Formatter("%(message)s"))
    for i in range(n):
        handler.emit(_record(f"{prefix}{i}"))


# ---------------------------------------------------------------------------
# Pusher chunk construction (the core loop body)
# ---------------------------------------------------------------------------


def test_pusher_first_chunk_dumps_full_ring():
    """On first push after flag flip, acked_offset=0 → whole ring sent."""
    handler = LogCaptureHandler()
    _emit_n(handler, 3)
    acked = 0
    chunk, new_offset = handler.drain_since(acked)
    msg = WorkerLogAppend(offset=acked, lines=chunk)
    assert "L0" in msg.lines
    assert "L1" in msg.lines
    assert "L2" in msg.lines
    assert msg.offset == 0
    assert new_offset == len("L0\nL1\nL2\n".encode("utf-8"))


def test_pusher_subsequent_chunks_only_include_new_lines():
    handler = LogCaptureHandler()
    _emit_n(handler, 2)
    _, acked = handler.drain_since(0)
    _emit_n(handler, 2, prefix="M")
    chunk, new_offset = handler.drain_since(acked)
    assert "L0" not in chunk
    assert "L1" not in chunk
    assert "M0" in chunk
    assert "M1" in chunk
    assert new_offset > acked


def test_pusher_empty_tick_yields_nothing_to_send():
    """A tick with no new lines must not POST a no-op."""
    handler = LogCaptureHandler()
    chunk, new_offset = handler.drain_since(0)
    assert chunk == ""
    # Empty WorkerLogAppend is still a valid round-trip, but the
    # pusher is expected to SKIP the POST entirely on empty chunks.
    # The test lives at the handler level so the pusher doesn't need
    # to run — just assert that the empty-chunk signal is available.
    assert new_offset == 0


def test_pusher_offset_matches_acked_on_retry_semantics():
    """If the POST fails, the pusher does NOT advance acked_offset.

    That means the next drain_since(acked) call returns the SAME chunk.
    """
    handler = LogCaptureHandler()
    _emit_n(handler, 2)
    acked = 0
    first, first_new = handler.drain_since(acked)
    # Simulate a 5xx: don't advance acked.
    second, second_new = handler.drain_since(acked)
    assert first == second
    assert first_new == second_new


# ---------------------------------------------------------------------------
# _update_log_streaming state transitions
# ---------------------------------------------------------------------------


def test_update_log_streaming_none_is_noop():
    """No flag in the heartbeat response = no state change."""
    import client as client_module  # noqa: PLC0415

    before = client_module._stream_logs_event.is_set()
    stop = threading.Event()
    client_module._update_log_streaming("cid", None, stop)
    assert client_module._stream_logs_event.is_set() is before


def test_update_log_streaming_true_sets_event():
    import client as client_module  # noqa: PLC0415

    client_module._stream_logs_event.clear()
    stop = threading.Event()
    try:
        client_module._update_log_streaming("cid", True, stop)
        assert client_module._stream_logs_event.is_set() is True
    finally:
        # Signal the pusher thread to exit so it doesn't outlive the test.
        stop.set()
        client_module._stream_logs_event.clear()


def test_update_log_streaming_false_clears_event():
    import client as client_module  # noqa: PLC0415

    client_module._stream_logs_event.set()
    stop = threading.Event()
    try:
        client_module._update_log_streaming("cid", False, stop)
        assert client_module._stream_logs_event.is_set() is False
    finally:
        stop.set()


# ---------------------------------------------------------------------------
# Control-poll loop: fast-path 1 Hz signal delivery
# ---------------------------------------------------------------------------


def test_control_poll_flips_stream_logs_on_server_true(monkeypatch):
    """The 1 Hz control-poll must react to server state faster than
    the 10 s heartbeat would.
    """
    import client as client_module  # noqa: PLC0415

    client_module._stream_logs_event.clear()

    class _FakeResp:
        ok = True
        def json(self):
            return {"stream_logs": True}

    call_count = {"n": 0}

    def fake_get(path, **kwargs):
        call_count["n"] += 1
        return _FakeResp()

    monkeypatch.setattr(client_module, "get", fake_get)

    stop = threading.Event()
    t = threading.Thread(
        target=client_module._control_poll_loop,
        args=("cid", stop),
        daemon=True,
    )
    t.start()
    try:
        # One tick of 1.0 s; give a bit of slack.
        deadline = threading.Event()
        for _ in range(30):
            if client_module._stream_logs_event.is_set():
                break
            deadline.wait(0.1)
        assert client_module._stream_logs_event.is_set() is True
        assert call_count["n"] >= 1
    finally:
        stop.set()
        t.join(timeout=2)
        client_module._stream_logs_event.clear()


def test_control_poll_tolerates_transport_errors(monkeypatch):
    """Connection errors during the poll must not crash the loop."""
    import client as client_module  # noqa: PLC0415
    import requests as _requests  # noqa: PLC0415

    def fake_get(path, **kwargs):
        raise _requests.exceptions.ConnectionError("simulated")

    monkeypatch.setattr(client_module, "get", fake_get)

    stop = threading.Event()
    t = threading.Thread(
        target=client_module._control_poll_loop,
        args=("cid", stop),
        daemon=True,
    )
    t.start()
    try:
        stop.wait(0.3)  # let the loop spin a couple of times
        assert t.is_alive()  # didn't crash
    finally:
        stop.set()
        t.join(timeout=2)
