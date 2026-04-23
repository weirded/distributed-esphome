"""Per-worker log broker for WL.2 pull-when-watched streaming.

The broker is the server-side pivot between worker log pushes and UI
WebSocket subscribers. It owns three pieces of state per ``client_id``:

- a bounded line buffer (2000 lines) that backs the initial hydration
  a UI gets when it opens the log dialog;
- a set of WS subscribers that receive each new chunk as it arrives;
- an eviction task that clears the buffer one hour after the last
  subscriber disconnects, so an unused worker's logs don't linger.

The broker is deliberately independent of ``registry.Worker``: the
registry tracks liveness + config; this module tracks log transport.
Couple them via ``client_id`` only.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

# ANSI dim escape + reset around the separator so it renders muted in
# xterm. Matches the compile-log colour palette.
RESTART_SEPARATOR = "\x1b[2m--- worker restarted ---\x1b[0m\n"

DEFAULT_BUFFER_MAXLEN = 2000
DEFAULT_EVICT_AFTER_SECONDS = 3600  # 1 h


class WorkerLogBroker:
    """Per-worker log buffer + subscriber set + eviction timer."""

    def __init__(
        self,
        *,
        buffer_maxlen: int = DEFAULT_BUFFER_MAXLEN,
        evict_after_seconds: float = DEFAULT_EVICT_AFTER_SECONDS,
    ) -> None:
        self._buffer_maxlen = buffer_maxlen
        self._evict_after = evict_after_seconds
        self._buffers: dict[str, deque[str]] = {}
        # Byte-offset the server expects on the NEXT push from this
        # worker. Absent key treated as 0.
        self._next_offset: dict[str, int] = {}
        self._subscribers: dict[str, set[Any]] = {}
        self._evict_tasks: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------
    # Subscribers
    # ------------------------------------------------------------------

    def is_watched(self, client_id: str) -> bool:
        return bool(self._subscribers.get(client_id))

    def subscribe(self, client_id: str, ws: Any) -> None:
        self._subscribers.setdefault(client_id, set()).add(ws)
        # If a prior unsubscribe scheduled eviction, cancel it.
        task = self._evict_tasks.pop(client_id, None)
        if task is not None and not task.done():
            task.cancel()

    def unsubscribe(self, client_id: str, ws: Any) -> None:
        subs = self._subscribers.get(client_id)
        if not subs:
            return
        subs.discard(ws)
        if not subs:
            self._subscribers.pop(client_id, None)
            self._schedule_eviction(client_id)

    # ------------------------------------------------------------------
    # Buffer
    # ------------------------------------------------------------------

    def snapshot(self, client_id: str) -> str:
        buf = self._buffers.get(client_id)
        if not buf:
            return ""
        return "".join(buf)

    def append(self, client_id: str, offset: int, lines: str) -> str:
        """Append a push to the buffer. Returns text to fan out to WS.

        Dedupe: a push with ``offset`` equal to the server's currently-
        expected next offset is the happy path. A push whose offset is
        *less* than that value is either a retry of the same chunk (same
        offset, same length → no-op, returns "") or evidence of a worker
        restart (different content, offset reset to 0). A push whose
        offset is *greater* than the expected value is a gap (server
        state lost mid-session, or a dropped chunk) — accept and warn.

        The returned string is what ``append_async`` should broadcast:
        either just ``lines`` on the happy path, or the restart
        separator concatenated with ``lines`` on a restart.
        """
        next_offset = self._next_offset.get(client_id, 0)
        broadcast_parts: list[str] = []

        if offset == next_offset:
            # Happy path (and also the very-first-ever push where both
            # are 0).
            pass
        elif offset == 0 and next_offset > 0:
            # Restart: the pusher only resets its local offset counter
            # to 0 when the worker process starts fresh. Any seeing-0-
            # after-advance is unambiguously a new worker session.
            self._ensure_buffer(client_id).append(RESTART_SEPARATOR)
            broadcast_parts.append(RESTART_SEPARATOR)
            self._next_offset[client_id] = 0
            next_offset = 0
        elif offset < next_offset:
            # Retry of a chunk whose response was lost (we already
            # accepted it; the worker got no ack). Content's in the
            # buffer; drop.
            return ""
        else:
            logger.warning(
                "worker %s log push at offset %d but next expected %d; accepting with gap",
                client_id, offset, next_offset,
            )

        if lines:
            self._ensure_buffer(client_id).append(lines)
            broadcast_parts.append(lines)
        self._next_offset[client_id] = offset + len(lines.encode("utf-8"))
        return "".join(broadcast_parts)

    async def append_async(self, client_id: str, offset: int, lines: str) -> None:
        """Append + fan out to WS subscribers.

        The sync ``append`` is enough when no subscribers are attached;
        this variant is what the POST handler calls so live watchers
        see the new chunk without waiting for the next UI poll.
        """
        # Snapshot the subscriber set before append so a subscriber
        # added mid-call doesn't get a partial view of the same chunk.
        subs_before = list(self._subscribers.get(client_id, ()))
        payload = self.append(client_id, offset, lines)
        if payload and subs_before:
            await self._broadcast(subs_before, payload)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_buffer(self, client_id: str) -> deque[str]:
        buf = self._buffers.get(client_id)
        if buf is None:
            buf = deque(maxlen=self._buffer_maxlen)
            self._buffers[client_id] = buf
        return buf

    async def _broadcast(self, subs: list[Any], text: str) -> None:
        await asyncio.gather(
            *(self._safe_send(ws, text) for ws in subs),
            return_exceptions=True,
        )

    async def _safe_send(self, ws: Any, text: str) -> None:
        try:
            await ws.send_str(text)
        except Exception:  # pragma: no cover — defensive; per-ws survive
            logger.debug("dropping dead worker-log subscriber", exc_info=True)

    def _schedule_eviction(self, client_id: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Called from a sync context with no running loop — happens
            # only in unit tests that exercise subscribe/unsubscribe
            # without driving the event loop. Production code always
            # calls unsubscribe from inside the aiohttp WS handler.
            return
        task = loop.create_task(self._evict_after_delay(client_id))
        self._evict_tasks[client_id] = task

    async def _evict_after_delay(self, client_id: str) -> None:
        try:
            await asyncio.sleep(self._evict_after)
        except asyncio.CancelledError:
            return
        # Last-chance check: a subscriber may have arrived between the
        # sleep ending and this line. If so, skip eviction.
        if self.is_watched(client_id):
            return
        self._buffers.pop(client_id, None)
        self._next_offset.pop(client_id, None)
        self._evict_tasks.pop(client_id, None)

    async def aclose(self) -> None:
        """Cancel any pending eviction tasks. Call on server shutdown."""
        tasks = list(self._evict_tasks.values())
        self._evict_tasks.clear()
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
