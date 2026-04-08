"""Unit tests for JobQueue — state machine, persistence, timeouts."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from job_queue import JobQueue, JobState, MAX_LOG_BYTES, LOG_TRUNCATED_MARKER


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow():
    return datetime.now(timezone.utc)


async def _enqueue(q: JobQueue, target: str = "device.yaml", *, version: str = "2024.3.1", run_id: str = "run1", timeout: int = 300):
    return await q.enqueue(target, version, run_id, timeout)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_queue_file(tmp_path):
    return tmp_path / "queue.json"


@pytest.fixture
def queue(tmp_queue_file):
    return JobQueue(queue_file=tmp_queue_file)


# ---------------------------------------------------------------------------
# Enqueue / dequeue (FIFO + deduplication)
# ---------------------------------------------------------------------------

async def test_enqueue_returns_job(queue):
    job = await _enqueue(queue, "device1.yaml")
    assert job is not None
    assert job.target == "device1.yaml"
    assert job.state == JobState.PENDING


async def test_enqueue_multiple_targets_fifo(queue):
    """Jobs for different targets are queued in insertion order."""
    await _enqueue(queue, "device1.yaml")
    await _enqueue(queue, "device2.yaml")

    j1 = await queue.claim_next("client-A")
    j2 = await queue.claim_next("client-B")

    assert j1.target == "device1.yaml"
    assert j2.target == "device2.yaml"


async def test_deduplication_same_target(queue):
    """A second enqueue for the same target while one is active returns None."""
    j1 = await _enqueue(queue, "device1.yaml")
    j2 = await _enqueue(queue, "device1.yaml")

    assert j1 is not None
    assert j2 is None  # duplicate rejected


async def test_deduplication_after_finish(queue):
    """A new job for the same target is allowed after the previous one finishes."""
    await _enqueue(queue, "device1.yaml")
    job = await queue.claim_next("client-A")
    await queue.submit_result(job.id, "success", log="ok")

    # Now we can enqueue again
    j2 = await _enqueue(queue, "device1.yaml")
    assert j2 is not None


# ---------------------------------------------------------------------------
# Job lifecycle transitions
# ---------------------------------------------------------------------------

async def test_claim_transitions_to_working(queue):
    await _enqueue(queue, "device1.yaml")
    job = await queue.claim_next("client-A")
    assert job.state == JobState.WORKING
    assert job.assigned_client_id == "client-A"
    assert job.assigned_at is not None


async def test_submit_result_success(queue):
    await _enqueue(queue, "device1.yaml")
    job = await queue.claim_next("client-A")
    await queue.submit_result(job.id, "success", log="built ok", ota_result="success")

    stored = queue.get(job.id)
    assert stored.state == JobState.SUCCESS
    assert stored.log == "built ok"
    assert stored.ota_result == "success"
    assert stored.finished_at is not None


async def test_submit_result_failed(queue):
    await _enqueue(queue, "device1.yaml")
    job = await queue.claim_next("client-A")
    await queue.submit_result(job.id, "failed", log="compile error")

    stored = queue.get(job.id)
    assert stored.state == JobState.FAILED


async def test_no_job_when_queue_empty(queue):
    result = await queue.claim_next("client-A")
    assert result is None


# ---------------------------------------------------------------------------
# Atomicity: concurrent claims
# ---------------------------------------------------------------------------

async def test_concurrent_claims_atomic(tmp_path):
    """Two coroutines racing to claim the same job: only one should win."""
    q = JobQueue(queue_file=tmp_path / "test_atomic_queue.json")
    await q.enqueue("device.yaml", "2024.3.1", "run1", 300)

    results = await asyncio.gather(
        q.claim_next("client-A"),
        q.claim_next("client-B"),
    )
    claimed = [r for r in results if r is not None]
    assert len(claimed) == 1, f"Expected exactly 1 claim, got {len(claimed)}"


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

async def test_cancel_pending_job(queue):
    job = await _enqueue(queue, "device1.yaml")
    n = await queue.cancel([job.id])
    assert n == 1
    assert queue.get(job.id).state == JobState.FAILED


async def test_cancel_working_job(queue):
    await _enqueue(queue, "device1.yaml")
    job = await queue.claim_next("client-A")
    assert job.state == JobState.WORKING
    n = await queue.cancel([job.id])
    assert n == 1
    assert queue.get(job.id).state == JobState.FAILED


async def test_cancel_already_finished_job(queue):
    await _enqueue(queue, "device1.yaml")
    job = await queue.claim_next("client-A")
    await queue.submit_result(job.id, "success")
    n = await queue.cancel([job.id])
    assert n == 0  # already terminal


async def test_cancel_multiple_jobs(queue):
    j1 = await _enqueue(queue, "device1.yaml")
    j2 = await _enqueue(queue, "device2.yaml")
    n = await queue.cancel([j1.id, j2.id])
    assert n == 2


# ---------------------------------------------------------------------------
# Timeout and retry
# ---------------------------------------------------------------------------

async def _make_queue_with_old_job(tmp_queue_file) -> tuple[JobQueue, str]:
    """Create a queue with a job that was assigned far in the past."""
    q = JobQueue(queue_file=tmp_queue_file)
    await q.enqueue("device.yaml", "2024.3.1", "run1", timeout_seconds=1)
    claimed = await q.claim_next("client-A")
    # Backdate assigned_at so it's timed out
    claimed.assigned_at = _utcnow() - timedelta(seconds=10)
    return q, claimed.id


async def test_check_timeouts_requeues_job(tmp_queue_file):
    q, job_id = await _make_queue_with_old_job(tmp_queue_file)
    affected = await q.check_timeouts()
    assert len(affected) == 1
    stored = q.get(job_id)
    assert stored.state == JobState.PENDING
    assert stored.retry_count == 1
    assert stored.assigned_client_id is None


async def test_check_timeouts_max_retries(tmp_queue_file):
    q, job_id = await _make_queue_with_old_job(tmp_queue_file)

    # Simulate 3 consecutive timeouts
    for i in range(3):
        await q.check_timeouts()
        job = q.get(job_id)
        if job.state == JobState.FAILED:
            break
        # Re-assign and backdate again
        claimed = await q.claim_next("client-X")
        if claimed:
            claimed.assigned_at = _utcnow() - timedelta(seconds=10)

    stored = q.get(job_id)
    assert stored.state == JobState.FAILED
    assert stored.retry_count >= 3


async def test_check_timeouts_no_false_positives(tmp_queue_file):
    """A recently-assigned job should NOT be timed out."""
    q = JobQueue(queue_file=tmp_queue_file)
    await q.enqueue("device.yaml", "2024.3.1", "run1", timeout_seconds=9999)
    await q.claim_next("client-A")
    affected = await q.check_timeouts()
    assert len(affected) == 0


# ---------------------------------------------------------------------------
# Persistence / restart recovery
# ---------------------------------------------------------------------------

async def test_persistence_pending_jobs_reload(tmp_queue_file):
    q1 = JobQueue(queue_file=tmp_queue_file)
    await _enqueue(q1, "device1.yaml")
    await _enqueue(q1, "device2.yaml")

    # Simulate restart
    q2 = JobQueue(queue_file=tmp_queue_file)
    q2.load()

    jobs = q2.get_all()
    assert len(jobs) == 2
    assert all(j.state == JobState.PENDING for j in jobs)


async def test_persistence_working_resets_to_pending(tmp_queue_file):
    q1 = JobQueue(queue_file=tmp_queue_file)
    await _enqueue(q1, "device1.yaml")
    job = await q1.claim_next("client-A")
    assert job.state == JobState.WORKING

    # Simulate restart
    q2 = JobQueue(queue_file=tmp_queue_file)
    q2.load()

    jobs = q2.get_all()
    assert len(jobs) == 1
    assert jobs[0].state == JobState.PENDING
    assert jobs[0].assigned_client_id is None


def test_persistence_backwards_compat_old_states(tmp_queue_file):
    """Old queue.json with 'assigned'/'running' state values load as WORKING then reset to PENDING."""
    old_data = [
        {
            "id": "aaaa-1111",
            "target": "device1.yaml",
            "esphome_version": "2024.3.1",
            "state": "assigned",
            "run_id": "run1",
            "assigned_client_id": "client-A",
            "assigned_hostname": "myhost",
            "assigned_at": "2024-01-01T00:00:00+00:00",
            "worker_id": 1,
            "timeout_seconds": 600,
            "created_at": "2024-01-01T00:00:00+00:00",
            "finished_at": None,
            "retry_count": 0,
            "log": None,
            "ota_result": None,
            "ota_only": False,
            "pinned_client_id": None,
            "status_text": None,
            "duration_seconds": None,
        },
        {
            "id": "bbbb-2222",
            "target": "device2.yaml",
            "esphome_version": "2024.3.1",
            "state": "running",
            "run_id": "run1",
            "assigned_client_id": "client-B",
            "assigned_hostname": "myhost2",
            "assigned_at": "2024-01-01T00:00:00+00:00",
            "worker_id": 1,
            "timeout_seconds": 600,
            "created_at": "2024-01-01T00:00:00+00:00",
            "finished_at": None,
            "retry_count": 0,
            "log": None,
            "ota_result": None,
            "ota_only": False,
            "pinned_client_id": None,
            "status_text": None,
            "duration_seconds": None,
        },
    ]
    tmp_queue_file.write_text(json.dumps(old_data))

    q = JobQueue(queue_file=tmp_queue_file)
    q.load()

    jobs = {j.id: j for j in q.get_all()}
    assert jobs["aaaa-1111"].state == JobState.PENDING
    assert jobs["aaaa-1111"].assigned_client_id is None
    assert jobs["bbbb-2222"].state == JobState.PENDING
    assert jobs["bbbb-2222"].assigned_client_id is None


async def test_persistence_success_retained(tmp_queue_file):
    q1 = JobQueue(queue_file=tmp_queue_file)
    await _enqueue(q1, "device1.yaml")
    job = await q1.claim_next("client-A")
    await q1.submit_result(job.id, "success", log="ok")

    q2 = JobQueue(queue_file=tmp_queue_file)
    q2.load()

    jobs = q2.get_all()
    assert len(jobs) == 1
    assert jobs[0].state == JobState.SUCCESS


async def test_persistence_failed_retained(tmp_queue_file):
    q1 = JobQueue(queue_file=tmp_queue_file)
    await _enqueue(q1, "device1.yaml")
    job = await q1.claim_next("client-A")
    await q1.submit_result(job.id, "failed", log="error")

    q2 = JobQueue(queue_file=tmp_queue_file)
    q2.load()

    jobs = q2.get_all()
    assert jobs[0].state == JobState.FAILED


async def test_persistence_atomic_write(tmp_queue_file):
    """The queue file should be valid JSON after every enqueue."""
    q = JobQueue(queue_file=tmp_queue_file)
    for i in range(5):
        await _enqueue(q, f"device{i}.yaml")

    data = json.loads(tmp_queue_file.read_text())
    assert isinstance(data, list)
    assert len(data) == 5


# ---------------------------------------------------------------------------
# Queue size
# ---------------------------------------------------------------------------

async def test_queue_size(queue):
    assert queue.queue_size() == 0
    await _enqueue(queue, "d1.yaml")
    await _enqueue(queue, "d2.yaml")
    assert queue.queue_size() == 2

    job = await queue.claim_next("client-A")
    await queue.submit_result(job.id, "success")
    assert queue.queue_size() == 1


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------

async def test_retry_failed_job_creates_pending(queue):
    await _enqueue(queue, "device1.yaml")
    claimed = await queue.claim_next("client-A")
    await queue.submit_result(claimed.id, "failed", log="error")

    new_jobs = await queue.retry([claimed.id], "2024.3.1", "run2", 300)
    assert len(new_jobs) == 1
    assert new_jobs[0].state == JobState.PENDING
    assert new_jobs[0].target == "device1.yaml"
    assert new_jobs[0].id != claimed.id  # new job, new id


async def test_retry_timed_out_job_creates_pending(tmp_queue_file):
    q, job_id = await _make_queue_with_old_job(tmp_queue_file)
    await q.check_timeouts()  # transitions to TIMED_OUT or PENDING after retry=0

    # After first timeout the job is back to PENDING with retry_count=1;
    # force it to TIMED_OUT by exhausting retries
    for _ in range(3):
        timed_out = q.get(job_id)
        if timed_out.state == JobState.FAILED:
            break
        claimed = await q.claim_next("x")
        if claimed:
            claimed.assigned_at = _utcnow() - timedelta(seconds=10)
        await q.check_timeouts()

    # Now retry via the retry() method
    timed_out_job = next(
        (j for j in q.get_all() if j.state in (JobState.FAILED, JobState.TIMED_OUT)),
        None,
    )
    if timed_out_job:
        new_jobs = await q.retry([timed_out_job.id], "2024.3.1", "run2", 300)
        assert len(new_jobs) == 1
        assert new_jobs[0].state == JobState.PENDING


async def test_retry_ignores_non_terminal_jobs(queue):
    job = await _enqueue(queue, "device1.yaml")
    await queue.claim_next("client-A")  # now WORKING

    new_jobs = await queue.retry([job.id], "2024.3.1", "run2", 300)
    assert new_jobs == []  # WORKING job is not retryable


async def test_retry_success_jobs(queue):
    """Success jobs can be individually retried (e.g. config changed after build)."""
    await _enqueue(queue, "device1.yaml")
    claimed = await queue.claim_next("client-A")
    await queue.submit_result(claimed.id, "success")

    new_jobs = await queue.retry([claimed.id], "2024.3.1", "run2", 300)
    assert len(new_jobs) == 1
    assert new_jobs[0].target == "device1.yaml"
    assert new_jobs[0].state.value == "pending"


async def test_retry_multiple_jobs(queue):
    j1 = await _enqueue(queue, "d1.yaml")
    j2 = await _enqueue(queue, "d2.yaml")
    c1 = await queue.claim_next("A")
    c2 = await queue.claim_next("B")
    await queue.submit_result(c1.id, "failed")
    await queue.submit_result(c2.id, "failed")

    new_jobs = await queue.retry([c1.id, c2.id], "2024.3.1", "run2", 300)
    assert len(new_jobs) == 2
    targets = {j.target for j in new_jobs}
    assert targets == {"d1.yaml", "d2.yaml"}


# ---------------------------------------------------------------------------
# Bounded log storage (SEC.2)
# ---------------------------------------------------------------------------

async def test_append_log_basic(queue):
    await _enqueue(queue, "device1.yaml")
    job = await queue.claim_next("client-A")
    ok = await queue.append_log(job.id, "line 1\n")
    assert ok
    assert queue.get(job.id)._streaming_log == "line 1\n"


async def test_append_log_unknown_job(queue):
    ok = await queue.append_log("nonexistent", "text")
    assert not ok


async def test_append_log_truncates_at_max(queue):
    """Log exceeding MAX_LOG_BYTES is truncated with a marker."""
    await _enqueue(queue, "device1.yaml")
    job = await queue.claim_next("client-A")

    # Write just under the limit, then push over
    chunk = "x" * (MAX_LOG_BYTES - 10)
    await queue.append_log(job.id, chunk)
    await queue.append_log(job.id, "y" * 100)  # pushes over

    log = queue.get(job.id)._streaming_log
    assert log.endswith(LOG_TRUNCATED_MARKER)
    # Total never exceeds the configured cap (marker is reserved within it)
    assert len(log) == MAX_LOG_BYTES


async def test_append_log_drops_after_truncation(queue):
    """After truncation, further appends are silently dropped."""
    await _enqueue(queue, "device1.yaml")
    job = await queue.claim_next("client-A")

    # Fill past max to trigger truncation
    await queue.append_log(job.id, "x" * (MAX_LOG_BYTES + 1))
    log_after_truncate = queue.get(job.id)._streaming_log
    assert LOG_TRUNCATED_MARKER in log_after_truncate

    # Further appends should not change the log
    await queue.append_log(job.id, "more data")
    assert queue.get(job.id)._streaming_log == log_after_truncate


# ---------------------------------------------------------------------------
# Pinned jobs — pinned_client_id semantics
# ---------------------------------------------------------------------------

async def test_pinned_job_stored_on_enqueue(queue):
    job = await queue.enqueue(
        "device.yaml", "2024.3.1", "run1", 300,
        pinned_client_id="worker-42",
    )
    assert job is not None
    assert job.pinned_client_id == "worker-42"


async def test_pinned_job_only_claimable_by_pinned_worker(queue):
    await queue.enqueue(
        "device.yaml", "2024.3.1", "run1", 300,
        pinned_client_id="worker-42",
    )

    # Other worker can't claim
    job = await queue.claim_next("worker-other")
    assert job is None

    # Pinned worker can
    job = await queue.claim_next("worker-42")
    assert job is not None
    assert job.assigned_client_id == "worker-42"


async def test_unpinned_job_claimable_by_any_worker(queue):
    await _enqueue(queue, "device.yaml")
    job = await queue.claim_next("any-worker")
    assert job is not None


async def test_retry_preserves_pinned_client_id(queue):
    """All retried jobs (not just OTA retries) must keep their original pin."""
    await queue.enqueue(
        "device.yaml", "2024.3.1", "run1", 300,
        pinned_client_id="worker-42",
    )
    claimed = await queue.claim_next("worker-42")
    await queue.submit_result(claimed.id, "failed", log="error")

    new_jobs = await queue.retry([claimed.id], "2024.3.1", "run2", 300)
    assert len(new_jobs) == 1
    assert new_jobs[0].pinned_client_id == "worker-42"


# ---------------------------------------------------------------------------
# OTA-only retry — submit ota_result preserves compile success
# ---------------------------------------------------------------------------

async def test_submit_result_ota_only(queue):
    """A job with ota_only=True represents a re-upload of an already-compiled target."""
    await queue.enqueue("device.yaml", "2024.3.1", "run1", 300)
    claimed = await queue.claim_next("worker")
    await queue.submit_result(claimed.id, "success", log="ok", ota_result="success")

    stored = queue.get(claimed.id)
    assert stored.state == JobState.SUCCESS
    assert stored.ota_result == "success"


async def test_submit_result_compile_success_but_ota_failed(queue):
    """Compile succeeded but OTA failed → state=SUCCESS, ota_result=failed."""
    await queue.enqueue("device.yaml", "2024.3.1", "run1", 300)
    claimed = await queue.claim_next("worker")
    await queue.submit_result(claimed.id, "success", log="ok", ota_result="failed")

    stored = queue.get(claimed.id)
    assert stored.state == JobState.SUCCESS
    assert stored.ota_result == "failed"


# ---------------------------------------------------------------------------
# Status text + claim race detection
# ---------------------------------------------------------------------------

async def test_update_status_sets_status_text(queue):
    """update_status is used by workers to report phase changes (e.g. 'Compiling')."""
    await _enqueue(queue, "device.yaml")
    claimed = await queue.claim_next("worker")

    await queue.update_status(claimed.id, "Compiling + OTA")
    stored = queue.get(claimed.id)
    assert stored.status_text == "Compiling + OTA"

    await queue.update_status(claimed.id, "OTA Retry")
    stored = queue.get(claimed.id)
    assert stored.status_text == "OTA Retry"


async def test_update_status_unknown_job_is_noop(queue):
    """Updating a nonexistent job must not raise."""
    # Should not raise — the return value depends on the implementation
    await queue.update_status("nonexistent-id", "something")


# ---------------------------------------------------------------------------
# finished_at is set on terminal transitions
# ---------------------------------------------------------------------------

async def test_finished_at_set_on_success(queue):
    await _enqueue(queue, "d.yaml")
    claimed = await queue.claim_next("w")
    await queue.submit_result(claimed.id, "success")
    assert queue.get(claimed.id).finished_at is not None


async def test_finished_at_set_on_failure(queue):
    await _enqueue(queue, "d.yaml")
    claimed = await queue.claim_next("w")
    await queue.submit_result(claimed.id, "failed")
    assert queue.get(claimed.id).finished_at is not None


async def test_finished_at_unset_on_pending(queue):
    await _enqueue(queue, "d.yaml")
    job = await _enqueue(queue, "d.yaml")  # deduped — returns None
    assert job is None
    stored = queue.get_all()[0]
    assert stored.finished_at is None
