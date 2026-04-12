"""Tests for the per-device cron scheduler (SU.1–SU.6).

Tests the schedule_checker background task's core logic by writing YAML
fixtures with schedule metadata, then invoking the scheduling logic and
asserting the correct jobs are (or aren't) enqueued.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from job_queue import JobQueue
from scanner import read_device_meta, write_device_meta


def _write_scheduled_device(
    config_dir: Path,
    name: str = "test-device",
    cron: str = "0 2 * * *",
    enabled: bool = True,
    last_run: str | None = None,
    pin_version: str | None = None,
) -> str:
    """Create a YAML file with a schedule in the metadata comment block."""
    filename = f"{name}.yaml"
    path = config_dir / filename
    path.write_text(f"esphome:\n  name: {name}\n")
    meta: dict = {"schedule": cron, "schedule_enabled": enabled}
    if last_run:
        meta["schedule_last_run"] = last_run
    if pin_version:
        meta["pin_version"] = pin_version
    write_device_meta(str(config_dir), filename, meta)
    return filename


async def _run_one_schedule_tick(config_dir: Path, queue: JobQueue) -> None:
    """Import and run one iteration of the schedule_checker's inner loop.

    We can't easily run the full background task (it sleeps forever), so
    we extract the core logic by importing the function and patching the
    sleep to break after one iteration.
    """
    from main import schedule_checker  # noqa: PLC0415

    app: dict = {
        "config": MagicMock(config_dir=str(config_dir), job_timeout=600),
        "queue": queue,
    }

    # Patch asyncio.sleep to run exactly one iteration then cancel.
    call_count = {"n": 0}

    async def one_tick_sleep(_seconds: float) -> None:
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", side_effect=one_tick_sleep):
        try:
            await schedule_checker(app)
        except asyncio.CancelledError:
            pass


@pytest.fixture
def tmp_queue(tmp_path):
    q = JobQueue(queue_file=tmp_path / "queue.json")
    return q


async def test_schedule_fires_when_due(tmp_path, tmp_queue):
    """A schedule whose next tick is in the past should enqueue a job."""
    last_run = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    _write_scheduled_device(tmp_path, cron="0 2 * * *", last_run=last_run)

    await _run_one_schedule_tick(tmp_path, tmp_queue)

    jobs = tmp_queue.get_all()
    assert len(jobs) == 1
    assert jobs[0].target == "test-device.yaml"
    assert jobs[0].scheduled is True


async def test_schedule_does_not_fire_when_disabled(tmp_path, tmp_queue):
    """A disabled schedule should not enqueue anything."""
    last_run = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    _write_scheduled_device(tmp_path, cron="0 2 * * *", enabled=False, last_run=last_run)

    await _run_one_schedule_tick(tmp_path, tmp_queue)

    assert len(tmp_queue.get_all()) == 0


async def test_schedule_does_not_fire_when_not_yet_due(tmp_path, tmp_queue):
    """A schedule whose next tick is in the future should not fire."""
    # last_run = 1 minute ago, cron = daily → next_run is ~23h59m from now
    last_run = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    _write_scheduled_device(tmp_path, cron="0 2 * * *", last_run=last_run)

    await _run_one_schedule_tick(tmp_path, tmp_queue)

    assert len(tmp_queue.get_all()) == 0


async def test_schedule_respects_pinned_version(tmp_path, tmp_queue):
    """A pinned device should compile with its pinned version, not the global one."""
    last_run = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    _write_scheduled_device(
        tmp_path, cron="0 2 * * *", last_run=last_run, pin_version="2024.11.1",
    )

    with patch("scanner.get_esphome_version", return_value="2026.3.3"):
        await _run_one_schedule_tick(tmp_path, tmp_queue)

    jobs = tmp_queue.get_all()
    assert len(jobs) == 1
    assert jobs[0].esphome_version == "2024.11.1"


async def test_schedule_updates_last_run_after_firing(tmp_path, tmp_queue):
    """After a schedule fires, schedule_last_run should be updated in the YAML."""
    last_run = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    _write_scheduled_device(tmp_path, cron="0 2 * * *", last_run=last_run)

    before = datetime.now(timezone.utc)
    await _run_one_schedule_tick(tmp_path, tmp_queue)
    after = datetime.now(timezone.utc)

    meta = read_device_meta(str(tmp_path), "test-device.yaml")
    new_last_run = datetime.fromisoformat(meta["schedule_last_run"])
    assert before <= new_last_run <= after


async def test_schedule_survives_invalid_cron(tmp_path, tmp_queue):
    """An invalid cron expression should be logged and skipped, not crash."""
    last_run = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    _write_scheduled_device(tmp_path, name="bad-cron", cron="not a cron", last_run=last_run)
    # Also add a valid device to prove it still runs.
    _write_scheduled_device(tmp_path, name="good-device", cron="0 2 * * *", last_run=last_run)

    await _run_one_schedule_tick(tmp_path, tmp_queue)

    jobs = tmp_queue.get_all()
    targets = {j.target for j in jobs}
    assert "good-device.yaml" in targets
    assert "bad-cron.yaml" not in targets


async def test_schedule_first_run_waits_for_next_occurrence(tmp_path, tmp_queue):
    """#67: A schedule with no last_run should NOT fire immediately.

    It should wait until the NEXT scheduled time. The old epoch default
    (2000-01-01) caused every new schedule to fire on the first tick.
    """
    _write_scheduled_device(tmp_path, cron="0 2 * * *", last_run=None)

    await _run_one_schedule_tick(tmp_path, tmp_queue)

    jobs = tmp_queue.get_all()
    assert len(jobs) == 0, "Should not fire — 2am hasn't arrived yet"
