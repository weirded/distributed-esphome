"""aiohttp application entry point for the ESPHome Distributed Build Server."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

import aiohttp
from aiohttp import web

import api as api_module
import ui_api as ui_api_module
from app_config import AppConfig
from device_poller import DevicePoller
from job_queue import JobQueue
from registry import WorkerRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

@web.middleware
async def auth_middleware(request: web.Request, handler):
    path = request.path

    # /ui/api/* — no auth; HA handles ingress authentication
    if path.startswith("/ui/api/") or path in ("/", "/index.html"):
        return await handler(request)

    # /api/v1/* — require Bearer token UNLESS from HA supervisor address
    if path.startswith("/api/v1/"):
        peer = request.transport and request.transport.get_extra_info("peername")
        peer_ip = ""
        if peer:
            peer_ip = peer[0] if isinstance(peer, tuple) else str(peer)

        if peer_ip == "172.30.32.2":
            return await handler(request)

        cfg: AppConfig = request.app["config"]
        if cfg.token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header == f"Bearer {cfg.token}":
                return await handler(request)
        else:
            # No token configured — allow all (development mode)
            logger.warning("No auth token configured; allowing unauthenticated request to %s", path)
            return await handler(request)

        return web.json_response({"error": "Unauthorized"}, status=401)

    # Everything else — pass through
    return await handler(request)


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def timeout_checker(app: web.Application) -> None:
    """Background task: check for timed-out jobs every 30 seconds."""
    queue: JobQueue = app["queue"]
    while True:
        await asyncio.sleep(30)
        try:
            timed_out = await queue.check_timeouts()
            if timed_out:
                logger.info("Timeout checker: processed %d timed-out jobs", len(timed_out))
        except Exception:
            logger.exception("Error in timeout checker")


async def config_scanner(app: web.Application) -> None:
    """Background task: re-scan config dir every 30s and update device poller targets."""
    from scanner import scan_configs, build_name_to_target_map  # noqa: PLC0415

    cfg: AppConfig = app["config"]
    device_poller = app.get("device_poller")
    prev_targets: list[str] = []

    while True:
        await asyncio.sleep(30)
        try:
            targets = scan_configs(cfg.config_dir)
            if targets != prev_targets:
                logger.info("Config change detected: %d targets (was %d)", len(targets), len(prev_targets))
                if device_poller:
                    name_map = build_name_to_target_map(cfg.config_dir, targets)
                    device_poller.update_compile_targets(targets, name_map)
                prev_targets = targets
        except Exception:
            logger.exception("Error in config scanner")


# ---------------------------------------------------------------------------
# ESPHome version detection and PyPI version list
# ---------------------------------------------------------------------------

_PYPI_CACHE_TTL = 3600  # seconds


async def _fetch_ha_esphome_version(session: aiohttp.ClientSession) -> Optional[str]:
    """Query the HA Supervisor for the installed ESPHome add-on version.

    Returns the version string, or None if not running inside an HA add-on or
    if the request fails for any reason.
    """
    import os  # noqa: PLC0415
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None

    for slug in ("5c53de3b_esphome", "core_esphome", "local_esphome"):
        try:
            async with session.get(
                f"http://supervisor/addons/{slug}/info",
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    version = data.get("data", {}).get("version")
                    if version:
                        logger.info("Detected HA ESPHome add-on version %s (slug: %s)", version, slug)
                        return str(version)
        except Exception:
            logger.debug("Supervisor query failed for slug %s", slug, exc_info=True)

    return None


async def _fetch_pypi_versions(session: aiohttp.ClientSession, limit: int = 10) -> list[str]:
    """Return recent ESPHome versions from PyPI, newest first."""
    try:
        async with session.get(
            "https://pypi.org/pypi/esphome/json",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                releases = list(data.get("releases", {}).keys())

                def _version_key(v: str) -> list[int]:
                    return [int(x) for x in v.split(".") if x.isdigit()]

                releases.sort(key=_version_key, reverse=True)
                return releases[:limit]
    except Exception:
        logger.debug("Failed to fetch PyPI esphome versions", exc_info=True)
    return []


async def pypi_version_refresher(app: web.Application) -> None:
    """Background task: refresh available ESPHome versions from PyPI every hour."""
    while True:
        await asyncio.sleep(_PYPI_CACHE_TTL)
        try:
            async with aiohttp.ClientSession() as session:
                versions = await _fetch_pypi_versions(session)
            if versions:
                app["esphome_available_versions"] = versions
                app["esphome_versions_fetched_at"] = time.monotonic()
                logger.info("Refreshed PyPI ESPHome version list: %d versions", len(versions))
        except Exception:
            logger.exception("Error refreshing PyPI ESPHome versions")


# ---------------------------------------------------------------------------
# Static file serving with ingress path injection
# ---------------------------------------------------------------------------

async def serve_index(request: web.Request) -> web.Response:
    """Serve index.html with X-Ingress-Path base href injection."""
    try:
        html = INDEX_HTML.read_text(encoding="utf-8")
    except FileNotFoundError:
        return web.Response(status=404, text="index.html not found")

    ingress_path = request.headers.get("X-Ingress-Path", "")
    if ingress_path:
        # Ensure trailing slash for base href
        if not ingress_path.endswith("/"):
            ingress_path += "/"
        html = html.replace(
            '<base href="./">',
            f'<base href="{ingress_path}">',
        )

    return web.Response(
        text=html,
        content_type="text/html",
        charset="utf-8",
    )


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> web.Application:
    cfg = AppConfig.load()

    queue = JobQueue()
    queue.load()

    registry = WorkerRegistry()

    device_poller = DevicePoller(poll_interval=cfg.device_poll_interval)

    app = web.Application(middlewares=[auth_middleware])
    app["config"] = cfg
    app["queue"] = queue
    app["registry"] = registry
    app["scanner_config_dir"] = cfg.config_dir
    app["device_poller"] = device_poller
    app["log_subscribers"] = {}

    # Register routes
    app.router.add_routes(api_module.routes)
    app.router.add_routes(ui_api_module.routes)

    # Static file routes
    app.router.add_get("/", serve_index)
    app.router.add_get("/index.html", serve_index)
    if STATIC_DIR.is_dir():
        app.router.add_static("/static/", path=str(STATIC_DIR), name="static")

    # ESPHome version state — populated during startup
    app["esphome_detected_version"] = None   # version from HA Supervisor (or None)
    app["esphome_available_versions"] = []   # list of versions from PyPI
    app["esphome_versions_fetched_at"] = 0.0

    # Startup/shutdown hooks
    async def on_startup(app: web.Application) -> None:
        logger.info("Starting ESPHome Distributed Build Server")
        logger.info("Config dir: %s", cfg.config_dir)
        logger.info("Token configured: %s", bool(cfg.token))

        # Detect ESPHome version: HA add-on → installed package → "unknown"
        from scanner import (  # noqa: PLC0415
            scan_configs, build_name_to_target_map,
            set_esphome_version, _get_installed_esphome_version,
        )

        async with aiohttp.ClientSession() as session:
            detected = await _fetch_ha_esphome_version(session)
            available = await _fetch_pypi_versions(session)

        app["esphome_detected_version"] = detected
        if available:
            app["esphome_available_versions"] = available
            app["esphome_versions_fetched_at"] = time.monotonic()

        # Select initial version: HA detected → installed package → "unknown"
        selected = detected or _get_installed_esphome_version()
        set_esphome_version(selected)
        logger.info("Active ESPHome version: %s (detected: %s)", selected, detected)

        # Update device poller with known targets
        targets = scan_configs(cfg.config_dir)
        name_map = build_name_to_target_map(cfg.config_dir, targets)
        device_poller.update_compile_targets(targets, name_map)

        # Start device poller
        await device_poller.start(app)

        # Start background tasks
        app["timeout_checker_task"] = asyncio.create_task(timeout_checker(app))
        app["config_scanner_task"] = asyncio.create_task(config_scanner(app))
        app["pypi_version_refresher_task"] = asyncio.create_task(pypi_version_refresher(app))

    async def on_shutdown(app: web.Application) -> None:
        logger.info("Shutting down ESPHome Distributed Build Server")

        for task_name in ("timeout_checker_task", "config_scanner_task", "pypi_version_refresher_task"):
            task = app.get(task_name)
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await device_poller.stop()

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    return app


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cfg = AppConfig.load()
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=cfg.port)
