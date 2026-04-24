"""Diagnostics broker for #109 — server self-dump + worker round-trip.

Two independent flows share this module's state:

* **Server self-dump** — ``run_self_thread_dump()`` walks the server's
  own Python frames via :func:`sys._current_frames` and returns a
  py-spy-ish text dump. Synchronous but fast (frame walking is pure
  Python + no syscalls); the async wrapper still runs it off the
  event loop so a few hundred threads doesn't stall other UI traffic.

  Originally (#108, 1.6.2-dev.28) this shelled out to ``py-spy dump``
  in a subprocess. #189 replaced that with the in-process walk after
  we found ``py-spy`` couldn't attach inside HA add-on / HAOS /
  Supervised variants (Supervisor drops ``CAP_SYS_PTRACE``, and the
  sidecar workaround from ``scripts/threaddump-addon.sh`` is
  rejected by those variants too). The in-process path has no
  privileged-capability requirement whatsoever.

* **Worker round-trip** — a UI client asks the server to collect a dump
  from a specific worker. The worker only ever polls us (no inbound
  reachability), so we:
    1. mint a ``request_id`` and store it as the pending request for
       that worker (``request_for_worker``);
    2. surface the id on the worker's next ``heartbeat`` /
       ``/control`` response so the worker picks it up within ~1 s
       (``pending_for_worker`` / ``claim_pending``);
    3. accept the worker's upload into the results map keyed by the
       id (``store_result``);
    4. let the UI poll ``get_result`` until the entry shows up.

State is process-local and intentionally in-memory — diagnostics data
is ephemeral triage output, not worth persisting across add-on
restarts. Results auto-expire after ``RESULT_TTL`` so a long-running
server doesn't accumulate a few hundred MB of dumps from repeated
triage sessions.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Seconds until a stored upload result is evicted. 10 min covers a
# generous poll-and-download window; anything older is unlikely to be
# what the user is looking at anyway.
RESULT_TTL: float = 600.0

# Cap on dump size we'll accept from a worker upload. In-process dumps
# run ~5-15 KB for our typical thread count; 2 MB leaves room for
# absurd edge cases while still protecting us from a runaway worker.
MAX_UPLOAD_BYTES: int = 2 * 1024 * 1024


@dataclass
class _DiagnosticsResult:
    request_id: str
    ok: bool
    dump: str
    created_at: float  # monotonic seconds


class DiagnosticsBroker:
    """In-memory store for pending + completed diagnostics requests.

    Thread-safe by a single lock because it's touched from both the
    aiohttp event loop (UI endpoints, worker API handlers) and the
    registry's plain-Python callers.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # client_id -> request_id of the outstanding request (if any).
        self._pending: dict[str, str] = {}
        self._results: dict[str, _DiagnosticsResult] = {}

    def request_for_worker(self, client_id: str) -> str:
        """Create a new request for *client_id*, replacing any prior one.

        Returns the new ``request_id`` the UI should poll for.
        """
        request_id = uuid.uuid4().hex
        with self._lock:
            self._pending[client_id] = request_id
        logger.info("diagnostics: new request %s for worker %s", request_id, client_id)
        return request_id

    def pending_for_worker(self, client_id: str) -> Optional[str]:
        """Return the outstanding ``request_id`` the worker should
        dump against, or ``None`` when nothing is requested."""
        with self._lock:
            return self._pending.get(client_id)

    def claim_pending(self, client_id: str, request_id: str) -> None:
        """Worker acknowledged the request by uploading — clear the
        pending slot so the heartbeat/control response stops asking."""
        with self._lock:
            if self._pending.get(client_id) == request_id:
                del self._pending[client_id]

    def store_result(self, request_id: str, *, ok: bool, dump: str) -> None:
        self._gc_expired()
        with self._lock:
            self._results[request_id] = _DiagnosticsResult(
                request_id=request_id,
                ok=ok,
                dump=dump,
                created_at=time.monotonic(),
            )
        logger.info(
            "diagnostics: stored result for request %s (ok=%s, %d bytes)",
            request_id, ok, len(dump),
        )

    def get_result(self, request_id: str) -> Optional[_DiagnosticsResult]:
        """Return the stored result or ``None`` if still pending / expired."""
        self._gc_expired()
        with self._lock:
            return self._results.get(request_id)

    def _gc_expired(self) -> None:
        cutoff = time.monotonic() - RESULT_TTL
        with self._lock:
            stale = [rid for rid, r in self._results.items() if r.created_at < cutoff]
            for rid in stale:
                del self._results[rid]


def _read_server_version() -> str:
    """Best-effort version string for the dump header. Mirrors the
    same /app/VERSION lookup ``main.py`` uses."""
    try:
        with open("/app/VERSION", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "unknown"


def in_process_thread_dump() -> str:
    """Walk every live Python thread's stack and format the result as
    plain text.

    This is the entire diagnostics mechanism — no ``py-spy``, no
    subprocess, no ``ptrace``. Works inside any container regardless
    of capabilities or AppArmor profile because it never crosses a
    syscall boundary the kernel would mediate.

    Uses :func:`sys._current_frames` (the officially-supported
    introspection hook, same API thread-dumpers have relied on for
    15 years) plus :func:`threading.enumerate` for thread names.
    Format is intentionally close to ``py-spy dump`` output so a
    reader used to the previous format recognises the shape.
    """
    # Snapshot both views up front. ``threading.enumerate`` and
    # ``sys._current_frames`` are documented to return a consistent
    # snapshot; the GIL guarantees no thread finishes mid-walk.
    frames = sys._current_frames()
    threads_by_ident = {t.ident: t for t in threading.enumerate()}

    # Header — process metadata + counts. Matches py-spy's info box
    # closely enough that operators who've seen the old format
    # recognise it on sight.
    lines: list[str] = [
        "ESPHome Fleet thread dump",
        f"Process: pid={os.getpid()}  v{_read_server_version()}",
        f"Python {platform.python_version()} on {sys.platform}",
        f"{len(frames)} thread(s)",
        "",
    ]

    for tid, frame in frames.items():
        thread = threads_by_ident.get(tid)
        if thread is not None:
            name = thread.name
            daemon = "daemon=True" if thread.daemon else "daemon=False"
        else:
            # Very short window where a thread finished between the
            # two snapshots — still dump its frames, just without a
            # friendly name.
            name = "<unknown>"
            daemon = "daemon=?"
        lines.append(f'Thread {tid} "{name}" ({daemon}):')
        # ``format_stack`` returns the call chain outermost-first (main
        # → current), matching py-spy's order. Indent two spaces under
        # the thread header.
        for chunk in traceback.format_stack(frame):
            # Each chunk is already multi-line (`  File "…", line N, in fn\n    <source>\n`).
            # Re-indent so it aligns under the thread header.
            for subline in chunk.rstrip("\n").splitlines():
                lines.append(f"  {subline}")
        lines.append("")

    return "\n".join(lines)


def run_self_thread_dump() -> tuple[bool, str]:
    """Capture a thread dump of the server's own process.

    Returns ``(ok, text)``. ``ok`` is always ``True`` on this code path
    since :func:`in_process_thread_dump` is pure-Python and cannot
    fail under container constraints. The ``bool`` is retained in the
    signature so the worker-upload protocol (``WorkerDiagnosticsUpload``)
    stays source-compatible and so a future capture mechanism that can
    fail has a place to report that.
    """
    return True, in_process_thread_dump()


async def run_self_thread_dump_async() -> tuple[bool, str]:
    """Asyncio-friendly wrapper — runs the frame walk off the event
    loop so a large thread count doesn't stall other UI requests."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, run_self_thread_dump)
