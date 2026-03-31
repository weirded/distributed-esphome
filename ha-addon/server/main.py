"""aiohttp application entry point for the ESPHome Distributed Build Server."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiohttp import web

import api as api_module
import ui_api as ui_api_module
from app_config import AppConfig
from device_poller import DevicePoller
from job_queue import JobQueue
from registry import ClientRegistry

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

    registry = ClientRegistry()

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

    # Startup/shutdown hooks
    async def on_startup(app: web.Application) -> None:
        logger.info("Starting ESPHome Distributed Build Server")
        logger.info("Config dir: %s", cfg.config_dir)
        logger.info("Token configured: %s", bool(cfg.token))

        # Update device poller with known targets
        from scanner import scan_configs, build_name_to_target_map  # noqa: PLC0415
        targets = scan_configs(cfg.config_dir)
        name_map = build_name_to_target_map(cfg.config_dir, targets)
        device_poller.update_compile_targets(targets, name_map)

        # Start device poller
        await device_poller.start(app)

        # Start background tasks
        app["timeout_checker_task"] = asyncio.create_task(timeout_checker(app))
        app["config_scanner_task"] = asyncio.create_task(config_scanner(app))

    async def on_shutdown(app: web.Application) -> None:
        logger.info("Shutting down ESPHome Distributed Build Server")

        for task_name in ("timeout_checker_task", "config_scanner_task"):
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
