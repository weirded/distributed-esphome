"""REST API handlers for build workers (/api/v1/*)."""

from __future__ import annotations

import base64
import logging
from functools import lru_cache
from pathlib import Path

import aiohttp
from aiohttp import web

from app_config import AppConfig
from job_queue import JobState
from scanner import create_bundle, get_esphome_version

# Worker code bundled inside this container
_CLIENT_CODE_DIR = Path("/app/client")
_VERSION_FILE = Path("/app/VERSION")


@lru_cache(maxsize=1)
def _get_server_client_version() -> str:
    """Return the add-on version from /app/VERSION (set at image build time)."""
    try:
        return _VERSION_FILE.read_text().strip()
    except Exception:
        return "0.0.1"

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


def _cfg(request: web.Request) -> AppConfig:
    return request.app["config"]


def _check_auth(request: web.Request) -> bool:
    """Return True if the request is authorized."""
    cfg = _cfg(request)
    # Requests from HA supervisor (ingress internal address) are always trusted
    peer = request.transport and request.transport.get_extra_info("peername")
    if peer:
        peer_ip = peer[0] if isinstance(peer, tuple) else str(peer)
        if peer_ip == "172.30.32.2":
            return True
    auth_header = request.headers.get("Authorization", "")
    from helpers import constant_time_compare  # noqa: PLC0415
    if auth_header.startswith("Bearer ") and constant_time_compare(auth_header[7:], cfg.token):
        return True
    return False


def _unauthorized() -> web.Response:
    return web.json_response({"error": "Unauthorized"}, status=401)


async def _register_worker_handler(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    hostname = body.get("hostname", "unknown")
    platform = body.get("platform", "unknown")
    client_version = body.get("client_version")
    existing_client_id = body.get("client_id")
    from helpers import clamp  # noqa: PLC0415
    max_parallel_jobs = clamp(int(body.get("max_parallel_jobs", 1)), 0, 32)
    system_info = body.get("system_info") if isinstance(body.get("system_info"), dict) else None
    registry = request.app["registry"]
    client_id = registry.register(
        hostname, platform, client_version, existing_client_id, max_parallel_jobs, system_info,
    )
    return web.json_response({"client_id": client_id})


async def _heartbeat_handler(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    client_id = body.get("client_id")
    if not client_id:
        return web.json_response({"error": "client_id required"}, status=400)

    system_info = body.get("system_info") if isinstance(body.get("system_info"), dict) else None
    registry = request.app["registry"]
    if not registry.heartbeat(client_id, system_info):
        # Unknown worker — let it re-register
        return web.json_response({"error": "Unknown client_id"}, status=404)

    # Include requested config changes in heartbeat response
    worker = registry.get(client_id)
    resp: dict = {
        "ok": True,
        "server_client_version": _get_server_client_version(),
    }
    if worker and worker.requested_max_parallel_jobs is not None:
        resp["set_max_parallel_jobs"] = worker.requested_max_parallel_jobs
    if worker and worker.pending_clean:
        resp["clean_build_cache"] = True
        worker.pending_clean = False
    return web.json_response(resp)


async def _deregister_handler(request: web.Request) -> web.Response:
    """Remove a worker from the registry on clean shutdown."""
    if not _check_auth(request):
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    client_id = body.get("client_id")
    if not client_id:
        return web.json_response({"error": "client_id required"}, status=400)

    registry = request.app["registry"]
    if registry.remove(client_id):
        logger.info("Worker %s deregistered (clean shutdown)", client_id)
        return web.json_response({"ok": True})
    return web.json_response({"error": "Unknown client_id"}, status=404)


# ---------------------------------------------------------------------------
# New worker routes (preferred)
# ---------------------------------------------------------------------------

@routes.post("/api/v1/workers/register")
async def register_worker(request: web.Request) -> web.Response:
    return await _register_worker_handler(request)


@routes.post("/api/v1/workers/heartbeat")
async def worker_heartbeat(request: web.Request) -> web.Response:
    return await _heartbeat_handler(request)


@routes.post("/api/v1/workers/deregister")
async def deregister_worker(request: web.Request) -> web.Response:
    return await _deregister_handler(request)


# ---------------------------------------------------------------------------
# Legacy client routes — kept for backwards compatibility with deployed workers
# that haven't updated yet. These call the same handlers.
# ---------------------------------------------------------------------------

@routes.post("/api/v1/clients/register")
async def register_client(request: web.Request) -> web.Response:
    return await _register_worker_handler(request)


@routes.post("/api/v1/clients/heartbeat")
async def client_heartbeat(request: web.Request) -> web.Response:
    return await _heartbeat_handler(request)


@routes.post("/api/v1/clients/deregister")
async def deregister_client(request: web.Request) -> web.Response:
    return await _deregister_handler(request)


# ---------------------------------------------------------------------------
# Job routes
# ---------------------------------------------------------------------------

@routes.get("/api/v1/jobs/next")
async def get_next_job(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return _unauthorized()

    client_id = request.headers.get("X-Client-Id") or request.rel_url.query.get("client_id")
    if not client_id:
        return web.json_response({"error": "X-Client-Id header or client_id param required"}, status=400)

    queue = request.app["queue"]
    registry = request.app["registry"]
    cfg = _cfg(request)

    # Don't assign new jobs to disabled workers
    worker = registry.get(client_id)
    if worker and worker.disabled:
        return web.Response(status=204)

    worker_id_str = request.headers.get("X-Worker-Id", "1")
    try:
        worker_id = int(worker_id_str)
    except ValueError:
        worker_id = 1

    hostname = worker.hostname if worker else None

    # Performance-based scheduling: spread jobs across workers, best-available first.
    # Effective score = perf_score * (1 - cpu_usage/100) — factors in both speed and load.
    # Two rules:
    # 1. Defer if ANY online worker has fewer active jobs (spread evenly first)
    # 2. Among workers with equal job counts, defer if one with higher effective score has free slots
    should_defer = False
    if worker:
        my_info = worker.system_info or {}
        my_perf = my_info.get("perf_score", 0)
        my_cpu = my_info.get("cpu_usage")
        my_effective = my_perf * (1 - (my_cpu or 0) / 100)
        cfg_threshold = cfg.worker_offline_threshold
        # Count active jobs per worker from the queue
        active_jobs_by_worker: dict[str, int] = {}
        for j in queue.get_all():
            if j.state == JobState.WORKING and j.assigned_client_id:
                active_jobs_by_worker[j.assigned_client_id] = \
                    active_jobs_by_worker.get(j.assigned_client_id, 0) + 1
        my_active = active_jobs_by_worker.get(client_id, 0)
        for other in registry.get_all():
            if other.client_id == client_id:
                continue
            if other.disabled or not registry.is_online(other.client_id, cfg_threshold):
                continue
            other_active = active_jobs_by_worker.get(other.client_id, 0)
            other_info = other.system_info or {}
            other_perf = other_info.get("perf_score", 0)
            other_cpu = other_info.get("cpu_usage")
            other_effective = other_perf * (1 - (other_cpu or 0) / 100)
            other_free = other_active < other.max_parallel_jobs
            if not other_free:
                continue  # fully busy, ignore
            # Rule 1: another worker has fewer jobs — let them catch up
            if other_active < my_active:
                should_defer = True
                break
            # Rule 2: same job count but higher effective score — let them go first
            if other_active == my_active and other_effective > my_effective:
                should_defer = True
                break

    job = await queue.claim_next(client_id, worker_id, hostname=hostname,
                                  faster_idle_worker_exists=should_defer)
    if job is None:
        return web.Response(status=204)

    # Generate bundle on demand
    try:
        bundle_bytes = create_bundle(cfg.config_dir)
        bundle_b64 = base64.b64encode(bundle_bytes).decode("ascii")
    except Exception:
        logger.exception("Failed to create bundle for job %s", job.id)
        # Release job back to pending
        await queue.cancel([job.id])
        return web.json_response({"error": "Bundle creation failed"}, status=500)

    registry.set_job(client_id, job.id)

    # Include server timezone so worker can match ESPHome's timezone detection.
    # Different timezones produce different config_hash → unnecessary clean rebuilds.
    import time as _time  # noqa: PLC0415
    server_tz = _time.tzname[0] if _time.daylight == 0 else _time.tzname[1]
    try:
        # Prefer the actual TZ env var or read /etc/timezone for the IANA name
        import os as _os  # noqa: PLC0415
        server_tz = _os.environ.get("TZ") or open("/etc/timezone").read().strip() or server_tz
    except Exception:
        pass

    return web.json_response(
        {
            "job_id": job.id,
            "target": job.target,
            "esphome_version": job.esphome_version,
            "bundle_b64": bundle_b64,
            "timeout_seconds": job.timeout_seconds,
            "ota_only": job.ota_only,
            "validate_only": job.validate_only,
            "ota_address": job.ota_address,
            "server_timezone": server_tz,
        }
    )


@routes.post("/api/v1/jobs/{id}/result")
async def submit_job_result(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return _unauthorized()

    job_id = request.match_info["id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    status = body.get("status")
    log = body.get("log")
    ota_result = body.get("ota_result")

    if status not in ("success", "failed"):
        return web.json_response({"error": "status must be 'success' or 'failed'"}, status=400)

    queue = request.app["queue"]
    registry = request.app["registry"]

    # Find the worker that owns this job and update registry
    job = queue.get(job_id)
    if job and job.assigned_client_id:
        registry.set_job(job.assigned_client_id, None)

    ok = await queue.submit_result(job_id, status, log, ota_result)
    if not ok:
        return web.json_response({"error": "Job not found or in unexpected state"}, status=404)

    return web.json_response({"ok": True})


@routes.post("/api/v1/jobs/{id}/status")
async def update_job_status(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return _unauthorized()

    job_id = request.match_info["id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    status_text = body.get("status_text", "")
    queue = request.app["queue"]
    ok = await queue.update_status(job_id, status_text)
    if not ok:
        return web.json_response({"error": "Job not found"}, status=404)
    return web.json_response({"ok": True})


@routes.get("/api/v1/client/version")
async def get_client_version(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return _unauthorized()
    return web.json_response({"version": _get_server_client_version()})


@routes.get("/api/v1/client/code")
async def get_client_code(request: web.Request) -> web.Response:
    """Return all .py files from the bundled worker directory."""
    if not _check_auth(request):
        return _unauthorized()
    base = _CLIENT_CODE_DIR if _CLIENT_CODE_DIR.exists() else Path(__file__).parent
    files = {}
    for path in sorted(base.glob("*.py")):
        if path.name.startswith("._"):
            continue
        try:
            files[path.name] = path.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Failed to read worker file %s", path.name)
    return web.json_response({
        "version": _get_server_client_version(),
        "files": files,
    })


@routes.post("/api/v1/jobs/{id}/log")
async def append_job_log(request: web.Request) -> web.Response:
    """Append streaming log lines from a build worker (HTTP batched)."""
    if not _check_auth(request):
        return _unauthorized()
    job_id = request.match_info["id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    lines = body.get("lines", "")
    queue = request.app["queue"]
    ok = await queue.append_log(job_id, lines)
    if not ok:
        return web.json_response({"error": "Job not found"}, status=404)

    # Forward to any browser WebSocket subscribers
    subscribers: dict = request.app.get("log_subscribers", {})
    for sub_ws in list(subscribers.get(job_id, set())):
        try:
            await sub_ws.send_str(lines)
        except Exception:
            subscribers[job_id].discard(sub_ws)

    return web.json_response({"ok": True})


@routes.get("/api/v1/jobs/{id}/log/ws")
async def ws_worker_log(request: web.Request) -> web.WebSocketResponse:
    """WebSocket endpoint for build workers to stream log lines."""
    if not _check_auth(request):
        return _unauthorized()  # type: ignore[return-value]

    job_id = request.match_info["id"]
    queue = request.app["queue"]
    job = queue.get(job_id)
    if not job:
        return web.json_response({"error": "Job not found"}, status=404)  # type: ignore[return-value]

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    subscribers: dict = request.app.setdefault("log_subscribers", {})
    # The worker WS is a producer; it is not added to subscribers

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            await queue.append_log(job_id, msg.data)
            for sub_ws in list(subscribers.get(job_id, set())):
                try:
                    await sub_ws.send_str(msg.data)
                except Exception:
                    subscribers[job_id].discard(sub_ws)
        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
            break

    return ws


@routes.get("/api/v1/status")
async def get_status(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return _unauthorized()

    cfg = _cfg(request)
    registry = request.app["registry"]
    queue = request.app["queue"]

    online_workers = sum(
        1 for w in registry.get_all() if registry.is_online(w.client_id, cfg.worker_offline_threshold)
    )

    return web.json_response(
        {
            "esphome_version": get_esphome_version(),
            "online_clients": online_workers,  # kept for backwards compatibility
            "online_workers": online_workers,
            "queue_size": queue.queue_size(),
        }
    )
