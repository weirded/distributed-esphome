"""Unit tests for JobQueue — state machine, persistence, timeouts."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Make server code importable
sys.path.insert(0, str(Path(__file__).parent.parent / "ha-addon" / "server"))

from job_queue import Job, JobQueue, JobState  # noqa: E402  (after sys.path manipulation)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow():
    return datetime.now(timezone.utc)


def run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


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

def test_enqueue_returns_job(queue):
    job = run(_enqueue(queue, "device1.yaml"))
    assert job is not None
    assert job.target == "device1.yaml"
    assert job.state == JobState.PENDING


def test_enqueue_multiple_targets_fifo(queue):
    """Jobs for different targets are queued in insertion order."""
    run(_enqueue(queue, "device1.yaml"))
    run(_enqueue(queue, "device2.yaml"))

    j1 = run(queue.claim_next("client-A"))
    j2 = run(queue.claim_next("client-B"))

    assert j1.target == "device1.yaml"
    assert j2.target == "device2.yaml"


def test_deduplication_same_target(queue):
    """A second enqueue for the same target while one is active returns None."""
    j1 = run(_enqueue(queue, "device1.yaml"))
    j2 = run(_enqueue(queue, "device1.yaml"))

    assert j1 is not None
    assert j2 is None  # duplicate rejected


def test_deduplication_after_finish(queue):
    """A new job for the same target is allowed after the previous one finishes."""
    run(_enqueue(queue, "device1.yaml"))
    job = run(queue.claim_next("client-A"))
    run(queue.submit_result(job.id, "success", log="ok"))

    # Now we can enqueue again
    j2 = run(_enqueue(queue, "device1.yaml"))
    assert j2 is not None


# ---------------------------------------------------------------------------
# Job lifecycle transitions
# ---------------------------------------------------------------------------

def test_claim_transitions_to_working(queue):
    run(_enqueue(queue, "device1.yaml"))
    job = run(queue.claim_next("client-A"))
    assert job.state == JobState.WORKING
    assert job.assigned_client_id == "client-A"
    assert job.assigned_at is not None


def test_submit_result_success(queue):
    run(_enqueue(queue, "device1.yaml"))
    job = run(queue.claim_next("client-A"))
    run(queue.submit_result(job.id, "success", log="built ok", ota_result="success"))

    stored = queue.get(job.id)
    assert stored.state == JobState.SUCCESS
    assert stored.log == "built ok"
    assert stored.ota_result == "success"
    assert stored.finished_at is not None


def test_submit_result_failed(queue):
    run(_enqueue(queue, "device1.yaml"))
    job = run(queue.claim_next("client-A"))
    run(queue.submit_result(job.id, "failed", log="compile error"))

    stored = queue.get(job.id)
    assert stored.state == JobState.FAILED


def test_no_job_when_queue_empty(queue):
    result = run(queue.claim_next("client-A"))
    assert result is None


# ---------------------------------------------------------------------------
# Atomicity: concurrent claims
# ---------------------------------------------------------------------------

def test_concurrent_claims_atomic():
    """Two coroutines racing to claim the same job: only one should win."""

    async def _run():
        q = JobQueue(queue_file=Path("/tmp/test_atomic_queue.json"))
        await q.enqueue("device.yaml", "2024.3.1", "run1", 300)

        results = await asyncio.gather(
            q.claim_next("client-A"),
            q.claim_next("client-B"),
        )
        claimed = [r for r in results if r is not None]
        assert len(claimed) == 1, f"Expected exactly 1 claim, got {len(claimed)}"
        # Cleanup
        Path("/tmp/test_atomic_queue.json").unlink(missing_ok=True)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

def test_cancel_pending_job(queue):
    job = run(_enqueue(queue, "device1.yaml"))
    n = run(queue.cancel([job.id]))
    assert n == 1
    assert queue.get(job.id).state == JobState.FAILED


def test_cancel_working_job(queue):
    run(_enqueue(queue, "device1.yaml"))
    job = run(queue.claim_next("client-A"))
    assert job.state == JobState.WORKING
    n = run(queue.cancel([job.id]))
    assert n == 1
    assert queue.get(job.id).state == JobState.FAILED


def test_cancel_already_finished_job(queue):
    run(_enqueue(queue, "device1.yaml"))
    job = run(queue.claim_next("client-A"))
    run(queue.submit_result(job.id, "success"))
    n = run(queue.cancel([job.id]))
    assert n == 0  # already terminal


def test_cancel_multiple_jobs(queue):
    j1 = run(_enqueue(queue, "device1.yaml"))
    j2 = run(_enqueue(queue, "device2.yaml"))
    n = run(queue.cancel([j1.id, j2.id]))
    assert n == 2


# ---------------------------------------------------------------------------
# Timeout and retry
# ---------------------------------------------------------------------------

def _make_queue_with_old_job(tmp_queue_file) -> tuple[JobQueue, str]:
    """Create a queue with a job that was assigned far in the past."""
    q = JobQueue(queue_file=tmp_queue_file)
    asyncio.run(q.enqueue("device.yaml", "2024.3.1", "run1", timeout_seconds=1))
    claimed = asyncio.run(q.claim_next("client-A"))
    # Backdate assigned_at so it's timed out
    claimed.assigned_at = _utcnow() - timedelta(seconds=10)
    return q, claimed.id


def test_check_timeouts_requeues_job(tmp_queue_file):
    q, job_id = _make_queue_with_old_job(tmp_queue_file)
    affected = run(q.check_timeouts())
    assert len(affected) == 1
    stored = q.get(job_id)
    assert stored.state == JobState.PENDING
    assert stored.retry_count == 1
    assert stored.assigned_client_id is None


def test_check_timeouts_max_retries(tmp_queue_file):
    q, job_id = _make_queue_with_old_job(tmp_queue_file)

    # Simulate 3 consecutive timeouts
    for i in range(3):
        run(q.check_timeouts())
        job = q.get(job_id)
        if job.state == JobState.FAILED:
            break
        # Re-assign and backdate again
        claimed = run(q.claim_next("client-X"))
        if claimed:
            claimed.assigned_at = _utcnow() - timedelta(seconds=10)

    stored = q.get(job_id)
    assert stored.state == JobState.FAILED
    assert stored.retry_count >= 3


def test_check_timeouts_no_false_positives(tmp_queue_file):
    """A recently-assigned job should NOT be timed out."""
    q = JobQueue(queue_file=tmp_queue_file)
    run(q.enqueue("device.yaml", "2024.3.1", "run1", timeout_seconds=9999))
    run(q.claim_next("client-A"))
    affected = run(q.check_timeouts())
    assert len(affected) == 0


# ---------------------------------------------------------------------------
# Persistence / restart recovery
# ---------------------------------------------------------------------------

def test_persistence_pending_jobs_reload(tmp_queue_file):
    q1 = JobQueue(queue_file=tmp_queue_file)
    run(_enqueue(q1, "device1.yaml"))
    run(_enqueue(q1, "device2.yaml"))

    # Simulate restart
    q2 = JobQueue(queue_file=tmp_queue_file)
    q2.load()

    jobs = q2.get_all()
    assert len(jobs) == 2
    assert all(j.state == JobState.PENDING for j in jobs)


def test_persistence_working_resets_to_pending(tmp_queue_file):
    q1 = JobQueue(queue_file=tmp_queue_file)
    run(_enqueue(q1, "device1.yaml"))
    job = run(q1.claim_next("client-A"))
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
    import json
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


def test_persistence_success_retained(tmp_queue_file):
    q1 = JobQueue(queue_file=tmp_queue_file)
    run(_enqueue(q1, "device1.yaml"))
    job = run(q1.claim_next("client-A"))
    run(q1.submit_result(job.id, "success", log="ok"))

    q2 = JobQueue(queue_file=tmp_queue_file)
    q2.load()

    jobs = q2.get_all()
    assert len(jobs) == 1
    assert jobs[0].state == JobState.SUCCESS


def test_persistence_failed_retained(tmp_queue_file):
    q1 = JobQueue(queue_file=tmp_queue_file)
    run(_enqueue(q1, "device1.yaml"))
    job = run(q1.claim_next("client-A"))
    run(q1.submit_result(job.id, "failed", log="error"))

    q2 = JobQueue(queue_file=tmp_queue_file)
    q2.load()

    jobs = q2.get_all()
    assert jobs[0].state == JobState.FAILED


def test_persistence_atomic_write(tmp_queue_file):
    """The queue file should be valid JSON after every enqueue."""
    q = JobQueue(queue_file=tmp_queue_file)
    for i in range(5):
        run(_enqueue(q, f"device{i}.yaml"))

    data = json.loads(tmp_queue_file.read_text())
    assert isinstance(data, list)
    assert len(data) == 5


# ---------------------------------------------------------------------------
# Queue size
# ---------------------------------------------------------------------------

def test_queue_size(queue):
    assert queue.queue_size() == 0
    run(_enqueue(queue, "d1.yaml"))
    run(_enqueue(queue, "d2.yaml"))
    assert queue.queue_size() == 2

    job = run(queue.claim_next("client-A"))
    run(queue.submit_result(job.id, "success"))
    assert queue.queue_size() == 1


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------

def test_retry_failed_job_creates_pending(queue):
    job = run(_enqueue(queue, "device1.yaml"))
    claimed = run(queue.claim_next("client-A"))
    run(queue.submit_result(claimed.id, "failed", log="error"))

    new_jobs = run(queue.retry([claimed.id], "2024.3.1", "run2", 300))
    assert len(new_jobs) == 1
    assert new_jobs[0].state == JobState.PENDING
    assert new_jobs[0].target == "device1.yaml"
    assert new_jobs[0].id != claimed.id  # new job, new id


def test_retry_timed_out_job_creates_pending(tmp_queue_file):
    q, job_id = _make_queue_with_old_job(tmp_queue_file)
    run(q.check_timeouts())  # transitions to TIMED_OUT or PENDING after retry=0

    job = q.get(job_id)
    # After first timeout the job is back to PENDING with retry_count=1;
    # force it to TIMED_OUT by exhausting retries
    for _ in range(3):
        timed_out = q.get(job_id)
        if timed_out.state == JobState.FAILED:
            break
        claimed = run(q.claim_next("x"))
        if claimed:
            claimed.assigned_at = _utcnow() - timedelta(seconds=10)
        run(q.check_timeouts())

    # Now retry via the retry() method
    timed_out_job = next(
        (j for j in q.get_all() if j.state in (JobState.FAILED, JobState.TIMED_OUT)),
        None,
    )
    if timed_out_job:
        new_jobs = run(q.retry([timed_out_job.id], "2024.3.1", "run2", 300))
        assert len(new_jobs) == 1
        assert new_jobs[0].state == JobState.PENDING


def test_retry_ignores_non_terminal_jobs(queue):
    job = run(_enqueue(queue, "device1.yaml"))
    run(queue.claim_next("client-A"))  # now WORKING

    new_jobs = run(queue.retry([job.id], "2024.3.1", "run2", 300))
    assert new_jobs == []  # WORKING job is not retryable


def test_retry_success_jobs(queue):
    """Success jobs can be individually retried (e.g. config changed after build)."""
    job = run(_enqueue(queue, "device1.yaml"))
    claimed = run(queue.claim_next("client-A"))
    run(queue.submit_result(claimed.id, "success"))

    new_jobs = run(queue.retry([claimed.id], "2024.3.1", "run2", 300))
    assert len(new_jobs) == 1
    assert new_jobs[0].target == "device1.yaml"
    assert new_jobs[0].state.value == "pending"


def test_retry_multiple_jobs(queue):
    j1 = run(_enqueue(queue, "d1.yaml"))
    j2 = run(_enqueue(queue, "d2.yaml"))
    c1 = run(queue.claim_next("A"))
    c2 = run(queue.claim_next("B"))
    run(queue.submit_result(c1.id, "failed"))
    run(queue.submit_result(c2.id, "failed"))

    new_jobs = run(queue.retry([c1.id, c2.id], "2024.3.1", "run2", 300))
    assert len(new_jobs) == 2
    targets = {j.target for j in new_jobs}
    assert targets == {"d1.yaml", "d2.yaml"}
