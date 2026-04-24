"""Diagnostics broker for #109 — server self-dump + worker round-trip.

Two independent flows share this module's state:

* **Server self-dump** — ``run_self_thread_dump()`` runs ``py-spy dump
  --pid 1`` in a subprocess against the server's own process and returns
  the text. Called directly from the UI endpoint; no broker state needed
  because the request is synchronous.

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
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Seconds until a stored upload result is evicted. 10 min covers a
# generous poll-and-download window; anything older is unlikely to be
# what the user is looking at anyway.
RESULT_TTL: float = 600.0

# Hard cap on subprocess wall-clock for py-spy. `py-spy dump` is
# sample-free (just walks Python frames once) so it's fast — 20 s is
# comfortable even for a process pinned at 100 % CPU.
PY_SPY_TIMEOUT: float = 20.0

# Cap on dump size we'll accept from a worker upload. py-spy dumps are
# ~10 KB per hundred threads; 2 MB leaves room for absurd edge cases
# while still protecting us from a malicious/runaway worker trying to
# push a gigabyte.
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


def _py_spy_binary() -> Optional[str]:
    """Resolve the ``py-spy`` binary on the current host, or ``None``
    when it isn't installed. Using ``shutil.which`` rather than a fixed
    ``/usr/local/bin/py-spy`` because pip wheels land the binary in
    whatever venv ``pip install`` was run against, which varies between
    the add-on image, the standalone image, and hand-installed setups.
    """
    return shutil.which("py-spy")


def run_self_thread_dump() -> tuple[bool, str]:
    """Run ``py-spy dump --pid 1`` against the current container's
    process 1 and return ``(ok, text)``.

    Returns the text of the dump on success. On failure (missing
    binary, dropped ``CAP_SYS_PTRACE``, subprocess timeout) returns
    ``(False, "<human-readable explanation>")`` — never raises. The
    UI surfaces the returned string verbatim either way so operators
    get a useful error instead of a 500.
    """
    binary = _py_spy_binary()
    if binary is None:
        return False, (
            "py-spy is not installed on this host. It should be bundled in\n"
            "ESPHome Fleet's Docker images since 1.6.2; if you're seeing\n"
            "this message, verify you're running the current image with\n"
            "`docker pull ghcr.io/weirded/esphome-dist-server:latest`."
        )
    cmd = [binary, "dump", "--pid", "1"]
    logger.info("diagnostics: running %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=PY_SPY_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, (
            f"py-spy dump exceeded {int(PY_SPY_TIMEOUT)} s wall-clock. The\n"
            "target process is likely deadlocked at the kernel boundary or\n"
            "spawning subprocesses faster than py-spy can walk frames."
        )
    except OSError as exc:
        return False, f"py-spy failed to launch: {exc}"

    if proc.returncode != 0:
        # py-spy prints the reason ("Permission Denied", "It looks like
        # you are running in a docker container...", etc.) to stderr
        # and exits non-zero. Hand that back verbatim — it's already
        # aimed at humans.
        stderr = (proc.stderr or "").strip()
        if "Permission Denied" in stderr or "SYS_PTRACE" in stderr:
            return False, (
                "py-spy was denied ptrace access by the container runtime.\n"
                "This is the expected result when running inside a Home\n"
                "Assistant add-on (Supervisor drops CAP_SYS_PTRACE). Use\n"
                "scripts/threaddump-addon.sh from the repo to capture a\n"
                "dump via a throwaway sidecar container instead.\n"
                "\n"
                f"py-spy stderr:\n{stderr}"
            )
        return False, f"py-spy exited with code {proc.returncode}:\n{stderr or '(no stderr)'}"

    return True, proc.stdout


async def run_self_thread_dump_async() -> tuple[bool, str]:
    """Asyncio-friendly wrapper around :func:`run_self_thread_dump` —
    runs the subprocess off the event loop so a slow dump doesn't
    block every other UI request."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, run_self_thread_dump)
