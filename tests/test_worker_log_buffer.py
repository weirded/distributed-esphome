"""Tests for the worker-side LogCaptureHandler (WL.1).

The handler tees formatted log records into a bounded ring buffer with
a monotonic byte-offset counter. Exposed via ``drain_since(offset)``,
which is what the WL.2 pusher thread reads.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
from io import StringIO

import pytest

from log_capture import LogCaptureHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler(maxlen: int = 2000) -> LogCaptureHandler:
    handler = LogCaptureHandler(maxlen=maxlen)
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


# ---------------------------------------------------------------------------
# Basic buffering
# ---------------------------------------------------------------------------


def test_emit_appends_formatted_line_to_buffer():
    handler = _make_handler()
    record = logging.LogRecord("t", logging.INFO, "", 0, "hello", None, None)
    handler.emit(record)
    chunk, _ = handler.drain_since(0)
    assert chunk == "hello\n"


def test_drain_since_returns_new_offset():
    handler = _make_handler()
    handler.emit(logging.LogRecord("t", logging.INFO, "", 0, "one", None, None))
    chunk, new_offset = handler.drain_since(0)
    assert chunk == "one\n"
    # 4 bytes = "one\n"
    assert new_offset == 4


def test_drain_since_advances_cursor_across_calls():
    handler = _make_handler()
    handler.emit(logging.LogRecord("t", logging.INFO, "", 0, "one", None, None))
    chunk1, off1 = handler.drain_since(0)
    handler.emit(logging.LogRecord("t", logging.INFO, "", 0, "two", None, None))
    chunk2, off2 = handler.drain_since(off1)
    assert chunk1 == "one\n"
    assert chunk2 == "two\n"
    assert off2 == off1 + len("two\n")


def test_drain_since_with_current_offset_returns_empty():
    handler = _make_handler()
    handler.emit(logging.LogRecord("t", logging.INFO, "", 0, "x", None, None))
    _, off = handler.drain_since(0)
    chunk, off2 = handler.drain_since(off)
    assert chunk == ""
    assert off2 == off


def test_drain_since_with_stale_cursor_returns_full_buffer():
    # A cursor from a previous worker session is effectively "give me
    # everything you have" — this is the first-push-after-restart case.
    handler = _make_handler()
    handler.emit(logging.LogRecord("t", logging.INFO, "", 0, "one", None, None))
    handler.emit(logging.LogRecord("t", logging.INFO, "", 0, "two", None, None))
    chunk, _ = handler.drain_since(-1)
    assert "one" in chunk and "two" in chunk


def test_buffer_drops_oldest_when_full():
    handler = _make_handler(maxlen=3)
    for i in range(5):
        handler.emit(logging.LogRecord("t", logging.INFO, "", 0, f"line{i}", None, None))
    chunk, _ = handler.drain_since(-1)
    # maxlen=3 so only line2/3/4 should remain.
    assert "line0" not in chunk
    assert "line1" not in chunk
    assert "line2" in chunk
    assert "line3" in chunk
    assert "line4" in chunk


def test_byte_offset_persists_past_ring_rotation():
    # Even after the oldest lines fall out of the ring, the byte-offset
    # counter keeps advancing monotonically — that's how the server's
    # restart detection works.
    handler = _make_handler(maxlen=2)
    for i in range(5):
        handler.emit(logging.LogRecord("t", logging.INFO, "", 0, f"L{i}", None, None))
    _, off = handler.drain_since(0)
    # Each formatted line is "L<i>\n" = 3 bytes (or 4 for L10+). Five
    # lines = at least 15 bytes total.
    assert off >= 15


# ---------------------------------------------------------------------------
# Does NOT suppress stdout
# ---------------------------------------------------------------------------


def test_emit_does_not_replace_stream_handler():
    """The capture handler is a tee — stdout logging must still work."""
    root = logging.getLogger("wl.test_tee")
    root.setLevel(logging.INFO)
    # Sink to capture stdout-equivalent output
    stream = StringIO()
    stream_handler = logging.StreamHandler(stream)
    stream_handler.setFormatter(logging.Formatter("%(message)s"))
    capture = LogCaptureHandler()
    capture.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(stream_handler)
    root.addHandler(capture)
    try:
        root.info("tee-test")
    finally:
        root.removeHandler(stream_handler)
        root.removeHandler(capture)
    assert "tee-test" in stream.getvalue()
    assert "tee-test" in capture.drain_since(0)[0]


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def test_concurrent_append_and_drain_is_safe():
    handler = _make_handler(maxlen=10_000)
    barrier = threading.Barrier(51)
    lines_per_thread = 50

    def producer(tid: int) -> None:
        barrier.wait()
        for i in range(lines_per_thread):
            handler.emit(
                logging.LogRecord(
                    "t", logging.INFO, "", 0, f"t{tid}-L{i}", None, None,
                )
            )

    def consumer() -> str:
        barrier.wait()
        # Drain repeatedly until we have at least one full pass. The
        # point of the test is that .drain_since doesn't corrupt state.
        acc = []
        last = 0
        for _ in range(100):
            chunk, last = handler.drain_since(last)
            if chunk:
                acc.append(chunk)
        return "".join(acc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=51) as pool:
        producers = [pool.submit(producer, tid) for tid in range(50)]
        consumer_fut = pool.submit(consumer)
        for p in producers:
            p.result()
        consumed = consumer_fut.result()

    # After all producers finish, a final drain should yield the rest.
    final_chunk, _ = handler.drain_since(0)
    # 50 threads × 50 lines each = 2500 lines. All of them must land
    # somewhere in the buffer (no loss because maxlen > 2500).
    combined = consumed + final_chunk
    for tid in range(50):
        for i in range(lines_per_thread):
            tag = f"t{tid}-L{i}"
            assert tag in combined, f"lost line {tag}"
