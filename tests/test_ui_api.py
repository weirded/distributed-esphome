"""Tests for the browser-facing UI API (/ui/api/*) in ui_api.py.

UI endpoints are unauthenticated (they rely on HA Ingress trust) so the
test client doesn't need auth headers.  Uses a test-local aiohttp app
with in-memory Queue/Registry and a tmp_path config dir.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import ui_api as ui_api_module
from app_config import AppConfig
from job_queue import JobQueue, JobState
from main import auth_middleware
from registry import WorkerRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _UiApp:
    """Container for a running TestClient plus direct access to the app state."""

    def __init__(
        self,
        client: TestClient,
        cfg: AppConfig,
        queue: JobQueue,
        registry: WorkerRegistry,
        config_dir: Path,
    ) -> None:
        self.client = client
        self.cfg = cfg
        self.queue = queue
        self.registry = registry
        self.config_dir = config_dir

    async def close(self) -> None:
        await self.client.close()

    async def get(self, *args, **kwargs):
        return await self.client.get(*args, **kwargs)

    async def post(self, *args, **kwargs):
        return await self.client.post(*args, **kwargs)

    async def delete(self, *args, **kwargs):
        return await self.client.delete(*args, **kwargs)


async def _make_ui_app(tmp_path: Path) -> _UiApp:
    """Spin up a fresh isolated UI test app."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    cfg = AppConfig(token="ui-test-token", config_dir=str(config_dir))
    queue = JobQueue(queue_file=tmp_path / "queue.json")
    registry = WorkerRegistry()

    app = web.Application(middlewares=[auth_middleware])
    app["config"] = cfg
    app["queue"] = queue
    app["registry"] = registry
    app["log_subscribers"] = {}
    app["_rt"] = {
        "ha_entity_status": {},
        "ha_mac_set": set(),
        "ha_mac_to_device_id": {},
        "ha_name_to_device_id": {},
        "esphome_detected_version": None,
        "esphome_available_versions": [],
        "esphome_versions_fetched_at": 0.0,
        "schedule_checker_started_at": None,
        "schedule_checker_tick_count": 0,
        "schedule_checker_last_tick": None,
        "schedule_checker_last_error": None,
    }
    app.router.add_routes(ui_api_module.routes)

    client = TestClient(TestServer(app))
    await client.start_server()
    return _UiApp(client, cfg, queue, registry, config_dir)


def _write_config(config_dir: Path, filename: str, name: str) -> Path:
    """Write a minimal compilable ESPHome YAML config into the test config dir."""
    path = config_dir / filename
    path.write_text(f"esphome:\n  name: {name}\n\nesp8266:\n  board: d1_mini\n")
    return path


# ---------------------------------------------------------------------------
# server-info
# ---------------------------------------------------------------------------

async def test_server_info_returns_version_and_token(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        resp = await ta.get("/ui/api/server-info")
        assert resp.status == 200
        data = await resp.json()
        assert data["token"] == "ui-test-token"
        assert "addon_version" in data
        assert "min_image_version" in data
        assert data["min_image_version"] == "4"
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# targets
# ---------------------------------------------------------------------------

async def test_targets_lists_yaml_files(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "living_room.yaml", "living-room")
        _write_config(ta.config_dir, "bedroom.yaml", "bedroom")

        resp = await ta.get("/ui/api/targets")
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, list)
        filenames = {t["target"] for t in data}
        assert "living_room.yaml" in filenames
        assert "bedroom.yaml" in filenames
    finally:
        await ta.close()


async def test_targets_excludes_secrets_yaml(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "device1.yaml", "device1")
        (ta.config_dir / "secrets.yaml").write_text("wifi_password: secret")

        resp = await ta.get("/ui/api/targets")
        data = await resp.json()
        assert any(t["target"] == "device1.yaml" for t in data)
        assert not any(t["target"] == "secrets.yaml" for t in data)
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# config CRUD — get/save/delete content
# ---------------------------------------------------------------------------

async def test_get_target_content_returns_yaml(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "device1.yaml", "device1")
        resp = await ta.get("/ui/api/targets/device1.yaml/content")
        assert resp.status == 200
        data = await resp.json()
        assert "esphome:" in data["content"]
        assert "device1" in data["content"]
    finally:
        await ta.close()


async def test_get_target_content_not_found(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        resp = await ta.get("/ui/api/targets/missing.yaml/content")
        assert resp.status == 404
    finally:
        await ta.close()


async def test_get_target_content_rejects_path_traversal(tmp_path):
    """Attempting to read files outside the config dir must be refused."""
    ta = await _make_ui_app(tmp_path)
    try:
        # Encode the traversal so the URL parser doesn't strip it
        resp = await ta.get("/ui/api/targets/..%2Fsecret.txt/content")
        # Server should return 400 or 404, never 200 with the file contents
        assert resp.status in (400, 404)
    finally:
        await ta.close()


async def test_save_target_content_writes_file(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "device1.yaml", "device1")
        new_content = "esphome:\n  name: renamed\n\nesp32:\n  board: esp32dev\n"
        resp = await ta.post(
            "/ui/api/targets/device1.yaml/content",
            json={"content": new_content},
        )
        assert resp.status == 200
        assert (ta.config_dir / "device1.yaml").read_text() == new_content
    finally:
        await ta.close()


async def test_save_target_content_rejects_path_traversal(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        resp = await ta.post(
            "/ui/api/targets/..%2Fevil.yaml/content",
            json={"content": "pwned"},
        )
        assert resp.status in (400, 404)
        # Sanity: the file didn't get created
        assert not (tmp_path / "evil.yaml").exists()
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# delete / archive
# ---------------------------------------------------------------------------

async def test_delete_target_archives_by_default(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "device1.yaml", "device1")
        resp = await ta.delete("/ui/api/targets/device1.yaml")
        assert resp.status == 200

        # File moved to .archive/
        assert not (ta.config_dir / "device1.yaml").exists()
        assert (ta.config_dir / ".archive" / "device1.yaml").exists()
    finally:
        await ta.close()


async def test_delete_target_permanent(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "device1.yaml", "device1")
        resp = await ta.delete("/ui/api/targets/device1.yaml?archive=false")
        assert resp.status == 200
        assert not (ta.config_dir / "device1.yaml").exists()
        assert not (ta.config_dir / ".archive" / "device1.yaml").exists()
    finally:
        await ta.close()


async def test_delete_target_cancels_pending_jobs(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "device1.yaml", "device1")
        job = await ta.queue.enqueue("device1.yaml", "2024.3.1", "run1", 300)
        assert job.state == JobState.PENDING

        resp = await ta.delete("/ui/api/targets/device1.yaml")
        assert resp.status == 200

        stored = ta.queue.get(job.id)
        assert stored.state == JobState.CANCELLED  # #49: cancel marks as CANCELLED
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# archive list / restore / permanent delete
# ---------------------------------------------------------------------------

async def test_archive_list_empty(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        resp = await ta.get("/ui/api/archive")
        assert resp.status == 200
        assert await resp.json() == []
    finally:
        await ta.close()


async def test_archive_list_after_delete(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "device1.yaml", "device1")
        await ta.delete("/ui/api/targets/device1.yaml")

        resp = await ta.get("/ui/api/archive")
        data = await resp.json()
        assert len(data) == 1
        assert data[0]["filename"] == "device1.yaml"
    finally:
        await ta.close()


async def test_archive_restore(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "device1.yaml", "device1")
        await ta.delete("/ui/api/targets/device1.yaml")
        assert not (ta.config_dir / "device1.yaml").exists()

        resp = await ta.post("/ui/api/archive/device1.yaml/restore")
        assert resp.status == 200
        assert (ta.config_dir / "device1.yaml").exists()
        assert not (ta.config_dir / ".archive" / "device1.yaml").exists()
    finally:
        await ta.close()


async def test_archive_permanent_delete(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "device1.yaml", "device1")
        await ta.delete("/ui/api/targets/device1.yaml")

        resp = await ta.delete("/ui/api/archive/device1.yaml")
        assert resp.status == 200
        assert not (ta.config_dir / ".archive" / "device1.yaml").exists()
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------

async def test_compile_all_enqueues_all_targets(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "a.yaml", "a")
        _write_config(ta.config_dir, "b.yaml", "b")

        resp = await ta.post("/ui/api/compile", json={"targets": "all"})
        assert resp.status == 200
        data = await resp.json()
        assert data["enqueued"] == 2
        assert "run_id" in data

        jobs = ta.queue.get_all()
        targets = {j.target for j in jobs}
        assert targets == {"a.yaml", "b.yaml"}
    finally:
        await ta.close()


async def test_compile_specific_targets(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "a.yaml", "a")
        _write_config(ta.config_dir, "b.yaml", "b")
        _write_config(ta.config_dir, "c.yaml", "c")

        resp = await ta.post("/ui/api/compile", json={"targets": ["a.yaml", "c.yaml"]})
        data = await resp.json()
        assert data["enqueued"] == 2

        targets = {j.target for j in ta.queue.get_all()}
        assert targets == {"a.yaml", "c.yaml"}
    finally:
        await ta.close()


async def test_compile_filters_unknown_targets(tmp_path):
    """A target not in the config dir is silently dropped, not an error."""
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "a.yaml", "a")
        resp = await ta.post("/ui/api/compile", json={"targets": ["a.yaml", "ghost.yaml"]})
        data = await resp.json()
        assert data["enqueued"] == 1
        assert {j.target for j in ta.queue.get_all()} == {"a.yaml"}
    finally:
        await ta.close()


async def test_compile_pinned_client_id(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "a.yaml", "a")
        resp = await ta.post(
            "/ui/api/compile",
            json={"targets": ["a.yaml"], "pinned_client_id": "worker-42"},
        )
        assert resp.status == 200
        jobs = ta.queue.get_all()
        assert len(jobs) == 1
        assert jobs[0].pinned_client_id == "worker-42"
    finally:
        await ta.close()


async def test_compile_invalid_json(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        resp = await ta.post(
            "/ui/api/compile",
            data="not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

async def test_validate_runs_esphome_config_directly(tmp_path):
    """Bug #25: /ui/api/validate runs ``esphome config`` as a direct subprocess
    on the server. No queue, no worker, immediate response.

    We mock ``asyncio.create_subprocess_exec`` since ``esphome`` isn't
    installed in the test environment.
    """
    from unittest.mock import AsyncMock, patch, MagicMock

    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "device1.yaml", "device1")

        # Mock a successful esphome config run.
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"Configuration is valid!\n", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            resp = await ta.post("/ui/api/validate", json={"target": "device1.yaml"})
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert "valid" in data["output"].lower()

            # Verify esphome config was called with the correct target path.
            mock_exec.assert_called_once()
            args = mock_exec.call_args[0]
            assert args[0] == "esphome"
            assert args[1] == "config"
            assert "device1.yaml" in str(args[2])

        # Also test a failed validation.
        mock_proc.communicate = AsyncMock(return_value=(b"ERROR: Invalid YAML\n", b""))
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            resp = await ta.post("/ui/api/validate", json={"target": "device1.yaml"})
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is False
            assert "Invalid YAML" in data["output"]
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# rename
# ---------------------------------------------------------------------------

async def test_rename_target_updates_file_and_name(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "old_device.yaml", "old-device")
        resp = await ta.post(
            "/ui/api/targets/old_device.yaml/rename",
            json={"new_name": "new-device"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["new_filename"] == "new-device.yaml"

        new_path = ta.config_dir / "new-device.yaml"
        assert new_path.exists()
        assert not (ta.config_dir / "old_device.yaml").exists()
        content = new_path.read_text()
        assert "new-device" in content
    finally:
        await ta.close()


async def test_rename_target_missing_source(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        resp = await ta.post(
            "/ui/api/targets/ghost.yaml/rename",
            json={"new_name": "new"},
        )
        assert resp.status == 404
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# queue / retry / clear / remove / cancel
# ---------------------------------------------------------------------------

async def test_queue_returns_jobs(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "device1.yaml", "device1")
        await ta.queue.enqueue("device1.yaml", "2024.3.1", "run1", 300)
        resp = await ta.get("/ui/api/queue")
        assert resp.status == 200
        jobs = await resp.json()
        assert len(jobs) == 1
        assert jobs[0]["target"] == "device1.yaml"
    finally:
        await ta.close()


async def test_retry_failed_job(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "device1.yaml", "device1")
        job = await ta.queue.enqueue("device1.yaml", "2024.3.1", "run1", 300)
        claimed = await ta.queue.claim_next("client-A")
        await ta.queue.submit_result(claimed.id, "failed", log="error")

        resp = await ta.post("/ui/api/retry", json={"job_ids": [job.id]})
        assert resp.status == 200
        data = await resp.json()
        assert data["retried"] == 1

        # A new pending job should exist for the same target
        pending = [j for j in ta.queue.get_all() if j.state == JobState.PENDING]
        assert len(pending) == 1
        assert pending[0].target == "device1.yaml"
    finally:
        await ta.close()


async def test_retry_all_failed(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "a.yaml", "a")
        _write_config(ta.config_dir, "b.yaml", "b")
        for target in ("a.yaml", "b.yaml"):
            await ta.queue.enqueue(target, "2024.3.1", "run1", 300)
            claimed = await ta.queue.claim_next("client-A")
            await ta.queue.submit_result(claimed.id, "failed", log="error")

        resp = await ta.post("/ui/api/retry", json={"job_ids": "all_failed"})
        data = await resp.json()
        assert data["retried"] == 2
    finally:
        await ta.close()


async def test_cancel_jobs(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "device1.yaml", "device1")
        job = await ta.queue.enqueue("device1.yaml", "2024.3.1", "run1", 300)

        resp = await ta.post("/ui/api/cancel", json={"job_ids": [job.id]})
        assert resp.status == 200
        data = await resp.json()
        assert data["cancelled"] == 1
        assert ta.queue.get(job.id).state == JobState.CANCELLED
    finally:
        await ta.close()


async def test_queue_clear_by_state(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "device1.yaml", "device1")
        await ta.queue.enqueue("device1.yaml", "2024.3.1", "run1", 300)
        claimed = await ta.queue.claim_next("client-A")
        await ta.queue.submit_result(claimed.id, "success", log="ok", ota_result="success")

        resp = await ta.post("/ui/api/queue/clear", json={"states": ["success"]})
        assert resp.status == 200
        data = await resp.json()
        assert data["cleared"] == 1
        assert ta.queue.queue_size() == 0
    finally:
        await ta.close()


async def test_queue_remove_by_id(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "device1.yaml", "device1")
        job = await ta.queue.enqueue("device1.yaml", "2024.3.1", "run1", 300)
        claimed = await ta.queue.claim_next("client-A")
        await ta.queue.submit_result(claimed.id, "failed", log="error")

        resp = await ta.post("/ui/api/queue/remove", json={"ids": [job.id]})
        assert resp.status == 200
        assert ta.queue.get(job.id) is None
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# workers
# ---------------------------------------------------------------------------

async def test_workers_lists_registered(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        ta.registry.register("worker-1", "linux/amd64", image_version="4")
        ta.registry.register("worker-2", "linux/arm64", image_version="4")
        resp = await ta.get("/ui/api/workers")
        assert resp.status == 200
        data = await resp.json()
        assert len(data) == 2
        hostnames = {w["hostname"] for w in data}
        assert hostnames == {"worker-1", "worker-2"}
    finally:
        await ta.close()


async def test_worker_set_parallel_jobs(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        client_id = ta.registry.register("w", "linux/amd64", image_version="4")
        resp = await ta.post(
            f"/ui/api/workers/{client_id}/parallel-jobs",
            json={"max_parallel_jobs": 4},
        )
        assert resp.status == 200
        worker = ta.registry.get(client_id)
        assert worker.requested_max_parallel_jobs == 4
    finally:
        await ta.close()


async def test_worker_set_parallel_jobs_rejects_out_of_range(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        client_id = ta.registry.register("w", "linux/amd64", image_version="4")
        resp = await ta.post(
            f"/ui/api/workers/{client_id}/parallel-jobs",
            json={"max_parallel_jobs": 99},
        )
        assert resp.status == 400
    finally:
        await ta.close()


async def test_worker_set_parallel_jobs_unknown_worker(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        resp = await ta.post(
            "/ui/api/workers/unknown-id/parallel-jobs",
            json={"max_parallel_jobs": 2},
        )
        assert resp.status == 404
    finally:
        await ta.close()


async def test_worker_remove_offline(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        from datetime import datetime, timedelta, timezone
        client_id = ta.registry.register("w", "linux/amd64", image_version="4")
        # Backdate last_seen so the worker is considered offline
        ta.registry.get(client_id).last_seen = datetime.now(timezone.utc) - timedelta(minutes=5)

        resp = await ta.delete(f"/ui/api/workers/{client_id}")
        assert resp.status == 200
        assert ta.registry.get(client_id) is None
    finally:
        await ta.close()


async def test_worker_remove_online_refused(tmp_path):
    """Can't remove an online worker — must be marked offline first."""
    ta = await _make_ui_app(tmp_path)
    try:
        client_id = ta.registry.register("w", "linux/amd64", image_version="4")
        resp = await ta.delete(f"/ui/api/workers/{client_id}")
        assert resp.status == 409
        # Worker is still in the registry
        assert ta.registry.get(client_id) is not None
    finally:
        await ta.close()


async def test_worker_clean_cache_sets_pending_flag(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        client_id = ta.registry.register("w", "linux/amd64", image_version="4")
        resp = await ta.post(f"/ui/api/workers/{client_id}/clean")
        assert resp.status == 200
        assert ta.registry.get(client_id).pending_clean is True
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# POST /ui/api/targets — CD.3 (create + duplicate device)
# ---------------------------------------------------------------------------


async def test_create_target_stub(tmp_path):
    """POST /ui/api/targets with no source creates a staged dotfile."""
    import yaml
    ta = await _make_ui_app(tmp_path)
    try:
        resp = await ta.post("/ui/api/targets", json={"filename": "kitchen"})
        assert resp.status == 200
        data = await resp.json()
        # #62: create returns a .pending. prefixed filename
        assert data["target"] == ".pending.kitchen.yaml"
        # File is staged as a dotfile at the config root (not the final name)
        staged = ta.config_dir / ".pending.kitchen.yaml"
        assert staged.exists()
        parsed = yaml.safe_load(staged.read_text())
        assert parsed["esphome"]["name"] == "kitchen"
        # Final name does NOT exist yet (not written until first save)
        assert not (ta.config_dir / "kitchen.yaml").exists()
    finally:
        await ta.close()


async def test_create_target_accepts_yaml_extension(tmp_path):
    """filename='kitchen.yaml' is normalised and accepted."""
    ta = await _make_ui_app(tmp_path)
    try:
        resp = await ta.post("/ui/api/targets", json={"filename": "kitchen.yaml"})
        assert resp.status == 200
        data = await resp.json()
        assert data["target"] == ".pending.kitchen.yaml"
    finally:
        await ta.close()


async def test_create_target_rejects_collision(tmp_path):
    """Creating a filename that already exists returns 400."""
    ta = await _make_ui_app(tmp_path)
    try:
        (ta.config_dir / "existing.yaml").write_text("esphome:\n  name: existing\n")
        resp = await ta.post("/ui/api/targets", json={"filename": "existing"})
        assert resp.status == 400
        body = await resp.json()
        assert "already exists" in body["error"]
    finally:
        await ta.close()


async def test_create_target_rejects_path_traversal(tmp_path):
    """A filename containing slashes is rejected by the slug regex."""
    ta = await _make_ui_app(tmp_path)
    try:
        resp = await ta.post("/ui/api/targets", json={"filename": "../etc/passwd"})
        assert resp.status == 400
    finally:
        await ta.close()


async def test_create_target_rejects_invalid_slug(tmp_path):
    """Underscores, uppercase, spaces all rejected by the slug regex."""
    ta = await _make_ui_app(tmp_path)
    try:
        for bad in ("Kitchen", "my_device", "device 1", "-leading-hyphen", ""):
            resp = await ta.post("/ui/api/targets", json={"filename": bad})
            assert resp.status == 400, f"expected 400 for {bad!r}"
    finally:
        await ta.close()


async def test_create_target_duplicate(tmp_path):
    """POST /ui/api/targets with source duplicates and rewrites esphome.name."""
    import yaml
    ta = await _make_ui_app(tmp_path)
    try:
        (ta.config_dir / "source.yaml").write_text(
            "esphome:\n  name: original\n  comment: Hello\n"
            "wifi:\n  ssid: home\n"
        )
        resp = await ta.post(
            "/ui/api/targets",
            json={"filename": "copy", "source": "source.yaml"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["target"] == ".pending.copy.yaml"

        created = ta.config_dir / ".pending.copy.yaml"
        parsed = yaml.safe_load(created.read_text())
        assert parsed["esphome"]["name"] == "copy"
        assert parsed["esphome"]["comment"] == "Hello"
        assert parsed["wifi"]["ssid"] == "home"
    finally:
        await ta.close()


async def test_create_target_duplicate_missing_source(tmp_path):
    """Duplicating from a non-existent source returns 404."""
    ta = await _make_ui_app(tmp_path)
    try:
        resp = await ta.post(
            "/ui/api/targets",
            json={"filename": "new", "source": "nonexistent.yaml"},
        )
        assert resp.status == 404
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# FD.2 / FD.6 — compile(download_only) + /ui/api/jobs/{id}/firmware download
# ---------------------------------------------------------------------------

async def test_compile_accepts_download_only_flag(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "a.yaml", "a")
        resp = await ta.post(
            "/ui/api/compile",
            json={"targets": ["a.yaml"], "download_only": True},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["enqueued"] == 1
        job = ta.queue.get_all()[0]
        assert job.download_only is True
        assert job.has_firmware is False
    finally:
        await ta.close()


async def test_compile_defaults_download_only_to_false(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        _write_config(ta.config_dir, "a.yaml", "a")
        resp = await ta.post("/ui/api/compile", json={"targets": ["a.yaml"]})
        assert resp.status == 200
        job = ta.queue.get_all()[0]
        assert job.download_only is False
    finally:
        await ta.close()


async def test_firmware_download_streams_stored_bin(tmp_path, monkeypatch):
    import firmware_storage
    firmware_dir = tmp_path / "firmware"
    monkeypatch.setattr(firmware_storage, "DEFAULT_FIRMWARE_DIR", firmware_dir)

    ta = await _make_ui_app(tmp_path)
    try:
        job = await ta.queue.enqueue(
            target="office.yaml", esphome_version="2026.3.2", run_id="r",
            timeout_seconds=300, download_only=True,
        )
        assert job is not None
        await ta.queue.claim_next("any")
        # #69: save via the default (factory) variant; the endpoint
        # picks the first variant reported by list_variants when no
        # ?variant= is given.
        firmware_storage.save_firmware(
            job.id, b"HELLO_FW", variant="factory", root=firmware_dir,
        )
        await ta.queue.mark_firmware_stored(job.id)

        resp = await ta.get(f"/ui/api/jobs/{job.id}/firmware")
        assert resp.status == 200
        body = await resp.read()
        assert body == b"HELLO_FW"
        # Must arrive as an attachment with a filename derived from the target + short id.
        cd = resp.headers.get("Content-Disposition", "")
        assert "attachment" in cd
        assert "office-" in cd
        # #69: non-legacy variants (factory/ota) are tagged in the filename.
        assert "-factory.bin" in cd
    finally:
        await ta.close()


async def test_firmware_download_selects_variant_by_query(tmp_path, monkeypatch):
    """#69 — ?variant=ota serves the OTA binary even when factory exists."""
    import firmware_storage
    firmware_dir = tmp_path / "firmware"
    monkeypatch.setattr(firmware_storage, "DEFAULT_FIRMWARE_DIR", firmware_dir)

    ta = await _make_ui_app(tmp_path)
    try:
        job = await ta.queue.enqueue(
            target="office.yaml", esphome_version="2026.3.2", run_id="r",
            timeout_seconds=300, download_only=True,
        )
        await ta.queue.claim_next("any")
        firmware_storage.save_firmware(
            job.id, b"FACTORY", variant="factory", root=firmware_dir,
        )
        firmware_storage.save_firmware(
            job.id, b"OTA_ONLY", variant="ota", root=firmware_dir,
        )
        await ta.queue.mark_firmware_stored(job.id)

        resp = await ta.get(f"/ui/api/jobs/{job.id}/firmware?variant=ota")
        assert resp.status == 200
        assert await resp.read() == b"OTA_ONLY"
        assert "-ota.bin" in resp.headers["Content-Disposition"]

        resp = await ta.get(f"/ui/api/jobs/{job.id}/firmware?variant=factory")
        assert await resp.read() == b"FACTORY"
        assert "-factory.bin" in resp.headers["Content-Disposition"]

        # Unknown variant → 404 with the available list in the body.
        resp = await ta.get(f"/ui/api/jobs/{job.id}/firmware?variant=nope")
        assert resp.status == 404
        data = await resp.json()
        assert data["available"] == ["factory", "ota"]
    finally:
        await ta.close()


async def test_firmware_download_gzip_flag_compresses_body(tmp_path, monkeypatch):
    """#69 — ?gz=1 wraps the response in gzip and serves a .bin.gz filename."""
    import gzip
    import firmware_storage
    firmware_dir = tmp_path / "firmware"
    monkeypatch.setattr(firmware_storage, "DEFAULT_FIRMWARE_DIR", firmware_dir)

    ta = await _make_ui_app(tmp_path)
    try:
        job = await ta.queue.enqueue(
            target="office.yaml", esphome_version="2026.3.2", run_id="r",
            timeout_seconds=300, download_only=True,
        )
        await ta.queue.claim_next("any")
        payload = b"A" * 4096  # compressible
        firmware_storage.save_firmware(
            job.id, payload, variant="factory", root=firmware_dir,
        )
        await ta.queue.mark_firmware_stored(job.id)

        resp = await ta.get(f"/ui/api/jobs/{job.id}/firmware?gz=1")
        assert resp.status == 200
        body = await resp.read()
        # Content-Encoding: identity ensures aiohttp didn't transparently
        # re-inflate on the client side.
        assert resp.headers["Content-Encoding"] == "identity"
        assert gzip.decompress(body) == payload
        # Compression is real — body should be materially smaller than
        # the uncompressed 4096 bytes (4096 A's compresses to <100).
        assert len(body) < 200
        assert resp.headers["Content-Disposition"].endswith('.bin.gz"')
    finally:
        await ta.close()


async def test_firmware_download_returns_404_when_unavailable(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        job = await ta.queue.enqueue(
            target="a.yaml", esphome_version="2026.3.2", run_id="r",
            timeout_seconds=300, download_only=True,
        )
        assert job is not None
        # has_firmware is False → endpoint returns 404.
        resp = await ta.get(f"/ui/api/jobs/{job.id}/firmware")
        assert resp.status == 404
    finally:
        await ta.close()


async def test_firmware_download_404_when_job_missing(tmp_path):
    ta = await _make_ui_app(tmp_path)
    try:
        resp = await ta.get("/ui/api/jobs/ghost/firmware")
        assert resp.status == 404
    finally:
        await ta.close()
