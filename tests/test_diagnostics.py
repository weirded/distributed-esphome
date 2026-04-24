"""Unit coverage for ha-addon/server/diagnostics.py.

Originally (#108/#109) the diagnostics self-dump shelled out to
``py-spy dump``. #189 replaced that with an in-process frame walk —
``py-spy`` can't attach inside HA add-on containers (Supervisor
drops ``CAP_SYS_PTRACE``), and the sidecar workaround is rejected
on HAOS / Supervised variants, so no py-spy path reached real users.
The in-process walk uses :func:`sys._current_frames` + friends and
works without any privileged capability.

These tests exercise the in-process helper (pure Python; no
subprocess mocking required), the broker's pending/result bookkeeping,
and the async-wrapper delegation contract.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

import diagnostics


# ---------------------------------------------------------------------------
# Broker — unchanged in #189, verify behaviour stays the same.
# ---------------------------------------------------------------------------


def test_broker_round_trip() -> None:
    broker = diagnostics.DiagnosticsBroker()
    assert broker.pending_for_worker("w1") is None
    rid = broker.request_for_worker("w1")
    assert broker.pending_for_worker("w1") == rid

    broker.store_result(rid, ok=True, dump="hello")
    broker.claim_pending("w1", rid)

    assert broker.pending_for_worker("w1") is None
    result = broker.get_result(rid)
    assert result is not None
    assert result.ok is True
    assert result.dump == "hello"


def test_broker_claim_pending_only_clears_matching_id() -> None:
    """Server must not drop a *later* request when a late upload for an
    earlier request arrives. ``claim_pending`` only clears the slot when
    the id matches — otherwise the later request stays in place."""
    broker = diagnostics.DiagnosticsBroker()
    first = broker.request_for_worker("w1")
    second = broker.request_for_worker("w1")
    assert broker.pending_for_worker("w1") == second
    broker.claim_pending("w1", first)
    assert broker.pending_for_worker("w1") == second


def test_broker_result_expiry() -> None:
    broker = diagnostics.DiagnosticsBroker()
    rid = broker.request_for_worker("w1")
    broker.store_result(rid, ok=True, dump="x")
    # Rewind the stored timestamp past TTL so _gc_expired evicts it.
    broker._results[rid].created_at = time.monotonic() - (diagnostics.RESULT_TTL + 5.0)
    assert broker.get_result(rid) is None


# ---------------------------------------------------------------------------
# in_process_thread_dump — #189 code path.
# ---------------------------------------------------------------------------


def test_in_process_thread_dump_captures_current_thread() -> None:
    """The dump contains at minimum the test-runner thread's name + a
    recognisable frame from the call site."""
    text = diagnostics.in_process_thread_dump()
    assert "ESPHome Fleet thread dump" in text
    assert "thread(s)" in text
    # Pytest's main thread is "MainThread"; the frame walk must
    # include the current test function name so downstream readers
    # can see where the walk was invoked from.
    assert "MainThread" in text
    assert "test_in_process_thread_dump_captures_current_thread" in text


def test_in_process_thread_dump_sees_named_worker_threads() -> None:
    """Spawn two named threads that park on an event and assert their
    names + the parking frame appear in the dump. This is the concrete
    proof that ``sys._current_frames`` + ``threading.enumerate`` give us
    py-spy-equivalent visibility into thread state."""
    ready = threading.Event()
    release = threading.Event()
    names = ("#189-worker-alpha", "#189-worker-beta")

    def _parked() -> None:
        ready.set()
        release.wait(timeout=5.0)

    threads = [threading.Thread(target=_parked, name=n, daemon=True) for n in names]
    for t in threads:
        t.start()
    # Wait until at least one worker has actually entered `release.wait`
    # so the frame walk catches them parked, not mid-spawn.
    assert ready.wait(timeout=5.0)
    try:
        text = diagnostics.in_process_thread_dump()
    finally:
        release.set()
        for t in threads:
            t.join(timeout=5.0)

    for n in names:
        assert n in text, f"expected {n!r} in dump, got:\n{text}"
    # The parking frame lives in threading.py's Event.wait implementation;
    # the exact filename can drift across CPython versions but
    # ``wait`` as a frame function is stable.
    assert "wait" in text


def test_run_self_thread_dump_returns_ok_with_frames() -> None:
    """The public entry point always succeeds — there's no fail path
    on the in-process walk. Assert ``ok=True`` and the output shape."""
    ok, text = diagnostics.run_self_thread_dump()
    assert ok is True
    assert text.startswith("ESPHome Fleet thread dump")
    assert "MainThread" in text


@pytest.mark.asyncio
async def test_run_self_thread_dump_async_delegates_to_sync() -> None:
    with patch.object(
        diagnostics, "run_self_thread_dump",
        return_value=(True, "sync-dump"),
    ) as m:
        ok, text = await diagnostics.run_self_thread_dump_async()
    assert m.called
    assert ok is True
    assert text == "sync-dump"
