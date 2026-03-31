"""Web UI API handlers (/ui/api/*) — no auth (HA ingress handles it)."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import aiohttp
from aiohttp import web

from app_config import AppConfig
from device_poller import Device
from job_queue import JobState
from scanner import scan_configs, get_esphome_version, get_device_metadata

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


def _cfg(request: web.Request) -> AppConfig:
    return request.app["config"]


@routes.get("/ui/api/server-info")
async def get_server_info(request: web.Request) -> web.Response:
    """Return server configuration needed by the UI (token, port, versions)."""
    from api import _get_server_client_version  # noqa: PLC0415
    cfg = _cfg(request)
    addon_version = _get_server_client_version()
    return web.json_response({
        "token": cfg.token,
        "port": cfg.port,
        "server_client_version": addon_version,
        "addon_version": addon_version,
    })


@routes.get("/ui/api/targets")
async def get_targets(request: web.Request) -> web.Response:
    """List discovered YAML targets with device status."""
    cfg = _cfg(request)
    device_poller = request.app.get("device_poller")
    server_version = get_esphome_version()

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
        entry: dict = {
            "target": target,
            "friendly_name": meta["friendly_name"],
            "device_name": meta["device_name"],
            "comment": meta["comment"],
            "online": dev.online if dev else None,
            "running_version": dev.running_version if dev else None,
            "compilation_time": dev.compilation_time if dev else None,
            "config_modified": config_modified,
            "needs_update": (
                dev.running_version != server_version
                if dev and dev.running_version
                else None
            ),
            "ip_address": dev.ip_address if dev else None,
            "server_version": server_version,
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


@routes.get("/ui/api/clients")
async def get_clients(request: web.Request) -> web.Response:
    """Return list of registered build clients with online status."""
    registry = request.app["registry"]
    queue = request.app["queue"]
    cfg = _cfg(request)

    result = []
    for client in registry.get_all():
        d = client.to_dict()
        d["online"] = registry.is_online(client.client_id, cfg.client_offline_threshold)
        if d.get("current_job_id"):
            job = queue.get(d["current_job_id"])
            if job:
                d["current_job_target"] = job.target
        result.append(d)
    return web.json_response(result)


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

    run_id = str(uuid.uuid4())
    enqueued = 0
    for target in selected:
        job = await queue.enqueue(
            target=target,
            esphome_version=server_version,
            run_id=run_id,
            timeout_seconds=cfg.job_timeout,
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
    logger.info("Saved %s (%d bytes)", filename, len(content))
    return web.json_response({"ok": True})


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


@routes.delete("/ui/api/clients/{client_id}")
async def remove_client(request: web.Request) -> web.Response:
    """Remove an offline client from the registry."""
    client_id = request.match_info["client_id"]
    registry = request.app["registry"]
    cfg = _cfg(request)

    if registry.is_online(client_id, cfg.client_offline_threshold):
        return web.json_response({"error": "Cannot remove an online client"}, status=409)
    if not registry.remove(client_id):
        return web.json_response({"error": "Unknown client_id"}, status=404)
    return web.json_response({"ok": True})


@routes.post("/ui/api/clients/{client_id}/disable")
async def set_client_disabled(request: web.Request) -> web.Response:
    """Enable or disable a client."""
    client_id = request.match_info["client_id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    disabled = bool(body.get("disabled", True))
    registry = request.app["registry"]
    if not registry.set_disabled(client_id, disabled):
        return web.json_response({"error": "Unknown client_id"}, status=404)
    return web.json_response({"ok": True, "disabled": disabled})


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
