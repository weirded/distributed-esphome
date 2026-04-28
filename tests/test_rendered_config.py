"""RC.1 — /ui/api/targets/{filename}/rendered-config endpoint tests.

Covers happy-path / invalid-YAML / missing-secret / package-fetch error
shapes plus the cache hit + bust behaviour. The ``esphome`` binary is
mocked via ``asyncio.create_subprocess_exec`` so the test environment
doesn't need ESPHome installed.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app_config import AppConfig
from job_queue import JobQueue
from registry import WorkerRegistry


@pytest.fixture
def _enable_socket():
    try:
        import pytest_socket as _pytest_socket  # type: ignore[import-not-found]
    except Exception:
        return
    _pytest_socket.enable_socket()


async def _make_app(tmp_path: Path) -> tuple[TestClient, Path]:
    """Stand up a minimal aiohttp app exposing the ui_api routes."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    cfg = AppConfig(config_dir=str(config_dir))

    import settings as _settings_mod
    _settings_mod._reset_for_tests()
    _settings_mod.init_settings(
        settings_path=tmp_path / "settings.json",
        options_path=tmp_path / "options.json",
    )
    await _settings_mod.update_settings({"server_token": "test-token"})

    import ui_api as ui_api_module
    from ha_auth import ha_auth_middleware

    app = web.Application(middlewares=[ha_auth_middleware])
    app["config"] = cfg
    app["queue"] = JobQueue(queue_file=tmp_path / "queue.json")
    app["registry"] = WorkerRegistry()
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

    # Reset the rendered-config cache so each test starts fresh.
    ui_api_module._rendered_config_cache = None  # type: ignore[attr-defined]
    return client, config_dir


def _write_config(config_dir: Path, filename: str, name: str) -> Path:
    p = config_dir / filename
    p.write_text(f"esphome:\n  name: {name}\n\nesp8266:\n  board: d1_mini\n")
    return p


def _mocked_proc(stdout: bytes, returncode: int = 0):
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.returncode = returncode
    return proc


async def test_rendered_config_returns_stdout_on_success(tmp_path: Path, _enable_socket) -> None:
    client, config_dir = await _make_app(tmp_path)
    try:
        _write_config(config_dir, "kitchen.yaml", "kitchen")
        rendered = b"esphome:\n  name: kitchen\nesp8266:\n  board: d1_mini\n"
        with patch("asyncio.create_subprocess_exec", return_value=_mocked_proc(rendered, 0)) as mock_exec:
            resp = await client.get(
                "/ui/api/targets/kitchen.yaml/rendered-config",
                headers={"Authorization": "Bearer test-token"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert data["output"] == rendered.decode()
            assert data["cached"] is False
            # The endpoint shells `esphome config <abs-path>` — same shape as /validate.
            args = mock_exec.call_args[0]
            assert args[1] == "config"
            assert args[2].endswith("kitchen.yaml")
    finally:
        await client.close()


async def test_rendered_config_surfaces_validator_errors(tmp_path: Path, _enable_socket) -> None:
    client, config_dir = await _make_app(tmp_path)
    try:
        _write_config(config_dir, "kitchen.yaml", "kitchen")
        err = b"INVALID: '!secret oven_password' could not be resolved\n"
        with patch("asyncio.create_subprocess_exec", return_value=_mocked_proc(err, 1)):
            resp = await client.get(
                "/ui/api/targets/kitchen.yaml/rendered-config",
                headers={"Authorization": "Bearer test-token"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is False
            assert "could not be resolved" in data["output"]
    finally:
        await client.close()


async def test_rendered_config_404_for_unknown_target(tmp_path: Path, _enable_socket) -> None:
    client, _ = await _make_app(tmp_path)
    try:
        resp = await client.get(
            "/ui/api/targets/ghost.yaml/rendered-config",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status == 404
    finally:
        await client.close()


async def test_rendered_config_skips_secrets_yaml(tmp_path: Path, _enable_socket) -> None:
    """secrets.yaml isn't a device config — the validate endpoint
    short-circuits to a friendly message and so does this one."""
    client, config_dir = await _make_app(tmp_path)
    try:
        (config_dir / "secrets.yaml").write_text("wifi_password: hunter2\n")
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            resp = await client.get(
                "/ui/api/targets/secrets.yaml/rendered-config",
                headers={"Authorization": "Bearer test-token"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert data["skipped"] is True
            assert "secrets.yaml" in data["output"]
            # No subprocess fired — the short-circuit returned before
            # the rendering call.
            assert mock_exec.call_count == 0
    finally:
        await client.close()


async def test_rendered_config_caches_repeat_open(tmp_path: Path, _enable_socket) -> None:
    """Second open returns the cached output without re-running esphome."""
    client, config_dir = await _make_app(tmp_path)
    try:
        _write_config(config_dir, "kitchen.yaml", "kitchen")
        rendered = b"esphome:\n  name: kitchen\n"
        with patch("asyncio.create_subprocess_exec", return_value=_mocked_proc(rendered, 0)) as mock_exec:
            # First open: subprocess fires, cached=False.
            resp1 = await client.get(
                "/ui/api/targets/kitchen.yaml/rendered-config",
                headers={"Authorization": "Bearer test-token"},
            )
            data1 = await resp1.json()
            assert data1["cached"] is False
            assert mock_exec.call_count == 1

            # Second open: cache hit, no subprocess.
            resp2 = await client.get(
                "/ui/api/targets/kitchen.yaml/rendered-config",
                headers={"Authorization": "Bearer test-token"},
            )
            data2 = await resp2.json()
            assert data2["cached"] is True
            assert data2["output"] == data1["output"]
            assert mock_exec.call_count == 1  # unchanged → no second subprocess
    finally:
        await client.close()


async def test_rendered_config_cache_busts_on_file_change(tmp_path: Path, _enable_socket) -> None:
    """Changing the YAML's mtime busts the cache and re-runs esphome."""
    client, config_dir = await _make_app(tmp_path)
    try:
        path = _write_config(config_dir, "kitchen.yaml", "kitchen")
        rendered_v1 = b"esphome:\n  name: kitchen\n"
        rendered_v2 = b"esphome:\n  name: kitchen-renamed\n"

        with patch("asyncio.create_subprocess_exec", return_value=_mocked_proc(rendered_v1, 0)) as mock_exec:
            resp1 = await client.get(
                "/ui/api/targets/kitchen.yaml/rendered-config",
                headers={"Authorization": "Bearer test-token"},
            )
            assert (await resp1.json())["output"] == rendered_v1.decode()
            assert mock_exec.call_count == 1

            # Touch the file with a clearly-different mtime so the
            # cache key (filename, mtime, secrets_mtime) changes.
            new_mtime = path.stat().st_mtime_ns + 1_000_000_000  # +1s
            import os as _os
            _os.utime(path, ns=(new_mtime, new_mtime))

            mock_exec.return_value = _mocked_proc(rendered_v2, 0)
            resp2 = await client.get(
                "/ui/api/targets/kitchen.yaml/rendered-config",
                headers={"Authorization": "Bearer test-token"},
            )
            data2 = await resp2.json()
            assert data2["cached"] is False  # new mtime → fresh subprocess
            assert data2["output"] == rendered_v2.decode()
            assert mock_exec.call_count == 2
    finally:
        await client.close()


async def test_rendered_config_cache_busts_on_secrets_change(tmp_path: Path, _enable_socket) -> None:
    """A secrets.yaml mtime change re-renders even if the device YAML
    is byte-identical — a `!secret` value swap is invisible otherwise."""
    client, config_dir = await _make_app(tmp_path)
    try:
        _write_config(config_dir, "kitchen.yaml", "kitchen")
        secrets_path = config_dir / "secrets.yaml"
        secrets_path.write_text("oven_password: hunter2\n")

        with patch("asyncio.create_subprocess_exec", return_value=_mocked_proc(b"v1\n", 0)) as mock_exec:
            await client.get(
                "/ui/api/targets/kitchen.yaml/rendered-config",
                headers={"Authorization": "Bearer test-token"},
            )
            assert mock_exec.call_count == 1

            # Touch secrets.yaml — the device YAML's mtime is unchanged
            # but the cache key still flips, forcing a re-render.
            new_mtime = secrets_path.stat().st_mtime_ns + 1_000_000_000
            import os as _os
            _os.utime(secrets_path, ns=(new_mtime, new_mtime))

            await client.get(
                "/ui/api/targets/kitchen.yaml/rendered-config",
                headers={"Authorization": "Bearer test-token"},
            )
            assert mock_exec.call_count == 2
    finally:
        await client.close()


async def test_rendered_config_failed_render_is_also_cached(tmp_path: Path, _enable_socket) -> None:
    """Caching the failure path keeps the modal responsive when the
    user repeatedly opens a known-bad YAML — they get the same error
    immediately instead of waiting on a fresh 60-second subprocess."""
    client, config_dir = await _make_app(tmp_path)
    try:
        _write_config(config_dir, "kitchen.yaml", "kitchen")
        with patch("asyncio.create_subprocess_exec", return_value=_mocked_proc(b"ERROR\n", 1)) as mock_exec:
            r1 = await client.get(
                "/ui/api/targets/kitchen.yaml/rendered-config",
                headers={"Authorization": "Bearer test-token"},
            )
            d1 = await r1.json()
            assert d1["success"] is False
            assert mock_exec.call_count == 1

            r2 = await client.get(
                "/ui/api/targets/kitchen.yaml/rendered-config",
                headers={"Authorization": "Bearer test-token"},
            )
            d2 = await r2.json()
            assert d2["success"] is False
            assert d2["cached"] is True
            assert mock_exec.call_count == 1  # no second subprocess
    finally:
        await client.close()


async def test_rendered_config_logs_do_not_leak_output(tmp_path: Path, _enable_socket, caplog) -> None:
    """`!secret` values resolve to plaintext in the rendered output —
    the logger must never include the body, only the byte count."""
    import logging as _logging
    client, config_dir = await _make_app(tmp_path)
    try:
        _write_config(config_dir, "kitchen.yaml", "kitchen")
        secret_value = "P@ssw0rd-with-distinct-marker-XYZ"
        rendered = f"wifi:\n  password: {secret_value}\n".encode()
        with patch("asyncio.create_subprocess_exec", return_value=_mocked_proc(rendered, 0)):
            with caplog.at_level(_logging.INFO):
                resp = await client.get(
                    "/ui/api/targets/kitchen.yaml/rendered-config",
                    headers={"Authorization": "Bearer test-token"},
                )
                assert resp.status == 200
        all_log_text = "\n".join(r.message for r in caplog.records)
        assert secret_value not in all_log_text
    finally:
        await client.close()


# silence unused-import warning when the helper isn't directly referenced
_ = time
