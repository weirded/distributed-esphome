"""Web UI API handlers (/ui/api/*) — no auth (HA ingress handles it)."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

import aiohttp
from aiohttp import web

from app_config import AppConfig
from device_poller import Device
from job_queue import JobState
from scanner import scan_configs, get_esphome_version, set_esphome_version, get_device_metadata

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()

# Module-level cache: populated once per server lifetime (components don't
# change until ESPHome is upgraded, which restarts the add-on).
_esphome_components_cache: list[str] | None = None


def _cfg(request: web.Request) -> AppConfig:
    return request.app["config"]


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
            import esphome.loader as _loader  # noqa: PLC0415
            comps_path = _Path(_loader.__file__).parent / "components"
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

    return web.json_response({
        "token": cfg.token,
        "port": cfg.port,
        "server_ip": server_ip,
        "server_addresses": addrs,
        "server_client_version": addon_version,
        "addon_version": addon_version,
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
) -> tuple[bool, bool | None]:
    """Return (ha_configured, ha_connected) for a given compile target.

    Matching priority:
    1. MAC address (most reliable — HA identifies ESPHome devices by MAC)
    2. Direct name lookup (friendly_name, esphome.name, filename)
    3. Prefix match against entity locals

    Returns (False, None) when no match is found.
    """
    # 1. MAC address match (authoritative — doesn't depend on naming)
    #    HA connections store MACs as "aa:bb:cc:dd:ee:ff" (lowercase with colons).
    #    Device poller MACs from aioesphomeapi are "AA:BB:CC:DD:EE:FF" (uppercase).
    if device_mac and ha_mac_set:
        mac_lower = device_mac.lower()
        mac_confirmed = mac_lower in ha_mac_set
    else:
        mac_confirmed = False

    if not ha_entity_status and not mac_confirmed:
        return False, None

    # 2. Name matching for connectivity state
    candidates: list[str] = []
    friendly = meta.get("friendly_name")
    if friendly:
        candidates.append(_normalize_for_ha(friendly))
    raw_name = meta.get("device_name_raw")
    if raw_name:
        candidates.append(_normalize_for_ha(raw_name))
    candidates.append(_normalize_for_ha(target.replace(".yaml", "")))

    # Direct lookup
    for norm_name in candidates:
        entry = ha_entity_status.get(norm_name)
        if entry:
            return True, entry.get("connected")

    # Prefix match
    for norm_name in candidates:
        prefix = norm_name + "_"
        for key, entry in ha_entity_status.items():
            if key.startswith(prefix) or key == norm_name:
                return True, entry.get("connected")

    # 3. MAC fragment match — some devices register with HA using internal names
    #    that include MAC fragments (e.g. screek_humen_sensor_1u_c76926 contains
    #    the last 3 bytes of MAC 84:FC:E6:C7:69:26 as "c76926").
    if device_mac:
        mac_suffix = device_mac.upper().replace(":", "")[-6:].lower()  # last 3 bytes
        if mac_suffix and len(mac_suffix) == 6:
            for key, entry in ha_entity_status.items():
                if mac_suffix in key:
                    return True, entry.get("connected")

    # 4. If MAC confirmed via HA device identifiers but name didn't match
    if mac_confirmed:
        return True, None

    return False, None


@routes.get("/ui/api/targets")
async def get_targets(request: web.Request) -> web.Response:
    """List discovered YAML targets with device status."""
    cfg = _cfg(request)
    device_poller = request.app.get("device_poller")
    server_version = get_esphome_version()
    ha_entity_status: dict[str, dict] = request.app.get("ha_entity_status", {})
    ha_mac_set: set[str] = request.app.get("ha_mac_set", set())

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
        ha_configured, ha_connected = _ha_status_for_target(
            ha_entity_status, target, meta, device_mac=device_mac, ha_mac_set=ha_mac_set,
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
            "online": effective_online,
            "running_version": dev.running_version if dev else None,
            "compilation_time": dev.compilation_time if dev else None,
            "config_modified": config_modified,
            "needs_update": (
                dev.running_version != server_version
                if dev and dev.running_version
                else None
            ),
            "ip_address": dev.ip_address if dev else None,
            "last_seen": dev.last_seen.isoformat() if dev and dev.last_seen else None,
            "server_version": server_version,
            "has_api_key": has_api_key,
            "has_web_server": meta["has_web_server"],
            "ha_configured": ha_configured,
            "ha_connected": ha_connected,
        }
        result.append(entry)

    return web.json_response(result)


@routes.get("/ui/api/queue")
async def get_queue(request: web.Request) -> web.Response:
    """Return current job queue state."""
    queue = request.app["queue"]
    jobs = []
    for job in queue.get_all():
        d = job.to_dict()
        # Don't send full log in poll response for active jobs — browser fetches
        # live logs via WebSocket instead
        if d["state"] in ("pending", "working"):
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

        loop = _asyncio.get_event_loop()

        def log_callback(msg: Any) -> None:
            if ws.closed:
                return
            from datetime import datetime as _dt  # noqa: PLC0415
            text = msg.message.decode("utf-8", errors="replace")
            if not text.endswith("\n"):
                text += "\n"
            ts = _dt.now().strftime("[%H:%M:%S] ")
            _asyncio.ensure_future(ws.send_str(ts + text), loop=loop)

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
    """Return known ESPHome devices with version info."""
    device_poller = request.app.get("device_poller")
    server_version = get_esphome_version()

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
        result.append(d)

    return web.json_response(result)


@routes.get("/ui/api/esphome-versions")
async def get_esphome_versions(request: web.Request) -> web.Response:
    """Return ESPHome version state: selected, detected, and available list."""
    selected = get_esphome_version()
    detected = request.app.get("esphome_detected_version")
    available = request.app.get("esphome_available_versions", [])

    # If PyPI list is empty, at least include the currently selected version so
    # the UI has something to show.
    if not available and selected and selected != "unknown":
        available = [selected]

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
    """Start a validation job for a single target (runs esphome config, not compile).

    Body: { "target": "mydevice.yaml" }
    Returns: { "job_id": "..." }
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    target = body.get("target")
    if not target:
        return web.json_response({"error": "target required"}, status=400)

    cfg = _cfg(request)
    queue = request.app["queue"]
    server_version = get_esphome_version()

    job = await queue.enqueue(
        target=target,
        esphome_version=server_version,
        run_id=str(uuid.uuid4()),
        timeout_seconds=cfg.job_timeout,
        validate_only=True,
    )
    if job is None:
        return web.json_response({"error": "Job already queued"}, status=409)
    logger.info("Validation job %s enqueued for target %s", job.id, target)
    return web.json_response({"job_id": job.id})


@routes.post("/ui/api/compile")
async def start_compile(request: web.Request) -> web.Response:
    """Start a compile run.

    Body: { "targets": "all" | "outdated" | ["file.yaml", ...] }
    Returns: { "run_id": "...", "enqueued": N }
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    targets_param = body.get("targets", "all")
    cfg = _cfg(request)
    queue = request.app["queue"]
    device_poller = request.app.get("device_poller")

    server_version = get_esphome_version()
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
        job = await queue.enqueue(
            target=target,
            esphome_version=server_version,
            run_id=run_id,
            timeout_seconds=cfg.job_timeout,
            ota_address=ota_addresses.get(target),
        )
        if job is not None:
            enqueued += 1

    logger.info("Compile run %s: enqueued %d jobs", run_id, enqueued)
    return web.json_response({"run_id": run_id, "enqueued": enqueued})


@routes.get("/ui/api/targets/{filename}/content")
async def get_target_content(request: web.Request) -> web.Response:
    """Return the raw YAML content of a config file."""
    filename = request.match_info["filename"]
    cfg = _cfg(request)
    config_dir = Path(cfg.config_dir)
    path = (config_dir / filename).resolve()
    try:
        path.relative_to(config_dir.resolve())
    except ValueError:
        return web.json_response({"error": "Invalid filename"}, status=400)
    if not path.exists():
        return web.json_response({"error": "File not found"}, status=404)
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)
    return web.json_response({"content": content})


@routes.post("/ui/api/targets/{filename}/content")
async def save_target_content(request: web.Request) -> web.Response:
    """Write raw YAML content back to a config file."""
    filename = request.match_info["filename"]
    cfg = _cfg(request)
    config_dir = Path(cfg.config_dir)
    path = (config_dir / filename).resolve()
    try:
        path.relative_to(config_dir.resolve())
    except ValueError:
        return web.json_response({"error": "Invalid filename"}, status=400)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    content = body.get("content", "")
    try:
        path.write_text(content, encoding="utf-8")
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)
    # Invalidate config cache so changes are picked up immediately
    from scanner import _config_cache  # noqa: PLC0415
    _config_cache.pop(filename, None)
    logger.info("Saved %s (%d bytes)", filename, len(content))
    return web.json_response({"ok": True})


@routes.delete("/ui/api/targets/{filename}")
async def delete_target(request: web.Request) -> web.Response:
    """Delete (or archive) a YAML config file and cancel any pending jobs for it."""
    filename = request.match_info["filename"]
    cfg = _cfg(request)
    config_dir = Path(cfg.config_dir)
    path = (config_dir / filename).resolve()

    # Security: ensure path is within config_dir
    try:
        path.relative_to(config_dir.resolve())
    except ValueError:
        return web.json_response({"error": "Invalid filename"}, status=400)

    if not path.exists():
        return web.json_response({"error": "File not found"}, status=404)

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

    logger.info("Deleted config %s (archive=%s)", filename, archive)
    return web.json_response({"ok": True})


@routes.post("/ui/api/targets/{filename}/rename")
async def rename_target(request: web.Request) -> web.Response:
    """Rename a YAML config file and update the esphome.name field within it."""
    filename = request.match_info["filename"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    new_name = body.get("new_name", "").strip()
    if not new_name:
        return web.json_response({"error": "new_name required"}, status=400)

    cfg = _cfg(request)
    config_dir = Path(cfg.config_dir)
    old_path = (config_dir / filename).resolve()

    # Security: ensure path is within config_dir
    try:
        old_path.relative_to(config_dir.resolve())
    except ValueError:
        return web.json_response({"error": "Invalid filename"}, status=400)

    if not old_path.exists():
        return web.json_response({"error": "File not found"}, status=404)

    # Derive new filename: lowercase, spaces → hyphens, ensure .yaml extension
    new_filename = new_name.replace(" ", "-").lower()
    if not new_filename.endswith(".yaml"):
        new_filename += ".yaml"

    new_path = (config_dir / new_filename).resolve()

    # Security: ensure new path is also within config_dir
    try:
        new_path.relative_to(config_dir.resolve())
    except ValueError:
        return web.json_response({"error": "Invalid new_name"}, status=400)

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
        name_map, enc_keys, addr_overrides = build_name_to_target_map(cfg.config_dir, targets)
        device_poller.update_compile_targets(targets, name_map, enc_keys, addr_overrides)

    logger.info("Renamed config %s → %s", filename, new_filename)

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

    Native API: connect via aioesphomeapi, list entities, find restart button, press it.
    HA fallback: POST /api/services/button/press with button.<name>_restart entity_id.
    """
    import os  # noqa: PLC0415
    import aioesphomeapi as _api  # noqa: PLC0415

    filename = request.match_info["filename"]
    device_poller = request.app.get("device_poller")

    # Try native API restart first — works even without HA integration
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
                    for entity in entities[0]:
                        if hasattr(entity, "object_id") and "restart" in getattr(entity, "object_id", "").lower():
                            if hasattr(entity, "key"):
                                await client.button_command(entity.key)  # type: ignore[func-returns-value]
                                logger.info("Restarted %s via native API (key=%d)", filename, entity.key)
                                return web.json_response({"ok": True, "method": "native_api"})
                finally:
                    await client.disconnect()
            except Exception as exc:
                logger.debug("Native API restart failed for %s: %s — trying HA fallback", filename, exc)

    # Fallback: HA REST API button.press
    meta = get_device_metadata(_cfg(request).config_dir, filename)
    friendly = meta.get("friendly_name")
    raw_name: str = meta.get("device_name_raw") or filename.replace(".yaml", "")
    norm_name = _normalize_for_ha(friendly) if friendly else _normalize_for_ha(raw_name)
    entity_id = f"button.{norm_name}_restart"

    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return web.json_response({"error": "Could not restart device — no native API access and no SUPERVISOR_TOKEN"}, status=500)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://supervisor/core/api/services/button/press",
                headers={"Authorization": f"Bearer {token}"},
                json={"entity_id": entity_id},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    logger.info("Restarted device %s via HA (%s)", filename, entity_id)
                    return web.json_response({"ok": True, "method": "ha_api", "entity_id": entity_id})
                body = await resp.text()
                logger.warning("Restart failed for %s: HTTP %d — %s", entity_id, resp.status, body)
                return web.json_response(
                    {"error": f"HA returned HTTP {resp.status}", "entity_id": entity_id},
                    status=502,
                )
    except Exception as exc:
        logger.warning("Restart failed for %s: %s", entity_id, exc)
        return web.json_response({"error": str(exc)}, status=500)


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

    new_jobs = await queue.retry(job_ids, server_version, str(uuid.uuid4()), cfg.job_timeout)
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
    ha_entity_status: dict[str, dict] = request.app.get("ha_entity_status", {})
    ha_mac_set: set[str] = request.app.get("ha_mac_set", set())
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
        ha_configured, ha_connected = _ha_status_for_target(
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
    path = Path(cfg.config_dir) / "secrets.yaml"
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
    return web.json_response({"cancelled": cancelled})
