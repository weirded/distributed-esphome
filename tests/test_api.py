"""Tests for the worker REST API (/api/v1/*) in api.py.

Uses aiohttp.test_utils.TestClient/TestServer directly (no pytest-aiohttp required).
"""

from __future__ import annotations

import asyncio
import base64
import io
import tarfile
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import api as api_module
from app_config import AppConfig
from job_queue import JobQueue, JobState
from main import auth_middleware
from registry import WorkerRegistry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOKEN = "test-secret-token"
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_bundle() -> bytes:
    """Return a minimal tar.gz that satisfies the bundle contract."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        content = b"esphome:\n  name: testdevice\n"
        info = tarfile.TarInfo(name="testdevice.yaml")
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class _App:
    """Container for a running TestClient plus direct access to queue and registry."""

    def __init__(
        self,
        client: TestClient,
        queue: JobQueue,
        registry: WorkerRegistry,
        app: web.Application,
    ) -> None:
        self.client = client
        self.queue = queue
        self.registry = registry
        self.app = app

    async def close(self) -> None:
        await self.client.close()

    # Convenience passthroughs so test code stays readable
    async def get(self, *args, **kwargs):
        return await self.client.get(*args, **kwargs)

    async def post(self, *args, **kwargs):
        return await self.client.post(*args, **kwargs)


async def _make_app(tmp_path: Path, token: str = TOKEN) -> _App:
    """Spin up a fresh isolated test app for a single test."""
    cfg = AppConfig(token=token, config_dir=str(tmp_path))
    queue = JobQueue(queue_file=tmp_path / "queue.json")
    registry = WorkerRegistry()

    app = web.Application(middlewares=[auth_middleware])
    app["config"] = cfg
    app["queue"] = queue
    app["registry"] = registry
    app["log_subscribers"] = {}
    app.router.add_routes(api_module.routes)

    client = TestClient(TestServer(app))
    await client.start_server()
    return _App(client, queue, registry, app)


async def _enqueue_job(
    queue: JobQueue,
    target: str = "testdevice.yaml",
    version: str = "2024.3.1",
    pinned_client_id: str | None = None,
) -> "JobQueue":  # returns Job
    job = await queue.enqueue(
        target=target,
        esphome_version=version,
        run_id=str(uuid.uuid4()),
        timeout_seconds=300,
        pinned_client_id=pinned_client_id,
    )
    assert job is not None, "enqueue returned None (duplicate?)"
    return job


async def _register(ta: _App, hostname: str = "build-box", platform: str = "linux/amd64",
                    system_info: dict | None = None,
                    image_version: str | None = "1") -> str:
    # Defaults to image_version="1" (current MIN_IMAGE_VERSION) so most tests
    # exercise the happy path. Tests that want to simulate a stale-image worker
    # explicitly pass image_version=None.
    body: dict = {"hostname": hostname, "platform": platform}
    if system_info is not None:
        body["system_info"] = system_info
    if image_version is not None:
        body["image_version"] = image_version
    resp = await ta.post("/api/v1/workers/register", json=body, headers=AUTH_HEADERS)
    assert resp.status == 200
    return (await resp.json())["client_id"]


# ---------------------------------------------------------------------------
# 1. Registration
# ---------------------------------------------------------------------------

async def test_register_returns_client_id(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        resp = await ta.post(
            "/api/v1/workers/register",
            json={"hostname": "worker1", "platform": "linux/amd64"},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 200
        data = await resp.json()
        assert "client_id" in data
        assert len(data["client_id"]) > 0
    finally:
        await ta.close()


async def test_register_stores_worker_in_registry(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        resp = await ta.post(
            "/api/v1/workers/register",
            json={"hostname": "worker1", "platform": "linux/arm64", "client_version": "1.2.3"},
            headers=AUTH_HEADERS,
        )
        client_id = (await resp.json())["client_id"]

        worker = ta.registry.get(client_id)
        assert worker is not None
        assert worker.hostname == "worker1"
        assert worker.platform == "linux/arm64"
        assert worker.client_version == "1.2.3"
    finally:
        await ta.close()


async def test_register_without_auth_returns_401(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        resp = await ta.post(
            "/api/v1/workers/register",
            json={"hostname": "worker1", "platform": "linux/amd64"},
        )
        assert resp.status == 401
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# 2. Re-registration preserves client_id
# ---------------------------------------------------------------------------

async def test_reregister_preserves_client_id(tmp_path):
    """Re-registering with the same client_id returns the same id."""
    ta = await _make_app(tmp_path)
    try:
        resp1 = await ta.post(
            "/api/v1/workers/register",
            json={"hostname": "worker1", "platform": "linux/amd64"},
            headers=AUTH_HEADERS,
        )
        client_id = (await resp1.json())["client_id"]

        resp2 = await ta.post(
            "/api/v1/workers/register",
            json={"hostname": "worker1", "platform": "linux/amd64", "client_id": client_id},
            headers=AUTH_HEADERS,
        )
        assert resp2.status == 200
        assert (await resp2.json())["client_id"] == client_id

        # Only one entry in registry
        assert len(ta.registry.get_all()) == 1
    finally:
        await ta.close()


async def test_reregister_updates_hostname(tmp_path):
    """Re-registration with a new hostname updates the stored value."""
    ta = await _make_app(tmp_path)
    try:
        resp1 = await ta.post(
            "/api/v1/workers/register",
            json={"hostname": "old-name", "platform": "linux/amd64"},
            headers=AUTH_HEADERS,
        )
        client_id = (await resp1.json())["client_id"]

        await ta.post(
            "/api/v1/workers/register",
            json={"hostname": "new-name", "platform": "linux/amd64", "client_id": client_id},
            headers=AUTH_HEADERS,
        )

        worker = ta.registry.get(client_id)
        assert worker.hostname == "new-name"
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# 3. Heartbeat
# ---------------------------------------------------------------------------

async def test_heartbeat_updates_last_seen(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        ts_before = ta.registry.get(client_id).last_seen

        await asyncio.sleep(0.01)

        resp = await ta.post(
            "/api/v1/workers/heartbeat",
            json={"client_id": client_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        assert "server_client_version" in data

        ts_after = ta.registry.get(client_id).last_seen
        assert ts_after >= ts_before
    finally:
        await ta.close()


async def test_heartbeat_returns_server_version(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        resp = await ta.post(
            "/api/v1/workers/heartbeat",
            json={"client_id": client_id},
            headers=AUTH_HEADERS,
        )
        data = await resp.json()
        assert isinstance(data["server_client_version"], str)
        assert len(data["server_client_version"]) > 0
    finally:
        await ta.close()


async def test_heartbeat_updates_system_info(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        system_info = {"perf_score": 42, "cpu_usage": 25}
        resp = await ta.post(
            "/api/v1/workers/heartbeat",
            json={"client_id": client_id, "system_info": system_info},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 200
        assert ta.registry.get(client_id).system_info == system_info
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# 4. Heartbeat — unknown worker
# ---------------------------------------------------------------------------

async def test_heartbeat_unknown_worker_returns_404(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        resp = await ta.post(
            "/api/v1/workers/heartbeat",
            json={"client_id": "does-not-exist"},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 404
        data = await resp.json()
        assert "error" in data
    finally:
        await ta.close()


async def test_heartbeat_missing_client_id_returns_400(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        resp = await ta.post(
            "/api/v1/workers/heartbeat",
            json={},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 400
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# 5. Claim job — job available
# ---------------------------------------------------------------------------

async def test_claim_job_returns_job_payload(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        await _enqueue_job(ta.queue, "device.yaml")

        with patch("api.create_bundle", return_value=_make_test_bundle()):
            resp = await ta.get(
                "/api/v1/jobs/next",
                headers={**AUTH_HEADERS, "X-Client-Id": client_id},
            )

        assert resp.status == 200
        data = await resp.json()
        assert data["target"] == "device.yaml"
        assert "job_id" in data
        assert "bundle_b64" in data
        # Verify the bundle is valid base64
        decoded = base64.b64decode(data["bundle_b64"])
        assert len(decoded) > 0
    finally:
        await ta.close()


async def test_claim_job_transitions_to_working(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        job = await _enqueue_job(ta.queue, "device.yaml")

        with patch("api.create_bundle", return_value=_make_test_bundle()):
            resp = await ta.get(
                "/api/v1/jobs/next",
                headers={**AUTH_HEADERS, "X-Client-Id": client_id},
            )

        assert resp.status == 200
        refreshed = ta.queue.get(job.id)
        assert refreshed.state == JobState.WORKING
        assert refreshed.assigned_client_id == client_id
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# 6. Claim job — empty queue
# ---------------------------------------------------------------------------

async def test_claim_job_empty_queue_returns_204(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        resp = await ta.get(
            "/api/v1/jobs/next",
            headers={**AUTH_HEADERS, "X-Client-Id": client_id},
        )
        assert resp.status == 204
    finally:
        await ta.close()


async def test_claim_job_missing_client_id_returns_400(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        resp = await ta.get("/api/v1/jobs/next", headers=AUTH_HEADERS)
        assert resp.status == 400
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# 7. Claim job — disabled worker
# ---------------------------------------------------------------------------

async def test_claim_job_disabled_worker_returns_204(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        await _enqueue_job(ta.queue, "device.yaml")
        ta.registry.set_disabled(client_id, True)

        resp = await ta.get(
            "/api/v1/jobs/next",
            headers={**AUTH_HEADERS, "X-Client-Id": client_id},
        )
        assert resp.status == 204

        # Job should remain PENDING
        assert all(j.state == JobState.PENDING for j in ta.queue.get_all())
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# 8. Submit result — success and failure
# ---------------------------------------------------------------------------

async def test_submit_result_success(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        job = await _enqueue_job(ta.queue, "device.yaml")
        await ta.queue.claim_next(client_id)

        resp = await ta.post(
            f"/api/v1/jobs/{job.id}/result",
            json={"status": "success", "log": "Build complete"},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 200
        assert (await resp.json())["ok"] is True

        refreshed = ta.queue.get(job.id)
        assert refreshed.state == JobState.SUCCESS
        assert refreshed.log == "Build complete"
    finally:
        await ta.close()


async def test_submit_result_failure(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        job = await _enqueue_job(ta.queue, "device.yaml")
        await ta.queue.claim_next(client_id)

        resp = await ta.post(
            f"/api/v1/jobs/{job.id}/result",
            json={"status": "failed", "log": "Compile error"},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 200
        assert ta.queue.get(job.id).state == JobState.FAILED
    finally:
        await ta.close()


async def test_submit_result_with_ota_result(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        job = await _enqueue_job(ta.queue, "device.yaml")
        await ta.queue.claim_next(client_id)

        resp = await ta.post(
            f"/api/v1/jobs/{job.id}/result",
            json={"status": "success", "log": "done", "ota_result": "success"},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 200
        assert ta.queue.get(job.id).ota_result == "success"
    finally:
        await ta.close()


async def test_submit_result_unknown_job_returns_404(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        resp = await ta.post(
            "/api/v1/jobs/nonexistent-id/result",
            json={"status": "success"},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 404
    finally:
        await ta.close()


async def test_submit_result_invalid_status_returns_400(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        job = await _enqueue_job(ta.queue, "device.yaml")
        await ta.queue.claim_next(client_id)

        resp = await ta.post(
            f"/api/v1/jobs/{job.id}/result",
            json={"status": "broken"},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 400
    finally:
        await ta.close()


async def test_submit_result_clears_worker_job(tmp_path):
    """After submitting a result the registry shows current_job_id = None."""
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        job = await _enqueue_job(ta.queue, "device.yaml")
        await ta.queue.claim_next(client_id)
        ta.registry.set_job(client_id, job.id)

        await ta.post(
            f"/api/v1/jobs/{job.id}/result",
            json={"status": "success"},
            headers=AUTH_HEADERS,
        )

        assert ta.registry.get(client_id).current_job_id is None
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# 9. Performance-based scheduling — faster worker gets priority
# ---------------------------------------------------------------------------

async def test_faster_worker_gets_job_over_slower(tmp_path):
    """A slower worker defers when a faster idle worker with free slots exists."""
    ta = await _make_app(tmp_path)
    try:
        slow_id = await _register(ta, hostname="slow", system_info={"perf_score": 10, "cpu_usage": 0})
        fast_id = await _register(ta, hostname="fast", system_info={"perf_score": 100, "cpu_usage": 0})

        await _enqueue_job(ta.queue, "device.yaml")

        # Slow worker polls first — should be deferred
        with patch("api.create_bundle", return_value=_make_test_bundle()):
            slow_resp = await ta.get(
                "/api/v1/jobs/next",
                headers={**AUTH_HEADERS, "X-Client-Id": slow_id},
            )
        assert slow_resp.status == 204  # deferred — faster worker is idle

        # Fast worker polls — should receive the job
        with patch("api.create_bundle", return_value=_make_test_bundle()):
            fast_resp = await ta.get(
                "/api/v1/jobs/next",
                headers={**AUTH_HEADERS, "X-Client-Id": fast_id},
            )
        assert fast_resp.status == 200
        data = await fast_resp.json()
        assert data["target"] == "device.yaml"
    finally:
        await ta.close()


async def test_only_worker_always_gets_job(tmp_path):
    """When there is only one worker, it always claims regardless of perf_score."""
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        # Give the sole worker a poor perf score
        ta.registry.get(client_id).system_info = {"perf_score": 1, "cpu_usage": 99}

        await _enqueue_job(ta.queue, "device.yaml")

        with patch("api.create_bundle", return_value=_make_test_bundle()):
            resp = await ta.get(
                "/api/v1/jobs/next",
                headers={**AUTH_HEADERS, "X-Client-Id": client_id},
            )
        assert resp.status == 200
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# 10. Pinned job — only designated worker can claim
# ---------------------------------------------------------------------------

async def test_pinned_job_only_claimable_by_pinned_worker(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        id_a = await _register(ta, hostname="worker-a")
        id_b = await _register(ta, hostname="worker-b")

        # Enqueue a job pinned to worker-b
        await _enqueue_job(ta.queue, "device.yaml", pinned_client_id=id_b)

        # Worker-a must not receive it
        with patch("api.create_bundle", return_value=_make_test_bundle()):
            resp = await ta.get(
                "/api/v1/jobs/next",
                headers={**AUTH_HEADERS, "X-Client-Id": id_a},
            )
        assert resp.status == 204

        # Worker-b must receive it
        with patch("api.create_bundle", return_value=_make_test_bundle()):
            resp = await ta.get(
                "/api/v1/jobs/next",
                headers={**AUTH_HEADERS, "X-Client-Id": id_b},
            )
        assert resp.status == 200
        data = await resp.json()
        assert data["target"] == "device.yaml"
    finally:
        await ta.close()


async def test_pinned_job_not_deferred_by_faster_worker(tmp_path):
    """Pinned jobs ignore the faster-worker deferral logic."""
    ta = await _make_app(tmp_path)
    try:
        slow_id = await _register(ta, hostname="slow",
                                   system_info={"perf_score": 1, "cpu_usage": 0})
        _fast_id = await _register(ta, hostname="fast",
                                    system_info={"perf_score": 100, "cpu_usage": 0})

        # Pin job to the slow worker
        await _enqueue_job(ta.queue, "device.yaml", pinned_client_id=slow_id)

        with patch("api.create_bundle", return_value=_make_test_bundle()):
            resp = await ta.get(
                "/api/v1/jobs/next",
                headers={**AUTH_HEADERS, "X-Client-Id": slow_id},
            )

        # Slow worker must NOT be deferred — pinned jobs bypass deferral
        assert resp.status == 200
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# 11. Job log streaming (HTTP batch POST)
# ---------------------------------------------------------------------------

async def test_append_log_to_running_job(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        job = await _enqueue_job(ta.queue, "device.yaml")
        await ta.queue.claim_next(client_id)

        resp = await ta.post(
            f"/api/v1/jobs/{job.id}/log",
            json={"lines": "Compiling step 1...\nCompiling step 2...\n"},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 200
        assert (await resp.json())["ok"] is True

        # Log is stored in the streaming buffer (transient)
        refreshed = ta.queue.get(job.id)
        assert "Compiling step 1" in refreshed._streaming_log
    finally:
        await ta.close()


async def test_append_log_unknown_job_returns_404(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        resp = await ta.post(
            "/api/v1/jobs/no-such-job/log",
            json={"lines": "some output"},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 404
    finally:
        await ta.close()


async def test_append_log_forwarded_to_subscribers(tmp_path):
    """Lines POSTed to /log are pushed to any registered WebSocket subscribers."""
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        job = await _enqueue_job(ta.queue, "device.yaml")
        await ta.queue.claim_next(client_id)

        received: list[str] = []

        class FakeWs:
            async def send_str(self, text: str) -> None:
                received.append(text)

        fake_ws = FakeWs()
        ta.app["log_subscribers"][job.id] = {fake_ws}

        await ta.post(
            f"/api/v1/jobs/{job.id}/log",
            json={"lines": "hello from worker\n"},
            headers=AUTH_HEADERS,
        )

        assert received == ["hello from worker\n"]
    finally:
        await ta.close()


async def test_append_log_requires_auth(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        job = await _enqueue_job(ta.queue, "device.yaml")
        await ta.queue.claim_next(client_id)

        resp = await ta.post(
            f"/api/v1/jobs/{job.id}/log",
            json={"lines": "data"},
        )
        assert resp.status == 401
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# 12. Code endpoint — GET /api/v1/client/code
# ---------------------------------------------------------------------------

async def test_get_client_code_returns_version_and_files(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        resp = await ta.get("/api/v1/client/code", headers=AUTH_HEADERS)
        assert resp.status == 200
        data = await resp.json()
        assert "version" in data
        assert "files" in data
        assert isinstance(data["files"], dict)
        # The server module directory contains Python files, so there must be at least one
        assert len(data["files"]) > 0
    finally:
        await ta.close()


async def test_get_client_code_requires_auth(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        resp = await ta.get("/api/v1/client/code")
        assert resp.status == 401
    finally:
        await ta.close()


async def test_get_client_version_returns_string(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        resp = await ta.get("/api/v1/client/version", headers=AUTH_HEADERS)
        assert resp.status == 200
        data = await resp.json()
        assert "version" in data
        assert isinstance(data["version"], str)
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# Legacy routes — /api/v1/clients/* aliases
# ---------------------------------------------------------------------------

async def test_legacy_register_route_works(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        resp = await ta.post(
            "/api/v1/clients/register",
            json={"hostname": "legacy-worker", "platform": "linux/amd64"},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 200
        assert "client_id" in await resp.json()
    finally:
        await ta.close()


async def test_legacy_heartbeat_route_works(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        reg_resp = await ta.post(
            "/api/v1/clients/register",
            json={"hostname": "legacy-worker", "platform": "linux/amd64"},
            headers=AUTH_HEADERS,
        )
        client_id = (await reg_resp.json())["client_id"]

        resp = await ta.post(
            "/api/v1/clients/heartbeat",
            json={"client_id": client_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 200
        assert (await resp.json())["ok"] is True
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# Deregistration
# ---------------------------------------------------------------------------

async def test_deregister_removes_worker(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        client_id = await _register(ta)
        resp = await ta.post(
            "/api/v1/workers/deregister",
            json={"client_id": client_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 200
        assert (await resp.json())["ok"] is True
        assert ta.registry.get(client_id) is None
    finally:
        await ta.close()


async def test_deregister_unknown_worker_returns_404(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        resp = await ta.post(
            "/api/v1/workers/deregister",
            json={"client_id": "ghost-id"},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 404
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------

async def test_status_endpoint(tmp_path):
    ta = await _make_app(tmp_path)
    try:
        await _register(ta)
        resp = await ta.get("/api/v1/status", headers=AUTH_HEADERS)
        assert resp.status == 200
        data = await resp.json()
        assert "esphome_version" in data
        assert "online_workers" in data
        assert "queue_size" in data
    finally:
        await ta.close()


# ---------------------------------------------------------------------------
# LIB.0 — Docker image version detection
# ---------------------------------------------------------------------------

async def test_register_stores_image_version(tmp_path):
    """Workers that send image_version have it stored in the registry."""
    ta = await _make_app(tmp_path)
    try:
        resp = await ta.post(
            "/api/v1/workers/register",
            json={
                "hostname": "modern-worker",
                "platform": "linux/amd64",
                "client_version": "1.3.0-dev.17",
                "image_version": "1",
            },
            headers=AUTH_HEADERS,
        )
        client_id = (await resp.json())["client_id"]
        worker = ta.registry.get(client_id)
        assert worker is not None
        assert worker.image_version == "1"
    finally:
        await ta.close()


async def test_register_without_image_version_stores_none(tmp_path):
    """Pre-LIB.0 workers that don't send image_version get None (treated as stale)."""
    ta = await _make_app(tmp_path)
    try:
        resp = await ta.post(
            "/api/v1/workers/register",
            json={"hostname": "old-worker", "platform": "linux/amd64"},
            headers=AUTH_HEADERS,
        )
        client_id = (await resp.json())["client_id"]
        worker = ta.registry.get(client_id)
        assert worker is not None
        assert worker.image_version is None
    finally:
        await ta.close()


async def test_heartbeat_advertises_update_for_fresh_image(tmp_path):
    """Workers with a current image_version get server_client_version in heartbeat."""
    ta = await _make_app(tmp_path)
    try:
        reg_resp = await ta.post(
            "/api/v1/workers/register",
            json={
                "hostname": "modern-worker",
                "platform": "linux/amd64",
                "image_version": "1",
            },
            headers=AUTH_HEADERS,
        )
        client_id = (await reg_resp.json())["client_id"]

        hb_resp = await ta.post(
            "/api/v1/workers/heartbeat",
            json={"client_id": client_id},
            headers=AUTH_HEADERS,
        )
        assert hb_resp.status == 200
        data = await hb_resp.json()
        assert "server_client_version" in data
        assert "image_upgrade_required" not in data
    finally:
        await ta.close()


async def test_heartbeat_flags_stale_image(tmp_path):
    """Workers missing image_version get image_upgrade_required, NOT server_client_version."""
    ta = await _make_app(tmp_path)
    try:
        reg_resp = await ta.post(
            "/api/v1/workers/register",
            json={"hostname": "old-worker", "platform": "linux/amd64"},
            headers=AUTH_HEADERS,
        )
        client_id = (await reg_resp.json())["client_id"]

        hb_resp = await ta.post(
            "/api/v1/workers/heartbeat",
            json={"client_id": client_id},
            headers=AUTH_HEADERS,
        )
        assert hb_resp.status == 200
        data = await hb_resp.json()
        assert data.get("image_upgrade_required") is True
        assert "min_image_version" in data
        # Suppressing server_client_version prevents the auto-update loop
        assert "server_client_version" not in data
    finally:
        await ta.close()


async def test_heartbeat_flags_below_min_image_version(tmp_path):
    """A reported image_version strictly below the server minimum is flagged."""
    ta = await _make_app(tmp_path)
    try:
        # Pin the server's minimum high enough that "1" is below it for this test
        with patch.object(api_module, "MIN_IMAGE_VERSION", "5"):
            reg_resp = await ta.post(
                "/api/v1/workers/register",
                json={
                    "hostname": "old-image-worker",
                    "platform": "linux/amd64",
                    "image_version": "1",
                },
                headers=AUTH_HEADERS,
            )
            client_id = (await reg_resp.json())["client_id"]

            hb_resp = await ta.post(
                "/api/v1/workers/heartbeat",
                json={"client_id": client_id},
                headers=AUTH_HEADERS,
            )
            data = await hb_resp.json()
            assert data.get("image_upgrade_required") is True
            assert data.get("min_image_version") == "5"
    finally:
        await ta.close()


async def test_get_client_code_refuses_stale_image(tmp_path):
    """Stale-image workers get 409 from /api/v1/client/code instead of code."""
    ta = await _make_app(tmp_path)
    try:
        reg_resp = await ta.post(
            "/api/v1/workers/register",
            json={"hostname": "old-worker", "platform": "linux/amd64"},
            headers=AUTH_HEADERS,
        )
        client_id = (await reg_resp.json())["client_id"]

        headers = {**AUTH_HEADERS, "X-Client-Id": client_id}
        resp = await ta.get("/api/v1/client/code", headers=headers)
        assert resp.status == 409
        data = await resp.json()
        assert data.get("error") == "image_upgrade_required"
    finally:
        await ta.close()


async def test_get_client_code_allows_fresh_image(tmp_path):
    """Fresh-image workers can still pull source code."""
    ta = await _make_app(tmp_path)
    try:
        reg_resp = await ta.post(
            "/api/v1/workers/register",
            json={
                "hostname": "modern-worker",
                "platform": "linux/amd64",
                "image_version": "1",
            },
            headers=AUTH_HEADERS,
        )
        client_id = (await reg_resp.json())["client_id"]

        headers = {**AUTH_HEADERS, "X-Client-Id": client_id}
        resp = await ta.get("/api/v1/client/code", headers=headers)
        assert resp.status == 200
        data = await resp.json()
        assert "files" in data
    finally:
        await ta.close()
