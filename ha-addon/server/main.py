"""aiohttp application entry point for the ESPHome Distributed Build Server."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
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
# Suppress noisy per-request access logs (heartbeats, polls, UI refreshes)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
# Suppress aioesphomeapi connection warnings (expected when devices are offline)
logging.getLogger("aioesphomeapi.connection").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

@web.middleware
async def version_header_middleware(request: web.Request, handler):
    """Attach X-Server-Version header to every response for UI change detection."""
    response = await handler(request)
    from api import _get_server_client_version  # noqa: PLC0415
    response.headers["X-Server-Version"] = _get_server_client_version()
    return response


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
    """Background task: check for timed-out jobs every 30 seconds.
    Also prunes terminal jobs older than 1 hour to keep the queue tidy."""
    queue: JobQueue = app["queue"]
    prune_counter = 0
    while True:
        await asyncio.sleep(30)
        try:
            timed_out = await queue.check_timeouts()
            if timed_out:
                logger.info("Timeout checker: processed %d timed-out jobs", len(timed_out))
            # Prune old finished jobs every ~5 minutes (every 10th cycle)
            prune_counter += 1
            if prune_counter >= 10:
                prune_counter = 0
                pruned = await queue.prune_old_terminal(max_age_seconds=3600)
                if pruned:
                    logger.info("Pruned %d old terminal jobs", pruned)
        except Exception:
            logger.exception("Error in timeout checker")


async def ha_entity_poller(app: web.Application) -> None:
    """Background task: poll HA entity registry every 30s to determine which
    ESPHome devices are configured in Home Assistant and whether they are
    currently connected.

    Requires SUPERVISOR_TOKEN (injected automatically when hassio_api: true).
    Stores results in app["ha_entity_status"]: dict[str, {configured, connected}]
    keyed by normalised device name (hyphens replaced with underscores, lowercase).
    """
    import os  # noqa: PLC0415

    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        logger.info("No SUPERVISOR_TOKEN — HA entity status polling disabled")
        return

    headers = {"Authorization": f"Bearer {token}"}
    timeout = aiohttp.ClientTimeout(total=10)
    first_poll = True

    while True:
        # Poll immediately on first iteration, then every 30s
        if not first_poll:
            await asyncio.sleep(30)
        try:
            import json as _json  # noqa: PLC0415

            async with aiohttp.ClientSession() as session:
                # 1. Use the template API to get ALL ESPHome entity IDs.
                #    This works even for devices without a _status sensor.
                esphome_entity_ids: list[str] = []
                try:
                    async with session.post(
                        "http://supervisor/core/api/template",
                        headers={**headers, "Content-Type": "application/json"},
                        json={"template": "{{ integration_entities('esphome') | list | tojson }}"},
                        timeout=timeout,
                    ) as resp:
                        if resp.status == 200:
                            raw = await resp.text()
                            try:
                                parsed = _json.loads(raw)
                                esphome_entity_ids = parsed if isinstance(parsed, list) else []
                            except (_json.JSONDecodeError, TypeError):
                                logger.warning("HA template API returned unparseable response: %.200s", raw)
                        else:
                            body = await resp.text()
                            logger.warning("HA template API returned HTTP %d: %.200s", resp.status, body)
                except Exception:
                    logger.warning("Template API call failed", exc_info=True)

                # 1b. Get MAC addresses for ESPHome devices via template API.
                # ESPHome devices store MACs in device connections (not identifiers):
                #   connections = [["mac", "50:02:91:3c:11:43"]]
                ha_mac_set: set[str] = set()
                if esphome_entity_ids:
                    try:
                        tmpl = (
                            "{%- set ns = namespace(macs=[], seen=[]) -%}"
                            "{%- for eid in integration_entities('esphome') -%}"
                            "  {%- set did = device_id(eid) -%}"
                            "  {%- if did and did not in ns.seen -%}"
                            "    {%- set ns.seen = ns.seen + [did] -%}"
                            "    {%- set conns = device_attr(did, 'connections') -%}"
                            "    {%- if conns -%}"
                            "      {%- for conn in conns -%}"
                            "        {%- if conn[0] == 'mac' -%}"
                            "          {%- set ns.macs = ns.macs + [conn[1]] -%}"
                            "        {%- endif -%}"
                            "      {%- endfor -%}"
                            "    {%- endif -%}"
                            "  {%- endif -%}"
                            "{%- endfor -%}"
                            "{{ ns.macs | unique | list | tojson }}"
                        )
                        async with session.post(
                            "http://supervisor/core/api/template",
                            headers={**headers, "Content-Type": "application/json"},
                            json={"template": tmpl},
                            timeout=timeout,
                        ) as resp:
                            if resp.status == 200:
                                raw_macs = await resp.text()
                                try:
                                    parsed_macs = _json.loads(raw_macs)
                                    if isinstance(parsed_macs, list):
                                        ha_mac_set = {str(m).lower() for m in parsed_macs}
                                except (_json.JSONDecodeError, TypeError):
                                    pass
                    except Exception:
                        logger.debug("MAC template query failed", exc_info=True)

                # 2. Fetch states for connectivity info
                async with session.get(
                    "http://supervisor/core/api/states",
                    headers=headers,
                    timeout=timeout,
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "HA states returned HTTP %d — check homeassistant_api: true in config.yaml",
                            resp.status,
                        )
                        continue
                    states: list[dict] = await resp.json()

            # Build connectivity map from binary_sensor.*_status with device_class=connectivity
            connectivity: dict[str, bool] = {}  # norm_name → connected
            for entity in states:
                entity_id: str = entity.get("entity_id", "")
                if not entity_id.startswith("binary_sensor.") or not entity_id.endswith("_status"):
                    continue
                attrs = entity.get("attributes") or {}
                if attrs.get("device_class") != "connectivity":
                    continue
                norm_name = entity_id[len("binary_sensor."):-len("_status")]
                connectivity[norm_name] = entity.get("state") == "on"

            # Build ha_status from ESPHome entity IDs (configured) + connectivity
            ha_status: dict[str, dict] = {}

            # Extract unique device name prefixes from entity IDs.
            # ESPHome entities follow the pattern: <domain>.<device_name>_<entity_suffix>
            # We collect all unique prefixes by stripping the domain and finding the
            # longest prefix that matches a connectivity key, or the full local part.
            esphome_device_names: set[str] = set()
            for eid in esphome_entity_ids:
                if "." not in eid:
                    continue
                local = eid.split(".", 1)[1]  # e.g. "nespresso_machine_temperature"
                # Check if any connectivity key is a prefix of this entity
                for conn_name in connectivity:
                    if local == conn_name or local.startswith(conn_name + "_"):
                        esphome_device_names.add(conn_name)
                        break
                else:
                    # No connectivity match — try to derive device name from entity ID.
                    # The _status entity would be the definitive prefix, but it may not
                    # exist. Store the full local as a candidate; _ha_status_for_target
                    # will match by prefix.
                    esphome_device_names.add(local)

            # All connectivity-matched devices get configured=True + connected state
            for name in connectivity:
                ha_status[name] = {"configured": True, "connected": connectivity[name]}

            # All other ESPHome entities mark their device as configured (connected unknown)
            for name in esphome_device_names:
                if name not in ha_status:
                    ha_status[name] = {"configured": True, "connected": None}

            app["ha_entity_status"].clear()
            app["ha_entity_status"].update(ha_status)
            app["ha_mac_set"] = ha_mac_set

            if first_poll:
                first_poll = False
                configured_count = len(ha_status)
                connected_count = sum(1 for v in ha_status.values() if v.get("connected") is not None)
                logger.info(
                    "HA entity poller: %d ESPHome entities from template API, "
                    "%d devices configured, %d with connectivity status",
                    len(esphome_entity_ids),
                    configured_count,
                    connected_count,
                )
            else:
                logger.debug(
                    "HA entity status updated: %d ESPHome devices",
                    len(ha_status),
                )

        except Exception:
            logger.warning("Error polling HA entity status", exc_info=True)


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
                    name_map, enc_keys, addr_overrides = build_name_to_target_map(cfg.config_dir, targets)
                    device_poller.update_compile_targets(targets, name_map, enc_keys, addr_overrides)
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
                        logger.debug("Detected HA ESPHome add-on version %s (slug: %s)", version, slug)
                        return str(version)
                else:
                    logger.warning("Supervisor query for %s returned HTTP %d (need hassio_api: true in config.yaml?)", slug, resp.status)
        except Exception as exc:
            logger.warning("Supervisor query failed for slug %s: %s", slug, exc)

    logger.warning("Could not detect ESPHome add-on version from Supervisor API")
    return None


async def _fetch_pypi_versions(session: aiohttp.ClientSession, limit: int = 50) -> list[str]:
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
    """Background task: refresh PyPI versions hourly and re-check HA ESPHome add-on every 5 min."""
    check_interval = 30   # check HA add-on version every 30 seconds
    pypi_countdown = 0    # fetch PyPI immediately on first loop
    while True:
        await asyncio.sleep(check_interval)
        try:
            async with aiohttp.ClientSession() as session:
                # Re-check HA ESPHome add-on version
                new_detected = await _fetch_ha_esphome_version(session)
                old_detected = app.get("esphome_detected_version")
                if new_detected and new_detected != old_detected:
                    logger.info(
                        "ESPHome add-on version changed: %s → %s",
                        old_detected, new_detected,
                    )
                    app["esphome_detected_version"] = new_detected
                    # Auto-update selected version to match
                    from scanner import set_esphome_version  # noqa: PLC0415
                    set_esphome_version(new_detected)
                    logger.info("Auto-selected ESPHome %s (matches updated add-on)", new_detected)

                # Refresh PyPI list periodically
                pypi_countdown -= check_interval
                if pypi_countdown <= 0:
                    pypi_countdown = _PYPI_CACHE_TTL
                    versions = await _fetch_pypi_versions(session)
                    if versions:
                        app["esphome_available_versions"] = versions
                        app["esphome_versions_fetched_at"] = time.monotonic()
                        logger.info("Refreshed PyPI ESPHome version list: %d versions", len(versions))
        except Exception:
            logger.exception("Error in version refresher")


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

    app = web.Application(middlewares=[version_header_middleware, auth_middleware])
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
        # Serve Vite-built assets at /assets/ (referenced by base-relative URLs in index.html)
        assets_dir = STATIC_DIR / "assets"
        if assets_dir.is_dir():
            app.router.add_static("/assets/", path=str(assets_dir), name="assets")

    # ESPHome version state — populated during startup
    app["esphome_detected_version"] = None   # version from HA Supervisor (or None)
    app["esphome_available_versions"] = []   # list of versions from PyPI
    app["esphome_versions_fetched_at"] = 0.0

    # HA entity status — populated by ha_entity_poller background task
    # dict[str, {"configured": bool, "connected": bool | None}]
    app["ha_entity_status"] = {}

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
        name_map, enc_keys, addr_overrides = build_name_to_target_map(cfg.config_dir, targets)
        device_poller.update_compile_targets(targets, name_map, enc_keys, addr_overrides)

        # Start device poller
        await device_poller.start(app)

        # Start background tasks
        app["timeout_checker_task"] = asyncio.create_task(timeout_checker(app))
        app["config_scanner_task"] = asyncio.create_task(config_scanner(app))
        app["pypi_version_refresher_task"] = asyncio.create_task(pypi_version_refresher(app))
        app["ha_entity_poller_task"] = asyncio.create_task(ha_entity_poller(app))

        # Local worker disabled — HA add-on Alpine image lacks PlatformIO toolchain
        # dependencies (glibc, C compiler toolchains). Use external Docker workers instead.
        # See: https://github.com/weirded/distributed-esphome/issues/4

    async def on_shutdown(app: web.Application) -> None:
        logger.info("Shutting down ESPHome Distributed Build Server")

        for task_name in ("timeout_checker_task", "config_scanner_task", "pypi_version_refresher_task", "ha_entity_poller_task"):
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
