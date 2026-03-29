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
    """Run a coroutine synchronously in a new event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


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

def test_claim_transitions_to_assigned(queue):
    run(_enqueue(queue, "device1.yaml"))
    job = run(queue.claim_next("client-A"))
    assert job.state == JobState.ASSIGNED
    assert job.assigned_client_id == "client-A"
    assert job.assigned_at is not None


def test_update_to_running(queue):
    run(_enqueue(queue, "device1.yaml"))
    job = run(queue.claim_next("client-A"))
    ok = run(queue.update_to_running(job.id, "client-A"))
    assert ok
    assert queue.get(job.id).state == JobState.RUNNING


def test_submit_result_success(queue):
    run(_enqueue(queue, "device1.yaml"))
    job = run(queue.claim_next("client-A"))
    run(queue.update_to_running(job.id, "client-A"))
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
        await q.enqueue("device.yaml", "2024.3.1", "run1")

        results = await asyncio.gather(
            q.claim_next("client-A"),
            q.claim_next("client-B"),
        )
        claimed = [r for r in results if r is not None]
        assert len(claimed) == 1, f"Expected exactly 1 claim, got {len(claimed)}"
        # Cleanup
        Path("/tmp/test_atomic_queue.json").unlink(missing_ok=True)

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

def test_cancel_pending_job(queue):
    job = run(_enqueue(queue, "device1.yaml"))
    n = run(queue.cancel([job.id]))
    assert n == 1
    assert queue.get(job.id).state == JobState.FAILED


def test_cancel_assigned_job(queue):
    run(_enqueue(queue, "device1.yaml"))
    job = run(queue.claim_next("client-A"))
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
    loop = asyncio.get_event_loop()
    job = loop.run_until_complete(q.enqueue("device.yaml", "2024.3.1", "run1", timeout_seconds=1))
    claimed = loop.run_until_complete(q.claim_next("client-A"))
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


def test_persistence_assigned_resets_to_pending(tmp_queue_file):
    q1 = JobQueue(queue_file=tmp_queue_file)
    run(_enqueue(q1, "device1.yaml"))
    run(q1.claim_next("client-A"))  # assigned

    # Simulate restart
    q2 = JobQueue(queue_file=tmp_queue_file)
    q2.load()

    jobs = q2.get_all()
    assert len(jobs) == 1
    assert jobs[0].state == JobState.PENDING
    assert jobs[0].assigned_client_id is None


def test_persistence_running_resets_to_pending(tmp_queue_file):
    q1 = JobQueue(queue_file=tmp_queue_file)
    run(_enqueue(q1, "device1.yaml"))
    job = run(q1.claim_next("client-A"))
    run(q1.update_to_running(job.id, "client-A"))

    # Simulate restart
    q2 = JobQueue(queue_file=tmp_queue_file)
    q2.load()

    jobs = q2.get_all()
    assert jobs[0].state == JobState.PENDING


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
