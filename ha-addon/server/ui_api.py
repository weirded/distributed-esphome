"""Web UI API handlers (/ui/api/*) — no auth (HA ingress handles it)."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

import aiohttp
from aiohttp import web

from app_config import AppConfig
from helpers import safe_resolve, json_error
from device_poller import Device
from job_queue import JobState
from scanner import (
    create_stub_yaml,
    duplicate_device,
    get_device_metadata,
    get_esphome_version,
    read_device_meta,
    scan_configs,
    set_esphome_version,
    write_device_meta,
)

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


def _broadcast_ws(event_type: str, **payload: object) -> None:
    """Fire a state-change event on the WebSocket bus (#41).

    Thin wrapper around :func:`event_bus.broadcast` so call sites don't
    have to import/except. Silent no-op on any failure — the 30 s HA
    coordinator poll still catches the change.
    """
    try:
        from event_bus import broadcast  # noqa: PLC0415
        broadcast(event_type, **payload)
    except Exception:
        logger.debug("event_bus broadcast failed", exc_info=True)


def _who(request: web.Request) -> str:
    """AU.4: attribution suffix for mutation log lines.

    Returns ``" by <name>"`` when the ha_auth_middleware resolved an HA
    user on this request, empty string otherwise. Used to tack a "by
    stefan" onto log lines like ``Pinned foo.yaml to 2026.4.0`` so
    operators can trace who enqueued what.
    """
    user = request.get("ha_user")
    if not user:
        return ""
    name = user.get("name")
    return f" by {name}" if name else ""

# Module-level cache: populated once per server lifetime (components don't
# change until ESPHome is upgraded, which restarts the add-on).
_esphome_components_cache: list[str] | None = None


def _cfg(request: web.Request) -> AppConfig:
    return request.app["config"]


@routes.get("/ui/api/_debug/scheduler")
async def debug_scheduler(request: web.Request) -> web.Response:
    """Diagnostic endpoint — reports on the APScheduler state (#87)."""
    import scheduler as scheduler_module  # noqa: PLC0415
    return web.json_response({
        "engine": "apscheduler",
        "jobs": scheduler_module.get_jobs_info(),
    })


@routes.get("/ui/api/schedule-history")
async def get_schedule_history(request: web.Request) -> web.Response:
    """Return the schedule fire history for all targets (#81)."""
    import schedule_history  # noqa: PLC0415
    all_history = schedule_history.get_all()
    result: dict[str, list[dict]] = {}
    for target, entries in all_history.items():
        result[target] = [
            {"fired_at": fired_at.isoformat(), "job_id": job_id, "outcome": outcome}
            for fired_at, job_id, outcome in entries
        ]
    return web.json_response(result)


@routes.get("/ui/api/esphome-schema")
async def get_esphome_schema(request: web.Request) -> web.Response:
    """Return ESPHome component names for editor autocomplete.

    Walks the esphome/components directory of the locally installed package so
    the list reflects exactly what is available, rather than a hardcoded subset.
    The result is cached in memory for the lifetime of the server process.
    """
    global _esphome_components_cache
    if _esphome_components_cache is None:
        try:
            from pathlib import Path as _Path  # noqa: PLC0415
            import scanner as _scanner  # noqa: PLC0415

            # SE.5: walk the venv's components directory directly instead of
            # importing esphome.loader. This sidesteps the chicken-and-egg
            # problem where the venv is on sys.path but Python has already
            # cached a half-resolved `esphome` module object from an earlier
            # failed import. When the venv isn't ready yet, fall through to
            # the old import-based path (covers pre-SE.1 bundled package +
            # the test harness).
            comps_path = None
            if _scanner._esphome_ready.is_set() and _scanner._server_esphome_venv:
                import sys as _sys  # noqa: PLC0415
                candidate = (
                    _scanner._server_esphome_venv / "lib"
                    / f"python{_sys.version_info.major}.{_sys.version_info.minor}"
                    / "site-packages" / "esphome" / "components"
                )
                if candidate.is_dir():
                    comps_path = candidate
            if comps_path is None:
                try:
                    import esphome.loader as _loader  # noqa: PLC0415
                    comps_path = _Path(_loader.__file__).parent / "components"
                except ImportError:
                    # Install still in flight and no bundled package —
                    # return an empty list; autocomplete briefly off.
                    logger.info(
                        "ESPHome still installing — components list empty until venv is ready"
                    )
                    return web.json_response({"components": []})

            names = sorted({
                p.stem
                for p in comps_path.iterdir()
                if (p.is_dir() and (p / "__init__.py").exists())
                or (p.suffix == ".py" and p.stem != "__init__")
            })
            # Ensure well-known root keys are always present even if the
            # directory walk misses them (e.g. "esphome" core block).
            for core_key in ("esphome", "substitutions", "packages", "external_components"):
                if core_key not in names:
                    names.append(core_key)
                    names.sort()
            _esphome_components_cache = names
            logger.debug("ESPHome component list cached: %d components", len(names))
        except Exception:
            logger.debug("Could not enumerate ESPHome components", exc_info=True)
            _esphome_components_cache = []
    return web.json_response({"components": _esphome_components_cache})


@routes.get("/ui/api/server-info")
async def get_server_info(request: web.Request) -> web.Response:
    """Return server configuration needed by the UI (token, port, versions)."""
    import socket  # noqa: PLC0415
    from api import _get_server_client_version  # noqa: PLC0415
    cfg = _cfg(request)
    addon_version = _get_server_client_version()

    # Collect all addresses the server is reachable on.
    # Start with hostname, then enumerate all non-loopback IPv4 addresses.
    addrs: list[str] = []
    try:
        hostname = socket.gethostname()
        addrs.append(hostname)
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = str(info[4][0])
            if ip not in addrs and not ip.startswith("127."):
                addrs.append(ip)
    except Exception:
        pass
    # Use a UDP connect trick to find the primary outbound IP (most useful for workers)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        primary_ip = s.getsockname()[0]
        s.close()
        if primary_ip not in addrs:
            addrs.insert(0, primary_ip)
    except Exception:
        pass

    # Backwards-compat: server_ip is the first IP address found (or None)
    ip_addrs = [a for a in addrs if a.replace(".", "").isdigit()]
    server_ip = ip_addrs[0] if ip_addrs else (addrs[0] if addrs else None)

    from constants import MIN_IMAGE_VERSION  # noqa: PLC0415
    return web.json_response({
        "token": cfg.token,
        "port": cfg.port,
        "server_ip": server_ip,
        "server_addresses": addrs,
        "server_client_version": addon_version,
        "addon_version": addon_version,
        "min_image_version": MIN_IMAGE_VERSION,
    })


def _normalize_for_ha(name: str) -> str:
    """Normalize a name to match HA entity_id conventions (underscores, lowercase).

    HA entity IDs strip special characters like &, ', etc. and collapse
    multiple underscores.
    """
    import re  # already imported at module level
    normalized = name.replace("-", "_").replace(" ", "_").lower()
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)  # strip non-alphanumeric
    normalized = re.sub(r"_+", "_", normalized)  # collapse multiple underscores
    return normalized.strip("_")


def _ha_status_for_target(
    ha_entity_status: dict[str, dict],
    target: str,
    meta: dict,
    device_mac: str | None = None,
    ha_mac_set: set[str] | None = None,
    ha_mac_to_device_id: dict[str, str] | None = None,
    ha_name_to_device_id: dict[str, str] | None = None,
) -> tuple[bool, bool | None, str | None]:
    """Return (ha_configured, ha_connected, ha_device_id) for a compile target.

    Matching priority:
    1. MAC address (most reliable — HA identifies ESPHome devices by MAC)
    2. Direct name lookup (friendly_name, esphome.name, filename)
    3. Prefix match against entity locals

    Returns (False, None, None) when no match is found.

    #35: ha_device_id is resolved via MAC match (most reliable).
    #41: falls back to the ha_name_to_device_id map (built from HA entity IDs)
    when no MAC is available — e.g. offline devices that the local mDNS/API
    poller can't reach right now.
    """
    # 1. MAC address match (authoritative — doesn't depend on naming)
    #    HA connections store MACs as "aa:bb:cc:dd:ee:ff" (lowercase with colons).
    #    Device poller MACs from aioesphomeapi are "AA:BB:CC:DD:EE:FF" (uppercase).
    ha_device_id: str | None = None
    if device_mac and ha_mac_set:
        mac_lower = device_mac.lower()
        mac_confirmed = mac_lower in ha_mac_set
        if mac_confirmed and ha_mac_to_device_id:
            ha_device_id = ha_mac_to_device_id.get(mac_lower)
    else:
        mac_confirmed = False

    if not ha_entity_status and not mac_confirmed:
        return False, None, ha_device_id

    # 2. Name matching for connectivity state
    candidates: list[str] = []
    friendly = meta.get("friendly_name")
    if friendly:
        candidates.append(_normalize_for_ha(friendly))
    raw_name = meta.get("device_name_raw")
    if raw_name:
        candidates.append(_normalize_for_ha(raw_name))
    candidates.append(_normalize_for_ha(target.replace(".yaml", "")))

    # Helper: fall back to name-based device_id lookup when we don't have
    # one from the MAC path. Offline devices commonly land here because the
    # local poller has no MAC for them right now.
    def _resolve_id(match_name: str) -> str | None:
        if ha_device_id:
            return ha_device_id
        if ha_name_to_device_id:
            return ha_name_to_device_id.get(match_name)
        return None

    # Direct lookup
    for norm_name in candidates:
        entry = ha_entity_status.get(norm_name)
        if entry:
            return True, entry.get("connected"), _resolve_id(norm_name)

    # Prefix match
    for norm_name in candidates:
        prefix = norm_name + "_"
        for key, entry in ha_entity_status.items():
            if key.startswith(prefix) or key == norm_name:
                return True, entry.get("connected"), _resolve_id(key)

    # 3. MAC fragment match — some devices register with HA using internal names
    #    that include MAC fragments (e.g. screek_humen_sensor_1u_c76926 contains
    #    the last 3 bytes of MAC 84:FC:E6:C7:69:26 as "c76926").
    if device_mac:
        mac_suffix = device_mac.upper().replace(":", "")[-6:].lower()  # last 3 bytes
        if mac_suffix and len(mac_suffix) == 6:
            for key, entry in ha_entity_status.items():
                if mac_suffix in key:
                    return True, entry.get("connected"), _resolve_id(key)

    # 4. If MAC confirmed via HA device identifiers but name didn't match
    if mac_confirmed:
        return True, None, ha_device_id

    return False, None, ha_device_id


@routes.get("/ui/api/targets")
async def get_targets(request: web.Request) -> web.Response:
    """List discovered YAML targets with device status."""
    cfg = _cfg(request)
    device_poller = request.app.get("device_poller")
    server_version = get_esphome_version()
    ha_entity_status: dict[str, dict] = request.app["_rt"].get("ha_entity_status", {})
    ha_mac_set: set[str] = request.app["_rt"].get("ha_mac_set", set())
    ha_mac_to_device_id: dict[str, str] = request.app["_rt"].get("ha_mac_to_device_id", {})
    ha_name_to_device_id: dict[str, str] = request.app["_rt"].get("ha_name_to_device_id", {})

    targets = scan_configs(cfg.config_dir)

    # Build device lookup by compile_target filename
    devices_by_target: dict[str, Device] = {}
    if device_poller:
        for dev in device_poller.get_devices():
            if dev.compile_target:
                devices_by_target[dev.compile_target] = dev

    result = []
    for target in targets:
        dev = devices_by_target.get(target)
        meta = get_device_metadata(cfg.config_dir, target)
        # Detect config changes since last compile
        config_modified = None
        if dev and dev.compilation_time:
            try:
                from datetime import datetime  # noqa: PLC0415
                # compilation_time format: "Mar 29 2026, 17:00:00"
                compile_dt = datetime.strptime(dev.compilation_time, "%b %d %Y, %H:%M:%S")
                config_path = Path(cfg.config_dir) / target
                if config_path.exists():
                    mtime_dt = datetime.fromtimestamp(config_path.stat().st_mtime)
                    config_modified = mtime_dt > compile_dt
            except Exception:
                pass
        # Determine if this target has an API encryption key in its config
        has_api_key = False
        if device_poller and device_poller._encryption_keys:
            for name, _key in device_poller._encryption_keys.items():
                if device_poller._map_target(name) == target:
                    has_api_key = True
                    break

        device_mac = dev.mac_address if dev else None
        ha_configured, ha_connected, ha_device_id = _ha_status_for_target(
            ha_entity_status, target, meta, device_mac=device_mac,
            ha_mac_set=ha_mac_set, ha_mac_to_device_id=ha_mac_to_device_id,
            ha_name_to_device_id=ha_name_to_device_id,
        )

        # 4.2c: Use HA connected state as additional online signal.
        # If the device poller hasn't confirmed online yet but HA says connected,
        # treat the device as online.
        poller_online: bool | None = dev.online if dev else None
        effective_online: bool | None
        if poller_online is not True and ha_connected is True:
            effective_online = True
        else:
            effective_online = poller_online

        entry: dict = {
            "target": target,
            "friendly_name": meta["friendly_name"],
            "device_name": meta["device_name"],
            "comment": meta["comment"],
            "area": meta["area"],
            "project_name": meta["project_name"],
            "project_version": meta["project_version"],
            "online": effective_online,
            "running_version": dev.running_version if dev else None,
            "compilation_time": dev.compilation_time if dev else None,
            "config_modified": config_modified,
            # VP: if the device is pinned, compare against the pinned version
            # instead of the global server version. A pinned device at its
            # pinned version is NOT "outdated" even if the global version is newer.
            "needs_update": (
                dev.running_version != (meta.get("pinned_version") or server_version)
                if dev and dev.running_version
                else None
            ),
            "ip_address": dev.ip_address if dev else None,
            "address_source": dev.address_source if dev else None,
            "last_seen": dev.last_seen.isoformat() if dev and dev.last_seen else None,
            "server_version": server_version,
            "has_api_key": has_api_key,
            "has_web_server": meta["has_web_server"],
            "has_restart_button": meta.get("has_restart_button", False),
            "ha_configured": ha_configured,
            "ha_connected": ha_connected,
            "ha_device_id": ha_device_id,
            # #27: surface MAC so the HA custom integration can merge its
            # target-device with the native ESPHome integration's device
            # via DeviceInfo `connections={(CONNECTION_NETWORK_MAC, mac)}`.
            # Populated by the device poller (mDNS TXT or native API).
            "mac_address": device_mac,
            # #10 — network facts surfaced by the toggleable Net/IP Mode/IPv6/AP columns
            "network_type": meta.get("network_type"),
            "network_static_ip": meta.get("network_static_ip", False),
            "network_ipv6": meta.get("network_ipv6", False),
            "network_ap_fallback": meta.get("network_ap_fallback", False),
            "network_matter": meta.get("network_matter", False),
            # Per-device metadata from the # distributed-esphome: comment block.
            "pinned_version": meta.get("pinned_version"),
            "schedule": meta.get("schedule"),
            "schedule_enabled": meta.get("schedule_enabled", False),
            "schedule_last_run": meta.get("schedule_last_run"),
            "schedule_once": meta.get("schedule_once"),
            # #90: IANA tz name (e.g. "America/Los_Angeles"). Absent for
            # legacy schedules; the scheduler interprets those as UTC.
            "schedule_tz": meta.get("schedule_tz"),
            "tags": meta.get("tags"),
        }
        result.append(entry)

    return web.json_response(result)


@routes.get("/ui/api/queue")
async def get_queue(request: web.Request) -> web.Response:
    """Return current job queue state.

    SP.2: `log` is stripped from EVERY job in the list response. Previously
    only pending/working jobs had their log blanked; terminal jobs carried
    up to 512 KB of log text each, and 10 finished jobs on a 1 Hz SWR poll
    = ~5 MB/s steady-state. The log modal and WebSocket tail both fetch
    per-job via /ui/api/jobs/{id}/log, so the list endpoint doesn't need it.
    """
    queue = request.app["queue"]
    jobs = []
    for job in queue.get_all():
        d = job.to_dict()
        d["log"] = None
        jobs.append(d)
    return web.json_response(jobs)


@routes.get("/ui/api/jobs/{id}/log")
async def get_job_log(request: web.Request) -> web.Response:
    """HTTP fallback for log tailing (used when WebSocket fails)."""
    job_id = request.match_info["id"]
    offset = int(request.rel_url.query.get("offset", "0"))
    queue = request.app["queue"]
    job = queue.get(job_id)
    if not job:
        return web.json_response({"error": "Job not found"}, status=404)
    finished = job.state in (JobState.SUCCESS, JobState.FAILED, JobState.TIMED_OUT)
    full_log = job.log if finished else job._streaming_log
    if full_log is None:
        full_log = ""
    chunk = full_log[offset:]
    return web.json_response({"log": chunk, "offset": len(full_log), "finished": finished})


@routes.get("/ui/api/jobs/{id}/firmware")
async def download_job_firmware(request: web.Request) -> web.Response:
    """FD.6 — download the firmware binary stored for a download-only job."""
    job_id = request.match_info["id"]
    queue = request.app["queue"]
    job = queue.get(job_id)
    if not job:
        return web.json_response({"error": "Job not found"}, status=404)
    if not job.has_firmware:
        return web.json_response({"error": "Firmware not available"}, status=404)

    from firmware_storage import firmware_path  # noqa: PLC0415
    path = firmware_path(job_id)
    if not path.is_file():
        # has_firmware flipped but file disappeared — log and 404.
        logger.warning(
            "Job %s has_firmware=True but %s is missing", job_id, path,
        )
        return web.json_response({"error": "Firmware not available"}, status=404)

    stem = job.target.removesuffix(".yaml").removesuffix(".yml") or job.target
    filename = f"{stem}-{job_id[:8]}.bin"
    return web.FileResponse(
        path=path,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@routes.get("/ui/api/targets/{filename}/logs/ws")
async def ws_device_log(request: web.Request) -> web.WebSocketResponse:
    """WebSocket endpoint for streaming live device logs via the native API."""
    filename = request.match_info["filename"]
    device_poller = request.app.get("device_poller")

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    if not device_poller:
        await ws.send_str("Device poller not available\n")
        await ws.close()
        return ws

    # Find the device for this target
    dev = None
    for d in device_poller.get_devices():
        if d.compile_target == filename:
            dev = d
            break

    if not dev or not dev.ip_address:
        # DL.4: the user-facing "Device not found" error is cryptic when
        # the real issue is a scanner/name-mapping regression. Dump the
        # poller's current view so operators can see whether the target
        # is absent entirely (→ scanner failure, look for a DL.1 WARNING),
        # present but without an IP (→ resolution issue, look at DL.2),
        # or mapped under a slightly different device_name (→ name-
        # normalization). Kept at INFO so it's visible without debug.
        known = [
            {
                "name": d.name,
                "compile_target": d.compile_target,
                "ip_address": d.ip_address,
                "online": d.online,
            }
            for d in device_poller.get_devices()
        ]
        logger.info(
            "ws_device_log: no device for target %r. Poller knows %d "
            "device(s): %s",
            filename, len(known), known,
        )
        await ws.send_str(f"Device not found or no IP address for {filename}\n")
        await ws.close()
        return ws

    noise_psk = device_poller._encryption_keys.get(dev.name)
    addr = device_poller._address_overrides.get(dev.name) or dev.ip_address

    import asyncio as _asyncio  # noqa: PLC0415
    import aioesphomeapi  # noqa: PLC0415
    from aioesphomeapi import LogLevel  # noqa: PLC0415
    from typing import Any  # noqa: PLC0415

    client = aioesphomeapi.APIClient(addr, 6053, password=None, noise_psk=noise_psk)
    unsub = None

    try:
        await ws.send_str(f"Connecting to {dev.name} at {addr}...\n")
        await client.connect(login=True)
        await ws.send_str("Connected. Streaming logs...\n\n")

        # C.8: capture the running loop while we're inside the async context.
        # The log_callback fires from a different thread (aioesphomeapi worker
        # thread), so we cannot call asyncio.get_running_loop() from inside it.
        loop = _asyncio.get_running_loop()

        def log_callback(msg: Any) -> None:
            if ws.closed:
                return
            from datetime import datetime as _dt  # noqa: PLC0415
            text = msg.message.decode("utf-8", errors="replace")
            if not text.endswith("\n"):
                text += "\n"
            ts = _dt.now().strftime("[%H:%M:%S] ")
            # ``run_coroutine_threadsafe`` is the cross-thread analogue of
            # create_task — required because log_callback runs in a worker
            # thread, not on the event loop thread. ``ensure_future(..., loop=)``
            # was the legacy way and is removed in 3.12.
            _asyncio.run_coroutine_threadsafe(ws.send_str(ts + text), loop)

        # subscribe_logs is synchronous and returns an unsubscribe callable.
        unsub = client.subscribe_logs(log_callback, log_level=LogLevel.LOG_LEVEL_VERY_VERBOSE, dump_config=True)

        # Keep the WebSocket open until the browser disconnects.
        async for msg in ws:
            if msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                break

    except Exception as exc:
        logger.debug("Device log WebSocket error for %s: %s", filename, exc)
        try:
            await ws.send_str(f"\nConnection error: {exc}\n")
        except Exception:
            pass
    finally:
        if unsub is not None:
            try:
                unsub()
            except Exception:
                pass
        try:
            await client.disconnect()
        except Exception:
            pass

    return ws


@routes.get("/ui/api/ws/events")
async def ws_events(request: web.Request) -> web.WebSocketResponse:
    """State-change event stream (#41).

    Any client (typically the HA custom integration's coordinator) can
    connect and receive JSON events whenever something changes on the
    server — queue mutations, worker registrations, device discoveries,
    scanner picks-up-new-YAML. Enables real-time entity updates in HA
    without waiting for the 30 s coordinator poll.

    Protocol: server → client JSON messages of the form
    ``{"type": "queue_changed"|"workers_changed"|"targets_changed"|
    "devices_changed", ...}``. No client → server messages expected;
    pings are handled by aiohttp's autoping.
    """
    import asyncio as _asyncio  # noqa: PLC0415
    from event_bus import subscribe, unsubscribe  # noqa: PLC0415

    ws = web.WebSocketResponse(heartbeat=30.0)
    await ws.prepare(request)
    queue = subscribe()
    try:
        # Send an immediate "hello" so clients can distinguish "connected,
        # no events yet" from "not yet connected".
        await ws.send_json({"type": "hello"})
        while not ws.closed:
            try:
                message = await _asyncio.wait_for(queue.get(), timeout=60.0)
            except _asyncio.TimeoutError:
                # Autoping keeps the connection alive; this just lets us
                # check ws.closed and exit cleanly if the peer vanished.
                continue
            try:
                await ws.send_json(message)
            except ConnectionError:
                break
    finally:
        unsubscribe(queue)
    return ws


@routes.get("/ui/api/jobs/{id}/log/ws")
async def ws_browser_log(request: web.Request) -> web.WebSocketResponse:
    """WebSocket endpoint for browser live log tailing."""
    job_id = request.match_info["id"]
    queue = request.app["queue"]

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Send any log content already buffered (streaming or persisted)
    job = queue.get(job_id)
    if job:
        existing = job._streaming_log or job.log or ""
        if existing:
            await ws.send_str(existing)

    # Subscribe for new lines produced while we are connected
    subscribers: dict = request.app.setdefault("log_subscribers", {})
    subscribers.setdefault(job_id, set()).add(ws)

    try:
        async for msg in ws:
            if msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                break
            # Browser may send a keep-alive ping; all other messages are ignored
    finally:
        subscribers.get(job_id, set()).discard(ws)
        if job_id in subscribers and not subscribers[job_id]:
            del subscribers[job_id]

    return ws


async def _get_workers_response(request: web.Request) -> web.Response:
    """Return list of registered build workers with online status."""
    registry = request.app["registry"]
    queue = request.app["queue"]
    cfg = _cfg(request)

    result = []
    for worker in registry.get_all():
        d = worker.to_dict()
        d["online"] = registry.is_online(worker.client_id, cfg.worker_offline_threshold)
        if d.get("current_job_id"):
            job = queue.get(d["current_job_id"])
            if job:
                d["current_job_target"] = job.target
        result.append(d)
    return web.json_response(result)


@routes.get("/ui/api/workers")
async def get_workers(request: web.Request) -> web.Response:
    """Return list of registered build workers with online status."""
    return await _get_workers_response(request)


@routes.get("/ui/api/clients")
async def get_clients(request: web.Request) -> web.Response:
    """Legacy alias for /ui/api/workers — kept for backwards compatibility."""
    return await _get_workers_response(request)


@routes.get("/ui/api/devices")
async def get_devices(request: web.Request) -> web.Response:
    """Return known ESPHome devices with version info.

    Enriches every device — managed *and* unmanaged — with HA configured /
    connected state by cross-referencing the device MAC and name against the
    HA entity registry snapshot. This lets the UI distinguish "random mDNS
    broadcast we happened to pick up" from "real ESPHome device HA also
    knows about, but we don't have its YAML yet" on the unmanaged rows.
    """
    device_poller = request.app.get("device_poller")
    server_version = get_esphome_version()
    ha_entity_status: dict[str, dict] = request.app["_rt"].get("ha_entity_status", {})
    ha_mac_set: set[str] = request.app["_rt"].get("ha_mac_set", set())
    ha_mac_to_device_id: dict[str, str] = request.app["_rt"].get("ha_mac_to_device_id", {})
    ha_name_to_device_id: dict[str, str] = request.app["_rt"].get("ha_name_to_device_id", {})

    if not device_poller:
        return web.json_response([])

    result = []
    for dev in device_poller.get_devices():
        d = dev.to_dict()
        d["server_version"] = server_version
        d["needs_update"] = (
            dev.running_version != server_version
            if dev.running_version
            else None
        )

        # Cross-reference against HA. We synthesise a minimal ``meta`` so we
        # can reuse the same matcher the targets endpoint uses — no
        # friendly_name, just the raw device name.
        meta = {"device_name_raw": dev.name}
        ha_configured, ha_connected, ha_device_id = _ha_status_for_target(
            ha_entity_status,
            target=dev.name,
            meta=meta,
            device_mac=dev.mac_address,
            ha_mac_set=ha_mac_set,
            ha_mac_to_device_id=ha_mac_to_device_id,
            ha_name_to_device_id=ha_name_to_device_id,
        )
        d["ha_configured"] = ha_configured
        d["ha_connected"] = ha_connected
        d["ha_device_id"] = ha_device_id
        result.append(d)

    return web.json_response(result)


@routes.get("/ui/api/esphome-versions")
async def get_esphome_versions(request: web.Request) -> web.Response:
    """Return ESPHome version state: selected, detected, and available list."""
    selected = get_esphome_version()
    detected = request.app["_rt"].get("esphome_detected_version")
    available = request.app["_rt"].get("esphome_available_versions", [])

    # If PyPI list is empty, at least include the currently selected version so
    # the UI has something to show.
    if not available and selected and selected != "unknown":
        available = [selected]

    return web.json_response({
        "selected": selected,
        "detected": detected,
        "available": available,
    })


@routes.post("/ui/api/esphome-versions/refresh")
async def refresh_esphome_versions(request: web.Request) -> web.Response:
    """Force-refresh the PyPI ESPHome version list (bug #19).

    Bypasses the 1-hour server-side TTL so that the Refresh button in the
    header dropdown actually hits PyPI and returns the latest releases —
    previously the UI just re-polled our cached list and showed the same
    versions it already had.
    """
    # Import here to avoid a circular import at module load time.
    from main import _fetch_pypi_versions  # noqa: PLC0415
    import time as _time  # noqa: PLC0415

    async with aiohttp.ClientSession() as session:
        versions = await _fetch_pypi_versions(session)

    if versions:
        request.app["_rt"]["esphome_available_versions"] = versions
        request.app["_rt"]["esphome_versions_fetched_at"] = _time.monotonic()
        logger.info("UI-triggered PyPI refresh: %d versions", len(versions))
    else:
        logger.warning("UI-triggered PyPI refresh returned no versions")

    selected = get_esphome_version()
    detected = request.app["_rt"].get("esphome_detected_version")
    available = versions or request.app["_rt"].get("esphome_available_versions", [])
    return web.json_response({
        "selected": selected,
        "detected": detected,
        "available": available,
    })


@routes.post("/ui/api/esphome-version")
async def set_esphome_version_handler(request: web.Request) -> web.Response:
    """Set the active ESPHome version for new compile jobs.

    Body: { "version": "2026.3.1" }
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    version = body.get("version", "").strip()
    if not version:
        return web.json_response({"error": "version is required"}, status=400)

    set_esphome_version(version)
    logger.info("ESPHome version changed to %s via UI", version)
    return web.json_response({"ok": True, "version": version})


@routes.post("/ui/api/validate")
async def validate_config(request: web.Request) -> web.Response:
    """Validate a target's config by running ``esphome config`` directly
    on the server.

    Body: { "target": "mydevice.yaml" }
    Returns: { "success": true/false, "output": "..." }

    Bug #25: validation now runs as a direct subprocess on the add-on
    server instead of going through the job queue. Rationale:
      - ``esphome config`` only reads YAML files that are already on the
        server's filesystem — no bundle transfer, no worker needed.
      - It's fast (2–5 s) and the result is returned immediately in the
        HTTP response — no queue polling, no log modal, no streaming.
      - Doesn't consume remote worker capacity.
    """
    import asyncio as _asyncio  # noqa: PLC0415

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    target = body.get("target")
    if not target:
        return web.json_response({"error": "target required"}, status=400)

    cfg = _cfg(request)
    config_path = safe_resolve(Path(cfg.config_dir), target)
    if config_path is None or not config_path.exists():
        return json_error("Target file not found", 404)

    # #84: use the correct ESPHome version for validation. If the device is
    # pinned, install that version via the version manager and validate with
    # its binary — not the server's default. This ensures pinned devices
    # validate against the version they'll actually compile with.
    # #48: compare the pin against the ACTUAL installed binary, not the
    # tracked "selected" version (pypi_version_refresher updates the
    # selected version from the HA Supervisor's ESPHome add-on, which can
    # differ from the version bundled in our own container). Otherwise a
    # pin matching the "selected" version silently skips the version-
    # manager install and uses the wrong binary.
    import scanner as _scanner  # noqa: PLC0415
    from scanner import _get_installed_esphome_version  # noqa: PLC0415
    meta = read_device_meta(cfg.config_dir, target)
    pin = meta.get("pin_version")
    # SE.6: default to the lazy-installed venv binary when ready. Pin
    # code path below still runs VersionManager for pinned devices, so
    # those remain decoupled from the server's tracked version.
    if _scanner._esphome_ready.is_set() and _scanner._server_esphome_bin:
        esphome_bin = _scanner._server_esphome_bin
    else:
        # Pre-SE.1 transitional / test-harness fallback: the bundled
        # `esphome` binary on PATH.
        esphome_bin = "esphome"
    installed_binary_version = _get_installed_esphome_version()

    # SE.6: when no pin is set and the venv isn't ready yet, return
    # 503 so the UI can surface "please retry in a moment" instead of
    # shelling into a binary that doesn't exist. Pinned-device path
    # installs its own version via VersionManager regardless.
    if not pin and not _scanner._esphome_ready.is_set():
        # Last-chance: check if the bundled package provides `esphome`
        # on PATH — covers the pre-SE.1 state where no lazy install is
        # needed to validate.
        import shutil as _shutil  # noqa: PLC0415
        if _shutil.which("esphome") is None:
            return web.json_response(
                {
                    "success": False,
                    "output": "ESPHome still installing, please retry in a moment",
                },
                status=503,
            )

    if pin and pin != installed_binary_version:
        try:
            from pathlib import Path as _Path  # noqa: PLC0415
            import sys as _sys  # noqa: PLC0415
            # The version manager lives in the bundled client code
            if "/app/client" not in _sys.path:
                _sys.path.insert(0, "/app/client")
            from version_manager import VersionManager  # noqa: PLC0415
            vm = VersionManager(
                versions_base=_Path("/data/esphome-versions"),
                max_versions=5,
            )
            logger.info("Validating %s: ensuring ESPHome %s is installed for pinned version", target, pin)
            esphome_bin = await _asyncio.get_event_loop().run_in_executor(
                None, vm.ensure_version, pin,
            )
        except Exception as exc:
            logger.warning("Could not install pinned ESPHome %s for validation: %s", pin, exc)
            # Fall back to server default

    logger.info("Validating %s via %s config (direct subprocess)", target, esphome_bin)

    try:
        proc = await _asyncio.create_subprocess_exec(
            esphome_bin, "config", str(config_path),
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.STDOUT,
            cwd=cfg.config_dir,
        )
        stdout, _ = await _asyncio.wait_for(proc.communicate(), timeout=60)
        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        success = proc.returncode == 0
    except _asyncio.TimeoutError:
        return web.json_response(
            {"success": False, "output": "Validation timed out after 60 seconds"},
            status=200,
        )
    except FileNotFoundError:
        return web.json_response(
            {"success": False, "output": "esphome binary not found on the server"},
            status=500,
        )
    except Exception as exc:
        logger.exception("Validation subprocess failed for %s", target)
        return web.json_response(
            {"success": False, "output": f"Internal error: {exc}"},
            status=500,
        )

    if success:
        logger.info("Validation passed for %s", target)
    else:
        logger.warning("Validation failed for %s (exit %d)", target, proc.returncode or -1)
    return web.json_response({"success": success, "output": output})


# ---------------------------------------------------------------------------
# Per-device metadata + schedule + version pinning endpoints
# ---------------------------------------------------------------------------

@routes.post("/ui/api/targets/{filename}/pin")
async def pin_target_version(request: web.Request) -> web.Response:
    """Pin a device to a specific ESPHome version.

    Body: ``{"version": "2026.3.3"}``
    The pin is stored in the ``# distributed-esphome:`` comment block.
    """
    filename = request.match_info["filename"]
    cfg = _cfg(request)
    path = safe_resolve(Path(cfg.config_dir), filename)
    if path is None or not path.exists():
        return json_error("Target not found", 404)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    version = body.get("version", "").strip()
    if not version:
        return web.json_response({"error": "version required"}, status=400)

    meta = read_device_meta(cfg.config_dir, filename)
    meta["pin_version"] = version
    write_device_meta(cfg.config_dir, filename, meta)
    logger.info("Pinned %s to version %s%s", filename, version, _who(request))
    return web.json_response({"ok": True, "pinned_version": version})


@routes.delete("/ui/api/targets/{filename}/pin")
async def unpin_target_version(request: web.Request) -> web.Response:
    """Remove the version pin from a device."""
    filename = request.match_info["filename"]
    cfg = _cfg(request)
    path = safe_resolve(Path(cfg.config_dir), filename)
    if path is None or not path.exists():
        return json_error("Target not found", 404)

    meta = read_device_meta(cfg.config_dir, filename)
    meta.pop("pin_version", None)
    write_device_meta(cfg.config_dir, filename, meta)
    logger.info("Unpinned %s%s", filename, _who(request))
    return web.json_response({"ok": True})

@routes.post("/ui/api/targets/{filename}/meta")
async def update_target_meta(request: web.Request) -> web.Response:
    """Update arbitrary per-device metadata stored in the YAML comment block.

    Body: dict of key→value. ``null`` values delete the key.
    E.g. ``{"pin_version": "2026.3.3", "tags": "office"}``
    """
    filename = request.match_info["filename"]
    cfg = _cfg(request)
    path = safe_resolve(Path(cfg.config_dir), filename)
    if path is None or not path.exists():
        return json_error("Target not found", 404)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "Expected a JSON object"}, status=400)

    meta = read_device_meta(cfg.config_dir, filename)
    for key, value in body.items():
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = value
    write_device_meta(cfg.config_dir, filename, meta)
    logger.info("Updated metadata for %s: %s%s", filename, list(body.keys()), _who(request))
    return web.json_response({"ok": True})


@routes.post("/ui/api/targets/{filename}/schedule")
async def set_target_schedule(request: web.Request) -> web.Response:
    """Set a cron schedule for automatic compile+OTA on a device.

    Body: ``{"cron": "0 2 * * 0"}``
    Returns: ``{"ok": true, "schedule": "...", "schedule_enabled": true}``
    """
    filename = request.match_info["filename"]
    cfg = _cfg(request)
    path = safe_resolve(Path(cfg.config_dir), filename)
    if path is None or not path.exists():
        return json_error("Target not found", 404)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    cron_expr = body.get("cron", "").strip()
    if not cron_expr:
        return web.json_response({"error": "cron expression required"}, status=400)

    # #90: optional `tz` (IANA name like "America/Los_Angeles"). When set,
    # the scheduler interprets the cron expression in that tz. Absent → UTC.
    tz = body.get("tz")
    if tz is not None and not isinstance(tz, str):
        return web.json_response({"error": "tz must be a string"}, status=400)
    if tz:
        try:
            from zoneinfo import ZoneInfo  # noqa: PLC0415
            ZoneInfo(tz)  # raises ZoneInfoNotFoundError if unknown
        except Exception as exc:
            return web.json_response({"error": f"Invalid tz: {exc}"}, status=400)

    # Validate the cron expression.
    try:
        from croniter import croniter  # type: ignore[import-untyped]  # noqa: PLC0415
        croniter(cron_expr)  # raises ValueError if invalid
    except ValueError as exc:
        return web.json_response({"error": f"Invalid cron expression: {exc}"}, status=400)
    except ImportError:
        # croniter not installed — accept the expression unvalidated rather
        # than blocking the feature. The scheduler will log when it can't parse.
        pass

    meta = read_device_meta(cfg.config_dir, filename)
    meta["schedule"] = cron_expr
    meta["schedule_enabled"] = True
    if tz:
        meta["schedule_tz"] = tz
    else:
        # No tz sent: clear any stale tz so the scheduler falls back to UTC.
        meta.pop("schedule_tz", None)
    write_device_meta(cfg.config_dir, filename, meta)
    import scheduler as _sched  # noqa: PLC0415
    _sched.sync_target(filename)
    logger.info("Schedule set for %s: %s (tz=%s)%s", filename, cron_expr, tz or "UTC", _who(request))
    return web.json_response({
        "ok": True,
        "schedule": cron_expr,
        "schedule_enabled": True,
        "schedule_tz": tz,
    })


@routes.delete("/ui/api/targets/{filename}/schedule")
async def delete_target_schedule(request: web.Request) -> web.Response:
    """Remove any schedule (recurring or one-time) from a device.

    #37: previously this only removed the recurring ``schedule`` fields
    (``schedule``, ``schedule_enabled``, ``schedule_last_run``) but left
    ``schedule_once`` intact, so clicking "Remove schedule" on a device
    that had a one-time schedule appeared to succeed but the schedule
    stuck around. Now removes both types.
    """
    filename = request.match_info["filename"]
    cfg = _cfg(request)
    path = safe_resolve(Path(cfg.config_dir), filename)
    if path is None or not path.exists():
        return json_error("Target not found", 404)

    meta = read_device_meta(cfg.config_dir, filename)
    meta.pop("schedule", None)
    meta.pop("schedule_enabled", None)
    meta.pop("schedule_last_run", None)
    meta.pop("schedule_once", None)
    meta.pop("schedule_tz", None)
    write_device_meta(cfg.config_dir, filename, meta)
    import scheduler as _sched  # noqa: PLC0415
    _sched.sync_target(filename)
    logger.info("Schedule removed for %s%s", filename, _who(request))
    return web.json_response({"ok": True})


@routes.post("/ui/api/targets/{filename}/schedule/toggle")
async def toggle_target_schedule(request: web.Request) -> web.Response:
    """Toggle the schedule enabled/disabled without clearing the expression."""
    filename = request.match_info["filename"]
    cfg = _cfg(request)
    path = safe_resolve(Path(cfg.config_dir), filename)
    if path is None or not path.exists():
        return json_error("Target not found", 404)

    meta = read_device_meta(cfg.config_dir, filename)
    if not meta.get("schedule"):
        return web.json_response({"error": "No schedule configured"}, status=400)
    meta["schedule_enabled"] = not meta.get("schedule_enabled", False)
    write_device_meta(cfg.config_dir, filename, meta)
    import scheduler as _sched  # noqa: PLC0415
    _sched.sync_target(filename)
    logger.info("Schedule toggled for %s: enabled=%s%s", filename, meta["schedule_enabled"], _who(request))
    return web.json_response({"ok": True, "schedule_enabled": meta["schedule_enabled"]})


@routes.post("/ui/api/targets/{filename}/schedule/once")
async def set_target_schedule_once(request: web.Request) -> web.Response:
    """Schedule a one-time upgrade at a specific date/time.

    Body: ``{"datetime": "2026-04-15T14:00:00Z"}``

    The scheduler fires the job when the datetime passes, then auto-clears
    the ``schedule_once`` field (no recurring schedule created).
    """
    filename = request.match_info["filename"]
    cfg = _cfg(request)
    path = safe_resolve(Path(cfg.config_dir), filename)
    if path is None or not path.exists():
        return json_error("Target not found", 404)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    dt_str = body.get("datetime", "").strip()
    if not dt_str:
        return web.json_response({"error": "datetime required"}, status=400)

    # Validate it's a parseable ISO datetime.  Allow up to 60s in the past
    # so that "schedule for now" (immediate) doesn't get rejected due to
    # network/processing latency.
    try:
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td  # noqa: PLC0415
        parsed_dt = _dt.fromisoformat(dt_str)
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=_tz.utc)
        if parsed_dt < _dt.now(_tz.utc) - _td(seconds=60):
            return web.json_response({"error": "Datetime must not be in the past"}, status=400)
    except ValueError:
        return web.json_response({"error": "Invalid datetime format (use ISO 8601)"}, status=400)

    meta = read_device_meta(cfg.config_dir, filename)
    meta["schedule_once"] = dt_str
    write_device_meta(cfg.config_dir, filename, meta)
    import scheduler as _sched  # noqa: PLC0415
    _sched.sync_target(filename)
    logger.info("One-time schedule set for %s at %s%s", filename, dt_str, _who(request))
    return web.json_response({"ok": True, "schedule_once": dt_str})


@routes.post("/ui/api/compile")
async def start_compile(request: web.Request) -> web.Response:
    """Start a compile run.

    Body: {
        "targets": "all" | "outdated" | ["file.yaml", ...],
        "pinned_client_id": str | null,    # optional, pin to a specific worker
        "esphome_version": str | null,     # optional, override the global default per-job (#16)
    }
    Returns: { "run_id": "...", "enqueued": N }
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    targets_param = body.get("targets", "all")
    pinned_client_id = body.get("pinned_client_id")  # optional: pin job to specific worker
    # #16: optional per-run ESPHome version override. Falls back to the global
    # default from set_esphome_version when not provided. We do NOT mutate the
    # global default — this is a per-job override only.
    version_override = body.get("esphome_version")
    # FD.2: compile-and-download mode. When true the worker runs
    # `esphome compile` (no OTA), POSTs the produced binary back, and
    # the user downloads it from the Queue tab. Mutually exclusive with
    # validate_only (which isn't exposed through this endpoint anyway).
    download_only = bool(body.get("download_only", False))
    cfg = _cfg(request)
    queue = request.app["queue"]
    device_poller = request.app.get("device_poller")

    server_version = get_esphome_version()
    job_version = version_override or server_version
    all_targets = scan_configs(cfg.config_dir)

    if targets_param == "all":
        selected = all_targets
    elif targets_param == "outdated":
        # Select targets where running version != server version
        if device_poller:
            devices_by_target: dict[str, Device] = {
                dev.compile_target: dev
                for dev in device_poller.get_devices()
                if dev.compile_target
            }
        else:
            devices_by_target = {}

        selected = []
        for t in all_targets:
            dev = devices_by_target.get(t)
            if dev is None:
                # Unknown device state — include it to be safe
                selected.append(t)
            elif dev.running_version != server_version:
                selected.append(t)
    elif isinstance(targets_param, list):
        # Validate that specified targets exist
        valid = set(all_targets)
        selected = [t for t in targets_param if t in valid]
    else:
        return web.json_response({"error": "Invalid targets value"}, status=400)

    # Build a map of target → device IP for OTA addressing
    ota_addresses: dict[str, str] = {}
    if device_poller:
        for dev in device_poller.get_devices():
            if dev.compile_target and dev.ip_address:
                addr = device_poller._address_overrides.get(dev.name) or dev.ip_address
                ota_addresses[dev.compile_target] = addr

    run_id = str(uuid.uuid4())
    enqueued = 0
    for target in selected:
        # VP.7: if the device is pinned to a specific version, use the pinned
        # version for this job — not the global/override version. This ensures
        # bulk "Upgrade All" doesn't accidentally flash pinned devices with
        # the wrong firmware. The version_override from the UI (when set via
        # the UpgradeModal) takes precedence over the pin, since the user
        # explicitly chose it for this specific run.
        effective_version = job_version
        if not version_override:
            device_meta = read_device_meta(cfg.config_dir, target)
            pinned = device_meta.get("pin_version")
            if pinned:
                effective_version = pinned

        job = await queue.enqueue(
            target=target,
            esphome_version=effective_version,
            run_id=run_id,
            timeout_seconds=cfg.job_timeout,
            download_only=download_only,
            ota_address=ota_addresses.get(target),
            pinned_client_id=pinned_client_id,
        )
        if job is not None:
            enqueued += 1

    logger.info(
        "Compile run %s: enqueued %d jobs (version=%s%s%s)%s",
        run_id, enqueued, job_version,
        " (override)" if version_override else "",
        f" pinned={pinned_client_id}" if pinned_client_id else "",
        _who(request),
    )
    return web.json_response({"run_id": run_id, "enqueued": enqueued})


@routes.get("/ui/api/targets/{filename}/content")
async def get_target_content(request: web.Request) -> web.Response:
    """Return the raw YAML content of a config file."""
    filename = request.match_info["filename"]
    cfg = _cfg(request)
    config_dir = Path(cfg.config_dir)
    path = safe_resolve(config_dir, filename)
    if path is None:
        return json_error("Invalid filename")
    if not path.exists():
        return json_error("File not found", 404)
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)
    return web.json_response({"content": content})


@routes.post("/ui/api/targets/{filename}/content")
async def save_target_content(request: web.Request) -> web.Response:
    """Write raw YAML content back to a config file.

    #53/#62: if the filename starts with ``.pending.``, the file is a staged
    new-device. On first save, write the content to the final ``<name>.yaml``
    (stripping the prefix) and delete the pending file. Returns
    ``{"ok": true, "renamed_to": "<name>.yaml"}``.
    """
    filename = request.match_info["filename"]
    cfg = _cfg(request)
    config_dir = Path(cfg.config_dir)
    path = safe_resolve(config_dir, filename)
    if path is None:
        return json_error("Invalid filename")
    try:
        body = await request.json()
    except Exception:
        return json_error("Invalid JSON")
    content = body.get("content", "")

    is_staged = filename.startswith(_PENDING_PREFIX)
    if is_staged:
        final_name = filename[len(_PENDING_PREFIX):]
        final_path = safe_resolve(config_dir, final_name)
        if final_path is None:
            return json_error("Invalid filename")
        if final_path.exists():
            return json_error(f"{final_name} already exists")
        try:
            final_path.write_text(content, encoding="utf-8")
            path.unlink(missing_ok=True)
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)
        logger.info("Saved staged %s → %s (%d bytes)", filename, final_name, len(content))
        return web.json_response({"ok": True, "renamed_to": final_name})

    try:
        path.write_text(content, encoding="utf-8")
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)
    # Invalidate config cache so changes are picked up immediately
    from scanner import _config_cache  # noqa: PLC0415
    _config_cache.pop(filename, None)
    logger.info("Saved %s (%d bytes)%s", filename, len(content), _who(request))
    _broadcast_ws("targets_changed")
    return web.json_response({"ok": True})


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


_PENDING_PREFIX = ".pending."


@routes.post("/ui/api/targets")
async def create_target(request: web.Request) -> web.Response:
    """Create a new device YAML file (CD.3).

    Body: ``{"filename": "<slug>", "source"?: "<existing.yaml>"}``

    - Without ``source``: creates a minimal stub YAML via ``create_stub_yaml``.
    - With ``source``: duplicates the source file and rewrites ``esphome.name``
      to the new filename via ``duplicate_device``.

    #53/#62: the file is written as ``.pending.<name>.yaml`` (a dotfile at the
    config root, invisible to the scanner which skips dotfiles). On first save,
    the save endpoint detects the ``.pending.`` prefix and renames to the final
    ``<name>.yaml``. If the user cancels, the #42 cleanup deletes the dotfile.

    Returns ``{"target": ".pending.<name>.yaml"}`` on success.
    """
    cfg = _cfg(request)
    config_dir = Path(cfg.config_dir)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    raw_name = str(body.get("filename", "")).strip()
    source = body.get("source")

    if not raw_name:
        return json_error("filename required")

    # Strip a ``.yaml`` extension if the caller included it, then validate
    # the slug portion.
    name = raw_name[:-5] if raw_name.lower().endswith(".yaml") else raw_name
    if not _SLUG_RE.match(name):
        return json_error(
            "filename must be lowercase, start with a letter or digit, and "
            "contain only letters, digits, and hyphens",
        )
    if len(name) > 64:
        return json_error("filename too long (max 64 characters)")

    new_filename = f"{name}.yaml"
    # Check for collision with the FINAL name (not the staging name)
    final_dest = safe_resolve(config_dir, new_filename)
    if final_dest is None:
        return json_error("Invalid filename")
    if final_dest.exists():
        return json_error(f"{new_filename} already exists")

    if source:
        src_name = str(source).strip()
        src_path = safe_resolve(config_dir, src_name)
        if src_path is None or not src_path.exists():
            return json_error("Source file not found", 404)
        try:
            yaml_text = duplicate_device(str(config_dir), src_name, name)
        except FileNotFoundError:
            return json_error("Source file not found", 404)
        except ValueError as e:
            return json_error(f"Source invalid: {e}")
    else:
        yaml_text = create_stub_yaml(name)

    # Write as a dotfile so the scanner doesn't pick it up
    pending_filename = f"{_PENDING_PREFIX}{new_filename}"
    staged_path = config_dir / pending_filename
    try:
        staged_path.write_text(yaml_text, encoding="utf-8")
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)

    staged_target = pending_filename
    logger.info("Created staged target %s (source=%s, %d bytes)", staged_target, source or "stub", len(yaml_text))
    return web.json_response({"target": staged_target, "ok": True})


@routes.delete("/ui/api/targets/{filename}")
async def delete_target(request: web.Request) -> web.Response:
    """Delete (or archive) a YAML config file and cancel any pending jobs for it."""
    filename = request.match_info["filename"]
    cfg = _cfg(request)
    config_dir = Path(cfg.config_dir)
    path = safe_resolve(config_dir, filename)
    if path is None:
        return json_error("Invalid filename")

    if not path.exists():
        return json_error("File not found", 404)

    archive = request.rel_url.query.get("archive", "true") == "true"

    try:
        if archive:
            archive_dir = config_dir / ".archive"
            archive_dir.mkdir(exist_ok=True)
            dest = archive_dir / filename
            path.rename(dest)
        else:
            path.unlink()
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)

    # Cancel any pending jobs for this target
    queue = request.app["queue"]
    job_ids = [j.id for j in queue.get_all() if j.target == filename and j.state == JobState.PENDING]
    if job_ids:
        await queue.cancel(job_ids)

    # Invalidate config cache for the deleted file
    from scanner import _config_cache  # noqa: PLC0415
    _config_cache.pop(filename, None)

    logger.info("Deleted config %s (archive=%s)%s", filename, archive, _who(request))
    _broadcast_ws("targets_changed")
    return web.json_response({"ok": True})


@routes.get("/ui/api/archive")
async def list_archive(request: web.Request) -> web.Response:
    """List archived YAML config files."""
    cfg = _cfg(request)
    archive_dir = Path(cfg.config_dir) / ".archive"
    if not archive_dir.exists():
        return web.json_response([])
    files = []
    for f in sorted(archive_dir.iterdir()):
        if f.suffix in (".yaml", ".yml") and f.is_file():
            files.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "archived_at": f.stat().st_mtime,
            })
    return web.json_response(files)


@routes.post("/ui/api/archive/{filename}/restore")
async def restore_archive(request: web.Request) -> web.Response:
    """Restore an archived config file back to the config directory."""
    filename = request.match_info["filename"]
    cfg = _cfg(request)
    config_dir = Path(cfg.config_dir)
    archive_dir = config_dir / ".archive"
    src = safe_resolve(archive_dir, filename)
    if src is None:
        return json_error("Invalid filename")

    if not src.exists():
        return json_error("Archived file not found", 404)

    dest = config_dir / filename
    if dest.exists():
        return web.json_response({"error": f"{filename} already exists in config directory"}, status=409)

    try:
        src.rename(dest)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)

    logger.info("Restored config %s from archive", filename)
    return web.json_response({"ok": True})


@routes.delete("/ui/api/archive/{filename}")
async def delete_archived(request: web.Request) -> web.Response:
    """Permanently delete an archived config file."""
    filename = request.match_info["filename"]
    cfg = _cfg(request)
    archive_dir = Path(cfg.config_dir) / ".archive"
    path = safe_resolve(archive_dir, filename)
    if path is None:
        return json_error("Invalid filename")

    if not path.exists():
        return json_error("File not found", 404)

    try:
        path.unlink()
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)

    logger.info("Permanently deleted archived config %s", filename)
    return web.json_response({"ok": True})


@routes.post("/ui/api/targets/{filename}/rename")
async def rename_target(request: web.Request) -> web.Response:
    """Rename a YAML config file and update the esphome.name field within it."""
    filename = request.match_info["filename"]
    try:
        body = await request.json()
    except Exception:
        return json_error("Invalid JSON")

    new_name = body.get("new_name", "").strip()
    if not new_name:
        return web.json_response({"error": "new_name required"}, status=400)

    cfg = _cfg(request)
    config_dir = Path(cfg.config_dir)
    old_path = safe_resolve(config_dir, filename)
    if old_path is None:
        return json_error("Invalid filename")

    if not old_path.exists():
        return json_error("File not found", 404)

    # Derive new filename: lowercase, spaces → hyphens, ensure .yaml extension
    new_filename = new_name.replace(" ", "-").lower()
    if not new_filename.endswith(".yaml"):
        new_filename += ".yaml"

    new_path = safe_resolve(config_dir, new_filename)
    if new_path is None:
        return json_error("Invalid new_name")

    if new_path.exists() and new_path != old_path:
        return web.json_response({"error": f"{new_filename} already exists"}, status=409)

    try:
        content = old_path.read_text(encoding="utf-8")
        # Update the esphome.name field to match the new filename stem.
        # Matches:  name: old-name  or  name: "old-name"  or  name: 'old-name'
        base_name = new_filename.replace(".yaml", "")
        content = re.sub(
            r"(^\s*name:\s*[\"']?)[\w-]+([\"']?\s*$)",
            rf"\g<1>{base_name}\g<2>",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        new_path.write_text(content, encoding="utf-8")
        if new_path != old_path:
            old_path.unlink()
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)

    # Invalidate config cache and force device poller to rescan
    from scanner import _config_cache, scan_configs, build_name_to_target_map  # noqa: PLC0415
    _config_cache.pop(filename, None)
    _config_cache.pop(new_filename, None)

    # Capture OTA address and remove stale device entry for the old filename.
    # Must happen before rescanning so we can still find the device by old compile_target.
    # After rename, the old mDNS device name no longer maps to any target and
    # would show up as an unmanaged device until mDNS re-discovers the new name.
    device_poller = request.app.get("device_poller")
    old_device_addr = None
    if device_poller:
        old_dev_name = None
        for d in device_poller.get_devices():
            if d.compile_target == filename:
                old_dev_name = d.name
                old_device_addr = device_poller._address_overrides.get(d.name) or d.ip_address
                break
        if old_dev_name and old_dev_name in device_poller._devices:
            del device_poller._devices[old_dev_name]
            logger.debug("Removed stale device entry %s after rename to %s", old_dev_name, new_filename)

    # Force immediate rescan so the UI shows the new name right away
    if device_poller:
        cfg = _cfg(request)
        targets = scan_configs(cfg.config_dir)
        name_map, enc_keys, addr_overrides, addr_sources = build_name_to_target_map(cfg.config_dir, targets)
        device_poller.update_compile_targets(targets, name_map, enc_keys, addr_overrides, addr_sources)

    logger.info("Renamed config %s → %s%s", filename, new_filename, _who(request))
    _broadcast_ws("targets_changed")

    queue = request.app["queue"]
    server_version = get_esphome_version()
    cfg = _cfg(request)
    await queue.enqueue(
        target=new_filename,
        esphome_version=server_version,
        run_id=str(uuid.uuid4()),
        timeout_seconds=cfg.job_timeout,
        ota_address=old_device_addr,
    )
    logger.info("Enqueued compile+OTA for renamed device %s", new_filename)

    return web.json_response({"ok": True, "new_filename": new_filename})


@routes.get("/ui/api/targets/{filename}/api-key")
async def get_api_key(request: web.Request) -> web.Response:
    """Return the ESPHome API encryption key for a target device."""
    filename = request.match_info["filename"]
    device_poller = request.app.get("device_poller")
    if device_poller:
        for name, key in device_poller._encryption_keys.items():
            target = device_poller._map_target(name)
            if target == filename:
                return web.json_response({"key": key})
    return web.json_response({"error": "No API key found"}, status=404)


@routes.post("/ui/api/targets/{filename}/restart")
async def restart_device(request: web.Request) -> web.Response:
    """Restart an ESPHome device via the native API (preferred) or HA button entity (fallback).

    Bug #12: previously the HA fallback called ``button.press`` with a guessed
    entity_id and reported success on HTTP 200 — but HA's button.press service
    returns 200 even for non-existent entities, so a wrong guess silently
    no-op'd. Now:

    1. Native API path is the primary route. Failures are logged at WARNING
       (was DEBUG, so operators couldn't see why it fell through).
    2. HA fallback verifies the entity_id actually exists (GET /states/<id>
       returns 404 for missing entities) before calling button.press.
    3. Multiple entity_id candidates are tried, derived from filename,
       device_name_raw, friendly_name, and the cached HA entity registry.
    4. If no candidate works, the response is a real error with the list of
       candidates that were tried, not a fake "ok".
    """
    import asyncio as _asyncio  # noqa: PLC0415
    import os  # noqa: PLC0415
    import aioesphomeapi as _api  # noqa: PLC0415

    filename = request.match_info["filename"]
    device_poller = request.app.get("device_poller")

    # ------------------------------------------------------------------
    # 1. Native API path — works without HA integration. Connects directly
    #    to the device, lists entities, finds the restart button, presses it.
    # ------------------------------------------------------------------
    native_error: "str | None" = None
    if device_poller:
        dev = None
        for d in device_poller.get_devices():
            if d.compile_target == filename:
                dev = d
                break
        if dev and dev.ip_address:
            noise_psk = device_poller._encryption_keys.get(dev.name)
            addr = device_poller._address_overrides.get(dev.name) or dev.ip_address
            try:
                client = _api.APIClient(addr, 6053, password=None, noise_psk=noise_psk)
                await client.connect(login=True)
                try:
                    entities = await client.list_entities_services()
                    # entities is a tuple: (entities_list, services_list)
                    restart_entity = None
                    for entity in entities[0]:
                        obj_id = getattr(entity, "object_id", "") or ""
                        if "restart" in obj_id.lower() and hasattr(entity, "key"):
                            restart_entity = entity
                            break
                    if restart_entity is not None:
                        client.button_command(restart_entity.key)
                        # Give the protocol a beat to flush before disconnect.
                        # button_command writes to the socket synchronously but
                        # the bytes need to leave the buffer; without this brief
                        # wait the disconnect can race the write.
                        await _asyncio.sleep(0.1)
                        logger.info(
                            "Restarted %s via native API (object_id=%s, key=%d)",
                            filename, getattr(restart_entity, "object_id", "?"), restart_entity.key,
                        )
                        return web.json_response({"ok": True, "method": "native_api"})
                    native_error = "device exposes no restart button entity"
                    logger.warning(
                        "Native API restart for %s: %s — falling back to HA",
                        filename, native_error,
                    )
                finally:
                    await client.disconnect()
            except Exception as exc:
                native_error = str(exc)
                logger.warning(
                    "Native API restart failed for %s: %s — falling back to HA",
                    filename, native_error,
                )
        elif dev is None:
            native_error = "device not found in poller"
        else:
            native_error = "device has no known IP address"

    # ------------------------------------------------------------------
    # 2. HA REST API fallback. Build a list of entity_id candidates and
    #    verify each one exists in HA before pressing.
    # ------------------------------------------------------------------
    meta = get_device_metadata(_cfg(request).config_dir, filename)
    friendly = meta.get("friendly_name")
    raw_name: str = meta.get("device_name_raw") or filename.replace(".yaml", "")
    file_stem = filename.replace(".yaml", "")

    candidate_names: list[str] = []
    for n in (friendly, raw_name, file_stem):
        if n:
            norm = _normalize_for_ha(n)
            if norm and norm not in candidate_names:
                candidate_names.append(norm)
    candidate_entity_ids = [f"button.{n}_restart" for n in candidate_names]

    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return web.json_response(
            {
                "error": "Could not restart device",
                "native_api_error": native_error,
                "ha_fallback_error": "no SUPERVISOR_TOKEN",
                "candidates_tried": [],
            },
            status=500,
        )

    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {token}"}
            tried: list[str] = []
            for entity_id in candidate_entity_ids:
                tried.append(entity_id)
                # Verify the entity exists first — HA's button.press returns
                # 200 even for missing entities, which is why bug #12 went
                # unnoticed.
                async with session.get(
                    f"http://supervisor/core/api/states/{entity_id}",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as state_resp:
                    if state_resp.status != 200:
                        logger.debug(
                            "Restart candidate %s does not exist in HA (HTTP %d)",
                            entity_id, state_resp.status,
                        )
                        continue
                # Entity exists — press the button.
                async with session.post(
                    "http://supervisor/core/api/services/button/press",
                    headers=headers,
                    json={"entity_id": entity_id},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        logger.info("Restarted device %s via HA (%s)", filename, entity_id)
                        return web.json_response(
                            {"ok": True, "method": "ha_api", "entity_id": entity_id},
                        )
                    body = await resp.text()
                    logger.warning(
                        "HA button.press failed for %s: HTTP %d — %s",
                        entity_id, resp.status, body,
                    )
            # No candidate worked.
            logger.warning(
                "Restart failed for %s: native_api=%s, no HA candidate matched (tried %s)",
                filename, native_error or "skipped", tried,
            )
            return web.json_response(
                {
                    "error": "Could not restart device — no native API restart button and no matching HA entity",
                    "native_api_error": native_error,
                    "candidates_tried": tried,
                },
                status=404,
            )
    except Exception as exc:
        logger.warning("Restart failed for %s: %s", filename, exc)
        return web.json_response(
            {
                "error": str(exc),
                "native_api_error": native_error,
                "candidates_tried": candidate_entity_ids,
            },
            status=500,
        )


@routes.post("/ui/api/retry")
async def retry_jobs(request: web.Request) -> web.Response:
    """Re-enqueue failed/timed_out jobs.

    Body: { "job_ids": ["uuid", ...] | "all_failed" }
    Returns: { "retried": N }
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    job_ids_param = body.get("job_ids", [])
    queue = request.app["queue"]
    cfg = _cfg(request)

    server_version = get_esphome_version()

    if job_ids_param == "all_failed":
        job_ids = [
            j.id for j in queue.get_all()
            if j.state in (JobState.FAILED, JobState.TIMED_OUT)
            or (j.state == JobState.SUCCESS and j.ota_result == "failed")
        ]
    elif isinstance(job_ids_param, list):
        job_ids = job_ids_param
    else:
        return web.json_response({"error": "job_ids must be a list or 'all_failed'"}, status=400)

    # #51: build a per-target version map that respects device pins.
    # If a device is pinned to a specific ESPHome version, the retry should
    # use that version — not blindly use the server default.
    target_versions: dict[str, str] = {}
    for jid in job_ids:
        job = queue._jobs.get(jid)
        if job is None:
            continue
        if job.target not in target_versions:
            meta = read_device_meta(cfg.config_dir, job.target)
            pinned = meta.get("pin_version")
            target_versions[job.target] = pinned if pinned else server_version

    new_jobs = await queue.retry(
        job_ids, server_version, str(uuid.uuid4()), cfg.job_timeout,
        target_versions=target_versions,
    )
    return web.json_response({"retried": len(new_jobs)})


async def _remove_worker_handler(request: web.Request, client_id: str) -> web.Response:
    """Remove an offline worker from the registry."""
    registry = request.app["registry"]
    cfg = _cfg(request)

    if registry.is_online(client_id, cfg.worker_offline_threshold):
        return web.json_response({"error": "Cannot remove an online worker"}, status=409)
    if not registry.remove(client_id):
        return web.json_response({"error": "Unknown client_id"}, status=404)
    return web.json_response({"ok": True})


async def _set_disabled_handler(request: web.Request, client_id: str) -> web.Response:
    """Enable or disable a worker."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    disabled = bool(body.get("disabled", True))
    registry = request.app["registry"]
    if not registry.set_disabled(client_id, disabled):
        return web.json_response({"error": "Unknown client_id"}, status=404)
    return web.json_response({"ok": True, "disabled": disabled})


# New worker routes

@routes.delete("/ui/api/workers/{client_id}")
async def remove_worker(request: web.Request) -> web.Response:
    """Remove an offline worker from the registry."""
    return await _remove_worker_handler(request, request.match_info["client_id"])


@routes.post("/ui/api/workers/{client_id}/disable")
async def set_worker_disabled(request: web.Request) -> web.Response:
    """Enable or disable a worker."""
    return await _set_disabled_handler(request, request.match_info["client_id"])


@routes.post("/ui/api/workers/{client_id}/parallel-jobs")
async def set_worker_parallel_jobs(request: web.Request) -> web.Response:
    """Set the requested max_parallel_jobs for a worker. Pushed via next heartbeat."""
    client_id = request.match_info["client_id"]
    registry = request.app["registry"]
    worker = registry.get(client_id)
    if not worker:
        return web.json_response({"error": "Worker not found"}, status=404)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    value = body.get("max_parallel_jobs")
    if not isinstance(value, int) or value < 0 or value > 32:
        return web.json_response({"error": "max_parallel_jobs must be 0-32"}, status=400)
    worker.requested_max_parallel_jobs = value
    logger.info("Worker %s (%s): requested max_parallel_jobs set to %d", client_id, worker.hostname, value)
    # Persist local worker slot count across restarts
    if worker.hostname == "local-worker":
        try:
            Path("/data/local_worker_slots").write_text(str(value))
        except Exception:
            pass
    _broadcast_ws("workers_changed")
    return web.json_response({"ok": True, "max_parallel_jobs": value})


@routes.post("/ui/api/workers/{client_id}/clean")
async def clean_worker_cache(request: web.Request) -> web.Response:
    """Request a worker to clean its build cache. Pushed via next heartbeat."""
    client_id = request.match_info["client_id"]
    registry = request.app["registry"]
    worker = registry.get(client_id)
    if not worker:
        return web.json_response({"error": "Worker not found"}, status=404)
    worker.pending_clean = True
    logger.info("Worker %s (%s): clean build cache requested", client_id, worker.hostname)
    _broadcast_ws("workers_changed")
    return web.json_response({"ok": True})


# Legacy client routes — kept for backwards compatibility

@routes.delete("/ui/api/clients/{client_id}")
async def remove_client(request: web.Request) -> web.Response:
    """Legacy alias for DELETE /ui/api/workers/{client_id}."""
    return await _remove_worker_handler(request, request.match_info["client_id"])


@routes.post("/ui/api/clients/{client_id}/disable")
async def set_client_disabled(request: web.Request) -> web.Response:
    """Legacy alias for POST /ui/api/workers/{client_id}/disable."""
    return await _set_disabled_handler(request, request.match_info["client_id"])


@routes.post("/ui/api/queue/remove")
async def remove_jobs(request: web.Request) -> web.Response:
    """Remove finished jobs from the queue by ID.

    Body: { "ids": ["job-id-1", "job-id-2"] }
    Returns: { "removed": N }
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    job_ids = body.get("ids", [])
    if not isinstance(job_ids, list) or not job_ids:
        return web.json_response({"error": "ids must be a non-empty list"}, status=400)

    queue = request.app["queue"]
    removed = await queue.remove_jobs(job_ids)
    return web.json_response({"removed": removed})


@routes.post("/ui/api/queue/clear")
async def clear_queue(request: web.Request) -> web.Response:
    """Remove terminal jobs from the queue permanently.

    Body: { "states": ["success"] }  or  { "states": ["success", "failed", "timed_out"] }
    Returns: { "cleared": N }
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    states = body.get("states", [])
    if not isinstance(states, list):
        return web.json_response({"error": "states must be a list"}, status=400)

    require_ota_success = bool(body.get("require_ota_success", False))
    queue = request.app["queue"]
    try:
        cleared = await queue.clear(states, require_ota_success=require_ota_success)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"cleared": cleared})


@routes.get("/ui/api/debug/ha-status")
async def debug_ha_status(request: web.Request) -> web.Response:
    """Debug endpoint: show HA entity status keys and matching info per target."""
    cfg = _cfg(request)
    ha_entity_status: dict[str, dict] = request.app["_rt"].get("ha_entity_status", {})
    ha_mac_set: set[str] = request.app["_rt"].get("ha_mac_set", set())
    device_poller = request.app.get("device_poller")
    targets = scan_configs(cfg.config_dir)

    devices_by_target: dict[str, Device] = {}
    if device_poller:
        for dev in device_poller.get_devices():
            if dev.compile_target:
                devices_by_target[dev.compile_target] = dev

    result: dict = {
        "ha_entity_status_keys": sorted(ha_entity_status.keys()),
        "ha_entity_count": len(ha_entity_status),
        "ha_mac_count": len(ha_mac_set),
        "ha_macs": sorted(ha_mac_set),
        "targets": {},
    }
    for target in targets:
        meta = get_device_metadata(cfg.config_dir, target)
        dev = devices_by_target.get(target)
        device_mac = dev.mac_address if dev else None
        ha_configured, ha_connected, _ha_device_id = _ha_status_for_target(
            ha_entity_status, target, meta, device_mac=device_mac, ha_mac_set=ha_mac_set,
        )
        candidates = []
        friendly = meta.get("friendly_name")
        if friendly:
            candidates.append(_normalize_for_ha(friendly))
        raw_name = meta.get("device_name_raw")
        if raw_name:
            candidates.append(_normalize_for_ha(raw_name))
        candidates.append(_normalize_for_ha(target.replace(".yaml", "")))
        result["targets"][target] = {
            "friendly_name": meta.get("friendly_name"),
            "device_name_raw": meta.get("device_name_raw"),
            "device_mac": device_mac,
            "candidates": candidates,
            "ha_configured": ha_configured,
            "ha_connected": ha_connected,
        }
    return web.json_response(result)


@routes.get("/ui/api/secret-keys")
async def get_secret_keys(request: web.Request) -> web.Response:
    """Return list of secret key names from secrets.yaml (values are never sent)."""
    import yaml  # noqa: PLC0415
    cfg = _cfg(request)
    from constants import SECRETS_YAML  # noqa: PLC0415
    path = Path(cfg.config_dir) / SECRETS_YAML
    if not path.exists():
        return web.json_response({"keys": []})
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            return web.json_response({"keys": sorted(str(k) for k in data)})
    except Exception:
        logger.debug("Failed to parse secrets.yaml", exc_info=True)
    return web.json_response({"keys": []})


@routes.post("/ui/api/cancel")
async def cancel_jobs(request: web.Request) -> web.Response:
    """Cancel jobs by id.

    Body: { "job_ids": ["uuid", ...] }
    Returns: { "cancelled": N }
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    job_ids = body.get("job_ids", [])
    if not isinstance(job_ids, list):
        return web.json_response({"error": "job_ids must be a list"}, status=400)

    queue = request.app["queue"]
    cancelled = await queue.cancel(job_ids)
    logger.info("Cancelled %d of %d job(s)%s", cancelled, len(job_ids), _who(request))
    return web.json_response({"cancelled": cancelled})
