"""Tests for the WL.2 worker-log HTTP + WS endpoints.

Covers:
  - POST /api/v1/workers/{id}/logs (worker pushes chunks)
  - GET /ui/api/workers/{id}/logs (UI snapshot hydration)
  - WS /ui/api/workers/{id}/logs/ws (UI live tail)
  - Heartbeat handler sets stream_logs based on broker.is_watched.

The app fixture here mirrors tests/test_api.py's `_make_app` but also
wires in the `ui_api` routes and the `WorkerLogBroker`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import api as api_module
import pytest_socket
import settings as _s
import ui_api as ui_api_module


# pytest-homeassistant-custom-component (installed on this dev box, not
# in CI's non-integration env) globally disables sockets via
# pytest_socket. Re-enable per test so the aiohttp TestClient can bind
# a loopback listener.
@pytest.fixture(autouse=True)
def _enable_loopback_socket():
    pytest_socket.enable_socket()
    yield
    # Intentionally do NOT re-disable on teardown: asyncio cleanup
    # during the test exit runs *after* our yield and still needs to
    # touch the event-loop's self-pipe socket. Re-disabling here
    # raises SocketBlockedError inside BaseEventLoop.close().
from app_config import AppConfig
from ha_auth import ha_auth_middleware
from job_queue import JobQueue
from main import auth_middleware
from registry import WorkerRegistry
from worker_log_broker import WorkerLogBroker


TOKEN = "token-abc"  # noqa: S105 — test constant
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}


# pytest_socket (installed transitively by pytest-homeassistant-custom-
# component) blocks socket() by default. The aiohttp TestClient needs a
# real loopback socket, so whitelist localhost for every test in this
# module. Same convention used implicitly by CI, where the package
# isn't installed in the non-integration environment.


async def _close(client: TestClient) -> None:
    """Close both the aiohttp test client and any broker eviction tasks.

    The broker schedules a 1 h eviction task on every unsubscribe; tests
    that close a WS leave that task pending unless we explicitly cancel
    it here.
    """
    broker = client.app.get("worker_log_broker")
    if broker is not None:
        await broker.aclose()
    await client.close()


async def _make_app(tmp_path: Path) -> TestClient:
    cfg = AppConfig(config_dir=str(tmp_path))
    _s._reset_for_tests()
    _s.init_settings(
        settings_path=tmp_path / "settings.json",
        options_path=tmp_path / "options.json",
    )
    await _s.update_settings({"server_token": TOKEN, "require_ha_auth": False})

    queue = JobQueue(queue_file=tmp_path / "queue.json")
    registry = WorkerRegistry()
    broker = WorkerLogBroker(evict_after_seconds=3600)

    app = web.Application(middlewares=[auth_middleware, ha_auth_middleware])
    app["config"] = cfg
    app["queue"] = queue
    app["registry"] = registry
    app["worker_log_broker"] = broker
    app["log_subscribers"] = {}
    app.router.add_routes(api_module.routes)
    app.router.add_routes(ui_api_module.routes)

    client = TestClient(TestServer(app))
    await client.start_server()
    return client


async def _register(client: TestClient, hostname: str = "w1") -> str:
    from constants import MIN_IMAGE_VERSION  # noqa: PLC0415

    resp = await client.post(
        "/api/v1/workers/register",
        json={
            "hostname": hostname,
            "platform": "linux/amd64",
            "image_version": MIN_IMAGE_VERSION,
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status == 200, await resp.text()
    return (await resp.json())["client_id"]


# ---------------------------------------------------------------------------
# Heartbeat <-> broker wiring
# ---------------------------------------------------------------------------


async def test_heartbeat_stream_logs_false_when_no_watchers(tmp_path):
    client = await _make_app(tmp_path)
    try:
        client_id = await _register(client)
        resp = await client.post(
            "/api/v1/workers/heartbeat",
            json={"client_id": client_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 200
        body = await resp.json()
        # Design: flag is either False or absent when no one is watching
        # (absent == None == "unchanged" which the worker treats as no-op).
        # Explicit False is the signal to tear down the pusher thread.
        assert body.get("stream_logs") in (False, None)
    finally:
        await _close(client)


async def test_heartbeat_stream_logs_true_when_subscriber_attached(tmp_path):
    client = await _make_app(tmp_path)
    try:
        client_id = await _register(client)
        broker: WorkerLogBroker = client.app["worker_log_broker"]
        broker.subscribe(client_id, object())

        resp = await client.post(
            "/api/v1/workers/heartbeat",
            json={"client_id": client_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 200
        body = await resp.json()
        assert body.get("stream_logs") is True
    finally:
        await _close(client)


# ---------------------------------------------------------------------------
# POST /api/v1/workers/{id}/logs
# ---------------------------------------------------------------------------


async def test_worker_log_push_accepted_from_empty_state(tmp_path):
    client = await _make_app(tmp_path)
    try:
        client_id = await _register(client)
        resp = await client.post(
            f"/api/v1/workers/{client_id}/logs",
            json={"offset": 0, "lines": "INFO starting\n"},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 200, await resp.text()

        broker: WorkerLogBroker = client.app["worker_log_broker"]
        assert "INFO starting" in broker.snapshot(client_id)
    finally:
        await _close(client)


async def test_worker_log_push_requires_auth(tmp_path):
    client = await _make_app(tmp_path)
    try:
        client_id = await _register(client)
        resp = await client.post(
            f"/api/v1/workers/{client_id}/logs",
            json={"offset": 0, "lines": "x\n"},
            # no bearer header
        )
        assert resp.status == 401
    finally:
        await _close(client)


async def test_worker_log_push_oversized_body_rejected(tmp_path):
    """Cap mirrors the job-log path: 4× MAX_LOG_BYTES."""
    client = await _make_app(tmp_path)
    try:
        client_id = await _register(client)
        from job_queue import MAX_LOG_BYTES  # noqa: PLC0415

        huge = "x" * (MAX_LOG_BYTES * 4 + 1024)
        resp = await client.post(
            f"/api/v1/workers/{client_id}/logs",
            json={"offset": 0, "lines": huge},
            headers=AUTH_HEADERS,
        )
        assert resp.status == 413
    finally:
        await _close(client)


# ---------------------------------------------------------------------------
# GET /ui/api/workers/{id}/logs
# ---------------------------------------------------------------------------


async def test_ui_worker_logs_snapshot_returns_buffer(tmp_path):
    client = await _make_app(tmp_path)
    try:
        client_id = await _register(client)
        broker: WorkerLogBroker = client.app["worker_log_broker"]
        broker.append(client_id, offset=0, lines="line1\n")
        broker.append(client_id, offset=6, lines="line2\n")

        resp = await client.get(f"/ui/api/workers/{client_id}/logs")
        assert resp.status == 200
        body = await resp.text()
        assert "line1" in body
        assert "line2" in body
        assert resp.headers["Content-Type"].startswith("text/plain")
    finally:
        await _close(client)


async def test_ui_worker_logs_snapshot_empty_when_unseen(tmp_path):
    client = await _make_app(tmp_path)
    try:
        client_id = await _register(client)
        resp = await client.get(f"/ui/api/workers/{client_id}/logs")
        assert resp.status == 200
        assert (await resp.text()) == ""
    finally:
        await _close(client)


# ---------------------------------------------------------------------------
# WS /ui/api/workers/{id}/logs/ws
# ---------------------------------------------------------------------------


async def test_ws_subscriber_receives_live_push(tmp_path):
    client = await _make_app(tmp_path)
    try:
        client_id = await _register(client)

        ws = await client.ws_connect(f"/ui/api/workers/{client_id}/logs/ws")
        try:
            # Give aiohttp the moment it needs to register the subscriber
            # before we push, so the first chunk isn't racy.
            await asyncio.sleep(0.05)

            # Worker pushes a chunk.
            resp = await client.post(
                f"/api/v1/workers/{client_id}/logs",
                json={"offset": 0, "lines": "live!\n"},
                headers=AUTH_HEADERS,
            )
            assert resp.status == 200

            msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
            assert msg.data == "live!\n"
        finally:
            await ws.close()
    finally:
        await _close(client)


async def test_ws_open_flips_is_watched(tmp_path):
    client = await _make_app(tmp_path)
    try:
        client_id = await _register(client)
        broker: WorkerLogBroker = client.app["worker_log_broker"]

        ws = await client.ws_connect(f"/ui/api/workers/{client_id}/logs/ws")
        try:
            await asyncio.sleep(0.05)
            assert broker.is_watched(client_id) is True
        finally:
            await ws.close()
        await asyncio.sleep(0.05)
        assert broker.is_watched(client_id) is False
    finally:
        await _close(client)
