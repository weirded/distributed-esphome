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
