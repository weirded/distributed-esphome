"""Unit coverage for ha-addon/server/diagnostics.py (#109)."""

from __future__ import annotations

import subprocess
import time
from unittest.mock import patch

import pytest

import diagnostics


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


def test_run_self_thread_dump_missing_binary() -> None:
    with patch.object(diagnostics, "_py_spy_binary", return_value=None):
        ok, text = diagnostics.run_self_thread_dump()
    assert ok is False
    assert "py-spy is not installed" in text


def test_run_self_thread_dump_permission_denied() -> None:
    """py-spy exits non-zero with 'Permission Denied' when SYS_PTRACE
    is dropped (HA add-on context). The helper must surface that as a
    human-readable hint pointing at the sidecar script, not as a raw
    subprocess error."""
    fake_proc = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="",
        stderr="Error: Permission Denied\nIt looks like you are running in a docker container.",
    )
    with patch.object(diagnostics, "_py_spy_binary", return_value="/fake/py-spy"), \
         patch("subprocess.run", return_value=fake_proc):
        ok, text = diagnostics.run_self_thread_dump()
    assert ok is False
    assert "ptrace access" in text
    assert "threaddump-addon.sh" in text


def test_run_self_thread_dump_success() -> None:
    fake_proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="Thread 1 (idle): MainThread\n", stderr="",
    )
    with patch.object(diagnostics, "_py_spy_binary", return_value="/fake/py-spy"), \
         patch("subprocess.run", return_value=fake_proc):
        ok, text = diagnostics.run_self_thread_dump()
    assert ok is True
    assert "MainThread" in text


def test_run_self_thread_dump_timeout() -> None:
    def _raise(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="py-spy", timeout=20.0)
    with patch.object(diagnostics, "_py_spy_binary", return_value="/fake/py-spy"), \
         patch("subprocess.run", side_effect=_raise):
        ok, text = diagnostics.run_self_thread_dump()
    assert ok is False
    assert "timeout" in text.lower() or "wall-clock" in text.lower()


@pytest.mark.asyncio
async def test_run_self_thread_dump_async_delegates_to_sync() -> None:
    with patch.object(diagnostics, "run_self_thread_dump", return_value=(True, "sync-dump")) as m:
        ok, text = await diagnostics.run_self_thread_dump_async()
    assert m.called
    assert ok is True
    assert text == "sync-dump"
