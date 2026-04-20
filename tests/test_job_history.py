"""JH.8 — unit tests for the persistent job-history DAO + write hooks."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import job_history as jh
from job_history import JobHistoryDAO
from job_queue import Job, JobQueue, JobState


def _utc(ts_offset_sec: int = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=ts_offset_sec)


def _make_job(
    *,
    job_id: str = "job-1",
    target: str = "bedroom.yaml",
    state: JobState = JobState.SUCCESS,
    ota_result: str | None = "success",
    scheduled: bool = False,
    schedule_kind: str | None = None,
    ha_action: bool = False,
    log: str | None = "compiled ok\nOTA 10.0.0.12\n",
    config_hash: str | None = "abc123def4567890abc123def4567890abc12345",
    created_offset: int = -120,
    assigned_offset: int = -110,
    finished_offset: int = 0,
) -> Job:
    """Build a terminal Job with realistic timestamps."""
    return Job(
        id=job_id,
        target=target,
        esphome_version="2026.4.0",
        state=state,
        run_id="run-1",
        assigned_client_id="local-1",
        assigned_hostname="local",
        assigned_at=_utc(assigned_offset),
        created_at=_utc(created_offset),
        finished_at=_utc(finished_offset),
        ota_result=ota_result,
        scheduled=scheduled,
        schedule_kind=schedule_kind,
        ha_action=ha_action,
        log=log,
        config_hash=config_hash,
    )


# ---------------------------------------------------------------------------
# DAO: schema + round-trip
# ---------------------------------------------------------------------------

def test_dao_records_a_terminal_job(tmp_path: Path) -> None:
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")
    dao.init()

    assert dao.record_terminal(_make_job()) is True
    rows = dao.query()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "job-1"
    assert row["target"] == "bedroom.yaml"
    assert row["state"] == "success"
    assert row["ota_result"] == "success"
    assert row["triggered_by"] == "user"
    assert row["trigger_detail"] is None
    assert row["duration_seconds"] == pytest.approx(110.0, abs=1.0)
    assert row["config_hash"] == "abc123def4567890abc123def4567890abc12345"
    # Log excerpt stored, not full log (short logs keep their full content).
    assert row["log_excerpt"] == "compiled ok\nOTA 10.0.0.12\n"


def test_dao_rejects_non_terminal_jobs(tmp_path: Path) -> None:
    """Non-terminal jobs must not be recorded — they'd pollute stats."""
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")
    pending = _make_job(job_id="pending-1", state=JobState.PENDING, ota_result=None)
    assert dao.record_terminal(pending) is False
    assert dao.query() == []


def test_dao_is_idempotent_on_duplicate_id(tmp_path: Path) -> None:
    """Second call upserts, keeping id unique — no double-count in stats."""
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")
    dao.record_terminal(_make_job())
    # Same id, different ota_result — simulates the OTA-patch path in
    # submit_result that updates the record after a successful OTA.
    dao.record_terminal(_make_job(ota_result="failed"))
    rows = dao.query()
    assert len(rows) == 1
    assert rows[0]["ota_result"] == "failed"


def test_dao_classifies_trigger_source(tmp_path: Path) -> None:
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")
    dao.record_terminal(_make_job(job_id="a", scheduled=True, schedule_kind="recurring"))
    dao.record_terminal(_make_job(job_id="b", ha_action=True, target="lr.yaml"))
    dao.record_terminal(_make_job(job_id="c"))

    rows = {r["id"]: r for r in dao.query()}
    assert rows["a"]["triggered_by"] == "schedule"
    assert rows["a"]["trigger_detail"] == "recurring"
    assert rows["b"]["triggered_by"] == "ha_action"
    assert rows["c"]["triggered_by"] == "user"


def test_dao_query_filters_by_target_and_state(tmp_path: Path) -> None:
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")
    dao.record_terminal(_make_job(job_id="1", target="a.yaml", state=JobState.SUCCESS))
    dao.record_terminal(_make_job(job_id="2", target="a.yaml", state=JobState.FAILED, finished_offset=10))
    dao.record_terminal(_make_job(job_id="3", target="b.yaml", state=JobState.SUCCESS, finished_offset=20))

    assert [r["id"] for r in dao.query(target="a.yaml")] == ["2", "1"]  # newest first
    assert [r["id"] for r in dao.query(state="failed")] == ["2"]
    assert dao.query(state="working") == []  # non-terminal state → empty
    assert dao.query(state="not-a-state") == []  # garbage → empty


def test_dao_query_honors_limit_and_offset(tmp_path: Path) -> None:
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")
    for i in range(5):
        dao.record_terminal(_make_job(job_id=f"j{i}", finished_offset=i))

    page1 = dao.query(limit=2, offset=0)
    page2 = dao.query(limit=2, offset=2)
    assert [r["id"] for r in page1] == ["j4", "j3"]
    assert [r["id"] for r in page2] == ["j2", "j1"]


def test_dao_log_excerpt_trims_long_logs(tmp_path: Path) -> None:
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")
    big = "\n".join(f"line {i}" for i in range(10_000))
    dao.record_terminal(_make_job(log=big))
    row = dao.query()[0]
    excerpt = row["log_excerpt"]
    assert excerpt is not None
    assert len(excerpt.encode("utf-8")) <= jh.LOG_EXCERPT_BYTES
    # Tail preserved: the last recorded line survives.
    assert "line 9999" in excerpt


# ---------------------------------------------------------------------------
# Stats rollup
# ---------------------------------------------------------------------------

def test_dao_stats_rollup(tmp_path: Path) -> None:
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")

    # 3 success + 1 failed + 1 cancelled for bedroom; 1 success for living-room.
    dao.record_terminal(_make_job(job_id="s1", target="bedroom.yaml", state=JobState.SUCCESS,
                                   assigned_offset=-30, finished_offset=0))
    dao.record_terminal(_make_job(job_id="s2", target="bedroom.yaml", state=JobState.SUCCESS,
                                   assigned_offset=-40, finished_offset=0))
    dao.record_terminal(_make_job(job_id="s3", target="bedroom.yaml", state=JobState.SUCCESS,
                                   assigned_offset=-50, finished_offset=0))
    dao.record_terminal(_make_job(job_id="f1", target="bedroom.yaml", state=JobState.FAILED,
                                   assigned_offset=-60, finished_offset=5))
    dao.record_terminal(_make_job(job_id="c1", target="bedroom.yaml", state=JobState.CANCELLED,
                                   assigned_offset=-70, finished_offset=10))
    dao.record_terminal(_make_job(job_id="lr1", target="living-room.yaml", state=JobState.SUCCESS,
                                   assigned_offset=-20, finished_offset=0))

    stats = dao.stats(target="bedroom.yaml")
    assert stats["total"] == 5
    assert stats["success"] == 3
    assert stats["failed"] == 1
    assert stats["cancelled"] == 1
    assert stats["timed_out"] == 0
    assert stats["avg_duration_seconds"] == pytest.approx(50.0, abs=5.0)
    assert stats["p95_duration_seconds"] is not None
    assert stats["last_success_at"] is not None
    assert stats["last_failure_at"] is not None

    # Fleet-wide: 6 jobs total.
    fleet = dao.stats(target=None)
    assert fleet["total"] == 6


def test_dao_stats_empty_when_no_rows(tmp_path: Path) -> None:
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")
    stats = dao.stats(target="bedroom.yaml")
    assert stats["total"] == 0
    assert stats["success"] == 0
    assert stats["avg_duration_seconds"] is None
    assert stats["last_success_at"] is None
    assert stats["last_failure_at"] is None


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def test_dao_retention_deletes_old_rows_only(tmp_path: Path) -> None:
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")
    # Write one row "now" and one "400 days ago" by manipulating finished_at.
    dao.record_terminal(_make_job(job_id="recent"))
    dao.record_terminal(_make_job(job_id="ancient", finished_offset=-400 * 86400))

    # Retention window of 365 days: only the ancient one is past cutoff.
    deleted = dao.evict_older_than(365)
    assert deleted == 1
    remaining = [r["id"] for r in dao.query()]
    assert remaining == ["recent"]


def test_dao_retention_noop_when_days_non_positive(tmp_path: Path) -> None:
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")
    dao.record_terminal(_make_job(finished_offset=-10 * 86400))
    # 0 and negatives are treated as "unlimited retention".
    assert dao.evict_older_than(0) == 0
    assert dao.evict_older_than(-7) == 0
    assert len(dao.query()) == 1


# ---------------------------------------------------------------------------
# JobQueue hook
# ---------------------------------------------------------------------------

async def test_jobqueue_submit_result_records_terminal(tmp_path: Path) -> None:
    """Terminal transition via submit_result drops a history row."""
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")
    q = JobQueue(queue_file=tmp_path / "queue.json", history=dao)

    # Enqueue + claim so the job is WORKING.
    job = await q.enqueue(
        target="bedroom.yaml",
        esphome_version="2026.4.0",
        run_id="r1",
        timeout_seconds=60,
    )
    assert job is not None
    claimed = await q.claim_next(client_id="c1", hostname="w1")
    assert claimed is not None

    # Success path.
    ok = await q.submit_result(claimed.id, status="success", log="done\n")
    assert ok is True

    rows = dao.query(target="bedroom.yaml")
    assert len(rows) == 1
    assert rows[0]["state"] == "success"
    assert rows[0]["assigned_hostname"] == "w1"


async def test_jobqueue_ota_patch_updates_history(tmp_path: Path) -> None:
    """OTA result patch on an already-terminal job must update the row."""
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")
    q = JobQueue(queue_file=tmp_path / "queue.json", history=dao)

    job = await q.enqueue(target="a.yaml", esphome_version="2026.4.0",
                          run_id="r1", timeout_seconds=60)
    assert job is not None
    claimed = await q.claim_next(client_id="c1", hostname="w1")
    assert claimed is not None
    await q.submit_result(claimed.id, status="success", log="compile ok\n")
    first = dao.query()[0]
    assert first["ota_result"] is None

    # Worker POSTs the OTA result (second submit_result call).
    await q.submit_result(claimed.id, status="success", ota_result="failed")
    updated = dao.query()[0]
    assert updated["ota_result"] == "failed"
    # Same id (upsert) so still only one row.
    assert len(dao.query()) == 1


async def test_jobqueue_cancel_records_terminal(tmp_path: Path) -> None:
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")
    q = JobQueue(queue_file=tmp_path / "queue.json", history=dao)
    job = await q.enqueue(target="a.yaml", esphome_version="2026.4.0",
                          run_id="r1", timeout_seconds=60)
    assert job is not None
    cancelled = await q.cancel([job.id])
    assert cancelled == 1
    rows = dao.query()
    assert len(rows) == 1
    assert rows[0]["state"] == "cancelled"


async def test_jobqueue_coalescing_snapshots_evictee(tmp_path: Path) -> None:
    """When enqueue() deletes old terminal jobs, they must first hit history."""
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")
    q = JobQueue(queue_file=tmp_path / "queue.json", history=dao)

    # One success that will be evicted by the next enqueue.
    job1 = await q.enqueue(target="a.yaml", esphome_version="2026.4.0",
                           run_id="r1", timeout_seconds=60)
    assert job1 is not None
    claimed = await q.claim_next(client_id="c1", hostname="w1")
    assert claimed is not None
    await q.submit_result(claimed.id, status="success", log="ok\n")
    assert len(dao.query()) == 1  # recorded on submit_result

    # Enqueue again — deletes the stale SUCCESS, but history should still
    # hold it (upsert semantics: re-record is idempotent).
    job2 = await q.enqueue(target="a.yaml", esphome_version="2026.4.0",
                           run_id="r2", timeout_seconds=60)
    assert job2 is not None
    assert len(dao.query()) == 1
    # The evicted job's id survives in the history table even after
    # it's gone from the live queue.
    assert dao.query()[0]["id"] == job1.id


# ---------------------------------------------------------------------------
# last_per_target rollup (used by JH.6 later)
# ---------------------------------------------------------------------------

def test_dao_last_per_target(tmp_path: Path) -> None:
    dao = JobHistoryDAO(db_path=tmp_path / "history.db")
    # Two targets, two rows each; latest should win per target.
    dao.record_terminal(_make_job(job_id="a-old", target="a.yaml", state=JobState.FAILED,
                                   finished_offset=0))
    dao.record_terminal(_make_job(job_id="a-new", target="a.yaml", state=JobState.SUCCESS,
                                   finished_offset=60))
    dao.record_terminal(_make_job(job_id="b-old", target="b.yaml", state=JobState.SUCCESS,
                                   finished_offset=0))
    dao.record_terminal(_make_job(job_id="b-new", target="b.yaml", state=JobState.FAILED,
                                   finished_offset=60))

    last = dao.last_per_target()
    assert last["a.yaml"]["id"] == "a-new"
    assert last["a.yaml"]["state"] == "success"
    assert last["b.yaml"]["id"] == "b-new"
    assert last["b.yaml"]["state"] == "failed"

    only_a = dao.last_per_target(["a.yaml"])
    assert list(only_a.keys()) == ["a.yaml"]
