"""Worker-side log capture for WL.1 pull-when-watched streaming.

Attaches a ``logging.Handler`` to the root logger that tees every
formatted record into a bounded ring buffer + a monotonic byte-offset
counter. The pusher thread (started only while the server's
``stream_logs`` flag is on) drains the buffer via ``drain_since`` and
POSTs the chunk to ``/api/v1/workers/{client_id}/logs``.

The buffer is process-lifetime only — no disk persistence. A 2000-line
ceiling (~2 MB in the common case) is cheap insurance so the backlog
is ready whenever the server asks.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Deque, Tuple

DEFAULT_MAXLEN = 2000


class LogCaptureHandler(logging.Handler):
    """Tee formatted log records into a bounded ring + byte-offset counter.

    Thread-safe: the handler may fire from the main thread, the heartbeat
    thread, or any of the worker-slot job threads, all under
    ``logging.Handler``'s own lock plus our internal ``_lock`` that
    protects the ring + offset.
    """

    def __init__(self, *, maxlen: int = DEFAULT_MAXLEN) -> None:
        super().__init__()
        # Each entry is (formatted_line_with_newline, byte_offset_of_FIRST_byte).
        # Keeping the offset per line lets ``drain_since`` produce a
        # chunk-to-send AND report the byte offset that chunk ends at
        # without rescanning.
        self._lines: Deque[Tuple[str, int]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        # Total bytes ever appended (monotonic across ring rotation).
        # This is the offset the next-appended line will start at.
        self._next_offset = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
        except Exception:
            self.handleError(record)
            return
        if not text.endswith("\n"):
            text += "\n"
        encoded_len = len(text.encode("utf-8"))
        with self._lock:
            offset = self._next_offset
            self._lines.append((text, offset))
            self._next_offset = offset + encoded_len

    def drain_since(self, since_offset: int) -> Tuple[str, int]:
        """Return ``(chunk, new_offset)`` covering lines past ``since_offset``.

        If ``since_offset`` is older than the oldest line currently in
        the ring (either because the worker restarted and the caller
        passed a stale cursor, or because lines fell off the ring),
        everything still in the buffer is returned. The server's
        restart-detection handles the offset-went-backwards case.

        If there's nothing new, returns ``("", since_offset)``.
        """
        with self._lock:
            if not self._lines:
                return "", self._next_offset
            # Find the first line whose offset >= since_offset. If none,
            # the cursor is past everything we have — return empty.
            parts = [text for text, off in self._lines if off >= since_offset]
            if not parts:
                return "", self._next_offset
            return "".join(parts), self._next_offset
