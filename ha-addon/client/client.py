"""ESPHome distributed build worker — polling loop, heartbeat, job runner."""

from __future__ import annotations

import base64
import fcntl
import io
import logging
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

import requests
from pydantic import ValidationError


from protocol import (
    DeregisterRequest,
    HeartbeatRequest,
    HeartbeatResponse,
    JobAssignment,
    JobLogAppend,
    JobResultSubmission,
    JobStatusUpdate,
    RegisterRequest,
    RegisterResponse,
    SystemInfo,
)
from version_manager import VersionManager
from sysinfo import collect_system_info

# ---------------------------------------------------------------------------
# Client version — must match the add-on VERSION file; bumped on each release.
# The server returns this value in heartbeat responses so outdated clients
# can detect the mismatch and self-update.
# ---------------------------------------------------------------------------

CLIENT_VERSION = "1.4.1-dev.71"


def _read_image_version() -> Optional[str]:
    """Read the baked-in Docker image version from IMAGE_VERSION next to this file.

    Returns None if the file is missing (e.g. running from a source checkout
    without a Docker build). The server treats None as "unknown".
    """
    try:
        path = Path(__file__).parent / "IMAGE_VERSION"
        return path.read_text(encoding="utf-8").strip() or None
    except (FileNotFoundError, OSError):
        return None


IMAGE_VERSION = _read_image_version()


# ---------------------------------------------------------------------------
# Logging setup — per-worker context filter
# Injects "[w<N> <target>] " prefix so each line shows which worker slot and
# which YAML file produced it, making parallel build logs easy to follow.
# ---------------------------------------------------------------------------

_log_context = threading.local()


class _WorkerContextFilter(logging.Filter):
    """Inject worker context prefix into every log record from this thread."""

    def filter(self, record: logging.LogRecord) -> bool:
        worker_id = getattr(_log_context, "worker_id", None)
        target = getattr(_log_context, "current_target", None)
        if worker_id is not None:
            if target:
                short = os.path.basename(target).rsplit(".", 1)[0]
                record.ctx = f"[w{worker_id} {short}] "  # type: ignore[attr-defined]
            else:
                record.ctx = f"[w{worker_id}] "  # type: ignore[attr-defined]
        else:
            record.ctx = ""  # type: ignore[attr-defined]
        return True


logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s %(levelname)-8s v{CLIENT_VERSION} %(ctx)s%(name)s: %(message)s",
)
# Attach the filter to the root handler so it runs for every log record.
for _h in logging.getLogger().handlers:
    _h.addFilter(_WorkerContextFilter())
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

SERVER_URL = os.environ["SERVER_URL"].rstrip("/")
SERVER_TOKEN = os.environ["SERVER_TOKEN"]
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "1"))
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "10"))
JOB_TIMEOUT = int(os.environ.get("JOB_TIMEOUT", "600"))
OTA_TIMEOUT = int(os.environ.get("OTA_TIMEOUT", "120"))
MAX_ESPHOME_VERSIONS = int(os.environ.get("MAX_ESPHOME_VERSIONS", "3"))
MAX_PARALLEL_JOBS = int(os.environ.get("MAX_PARALLEL_JOBS", "2"))
HOSTNAME = os.environ.get("HOSTNAME", socket.gethostname())
PLATFORM = os.environ.get("PLATFORM", sys.platform)
ESPHOME_BIN = os.environ.get("ESPHOME_BIN")  # If set, skip version manager
ESPHOME_SEED_VERSION = os.environ.get("ESPHOME_SEED_VERSION")  # Pre-download on startup
# Base directory for per-slot PlatformIO core dirs (avoids cross-slot conflicts)
_ESPHOME_VERSIONS_DIR = os.environ.get("ESPHOME_VERSIONS_DIR", "/esphome-versions")
# Persistent client identity file — survives container restarts
_CLIENT_ID_FILE = os.path.join(_ESPHOME_VERSIONS_DIR, ".client_id")

HEADERS = {
    "Authorization": f"Bearer {SERVER_TOKEN}",
    "Content-Type": "application/json",
}

# Set when the heartbeat detects a newer server-side client bundle.
# Checked in the main loop so updates only happen between jobs.
_update_available: threading.Event = threading.Event()

# Sticky flag so we only log the "image upgrade required" warning once
# per process rather than on every heartbeat.
_image_upgrade_logged: bool = False

# Active job counter — incremented/decremented by run_job(); main loop
# waits for this to reach zero before applying updates or re-registering.
_active_jobs: int = 0
_active_jobs_lock: threading.Lock = threading.Lock()

# ---------------------------------------------------------------------------
# Connectivity / auth state — deduplicate repeated log messages
# ---------------------------------------------------------------------------
# Touched by both the heartbeat thread and the worker poll loops. The GIL
# makes individual bool reads atomic, but the test-then-set pattern in the
# helpers below is a race: two threads can both pass the ``if`` check before
# either flips the flag, causing duplicate "went offline" log lines. C.1 wraps
# the test-then-set in a single shared lock.
_state_lock: threading.Lock = threading.Lock()
_server_reachable: bool = True   # False once we've logged "server offline"
_auth_ok: bool = True            # False once we've logged "auth failed"
_reregister_needed: threading.Event = threading.Event()  # set by heartbeat on 404


def _is_idle() -> bool:
    """Return True when no jobs are currently running across all workers."""
    with _active_jobs_lock:
        return _active_jobs == 0


def _on_server_unreachable(exc: Exception) -> None:
    global _server_reachable
    with _state_lock:
        if not _server_reachable:
            return
        _server_reachable = False
    logger.warning("Server went offline: %s", exc)


def _on_server_reachable() -> None:
    global _server_reachable
    with _state_lock:
        if _server_reachable:
            return
        _server_reachable = True
    logger.info("Server came back online")


def _on_auth_failed() -> None:
    global _auth_ok
    with _state_lock:
        if not _auth_ok:
            return
        _auth_ok = False
    logger.warning("Authentication failed (token mismatch?) — will keep retrying silently")


def _on_auth_ok() -> None:
    global _auth_ok
    with _state_lock:
        if _auth_ok:
            return
        _auth_ok = True
    logger.info("Authentication restored")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def post(path: str, data: dict, timeout: int = 30) -> requests.Response:
    url = f"{SERVER_URL}{path}"
    return requests.post(url, json=data, headers=HEADERS, timeout=timeout)


def get(path: str, params: Optional[dict] = None, timeout: int = 30) -> requests.Response:
    url = f"{SERVER_URL}{path}"
    return requests.get(url, params=params, headers={**HEADERS, "Content-Type": "application/json"}, timeout=timeout)


def post_bytes(
    path: str, data: bytes, timeout: int = 600, client_id: Optional[str] = None,
) -> requests.Response:
    """POST raw bytes (e.g. firmware uploads — FD.5). 10 min default timeout.

    *client_id* is included as `X-Client-Id` so the server can validate
    that the caller is the worker currently assigned to the job (bug
    #24 / audit F-08). Omit only for test scaffolding.
    """
    url = f"{SERVER_URL}{path}"
    headers = {**HEADERS, "Content-Type": "application/octet-stream"}
    if client_id:
        headers["X-Client-Id"] = client_id
    return requests.post(url, data=data, headers=headers, timeout=timeout)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def _load_client_id() -> Optional[str]:
    """Load persisted client_id from disk (survives container restarts)."""
    # Environment override (set by auto-update before os.execv)
    env_id = os.environ.pop("DISTRIBUTED_ESPHOME_CLIENT_ID", None)
    if env_id:
        return env_id
    try:
        if os.path.exists(_CLIENT_ID_FILE):
            with open(_CLIENT_ID_FILE, encoding="utf-8") as f:
                cid = f.read().strip()
                if cid:
                    return cid
    except OSError:
        logger.debug("Could not read client_id file: %s", _CLIENT_ID_FILE, exc_info=True)
    return None


def _save_client_id(client_id: str) -> None:
    """Persist client_id to disk."""
    try:
        os.makedirs(os.path.dirname(_CLIENT_ID_FILE), exist_ok=True)
        with open(_CLIENT_ID_FILE, "w", encoding="utf-8") as f:
            f.write(client_id)
    except OSError as exc:
        logger.debug("Could not persist client_id: %s", exc)


def _clear_client_id() -> None:
    """Remove persisted client_id (on clean deregister)."""
    try:
        if os.path.exists(_CLIENT_ID_FILE):
            os.remove(_CLIENT_ID_FILE)
    except OSError:
        logger.debug("Could not remove client_id file: %s", _CLIENT_ID_FILE, exc_info=True)


def deregister(client_id: str) -> None:
    """Tell the server to remove this worker (best-effort on shutdown)."""
    try:
        resp = post(
            "/api/v1/workers/deregister",
            DeregisterRequest(client_id=client_id).model_dump(),
        )
        if resp.ok:
            logger.info("Deregistered worker %s", client_id)
            _clear_client_id()
        else:
            logger.debug("Deregister returned %s", resp.status_code)
    except Exception as exc:
        logger.debug("Deregister failed: %s", exc)


def register() -> str:
    """Register with server and return client_id. Retries until successful.

    Re-uses a persisted client_id so the server recognises us across restarts.
    """
    existing_id = _load_client_id()
    while True:
        try:
            sysinfo = collect_system_info(_ESPHOME_VERSIONS_DIR)
            req = RegisterRequest(
                hostname=HOSTNAME,
                platform=PLATFORM,
                client_version=CLIENT_VERSION,
                image_version=IMAGE_VERSION,
                client_id=existing_id,
                max_parallel_jobs=MAX_PARALLEL_JOBS,
                system_info=SystemInfo.model_validate(sysinfo),
            )
            resp = post("/api/v1/workers/register", req.model_dump(exclude_none=True))
            resp.raise_for_status()
            try:
                parsed = RegisterResponse.model_validate(resp.json())
            except ValidationError as exc:
                raise RuntimeError(f"malformed register response: {exc}") from exc
            client_id = parsed.client_id
            _save_client_id(client_id)
            logger.info("Registered as worker %s (version %s)", client_id, CLIENT_VERSION)
            logger.info(
                "System: %s | %s | %s cores | %s | %s",
                sysinfo.get("os_version", "?"),
                sysinfo.get("cpu_model", "?"),
                sysinfo.get("cpu_cores", "?"),
                sysinfo.get("total_memory", "?"),
                sysinfo.get("cpu_arch", "?"),
            )
            return client_id
        except Exception as exc:
            logger.warning("Registration failed: %s; retrying in 5s", exc)
            time.sleep(5)


# ---------------------------------------------------------------------------
# Heartbeat thread
# ---------------------------------------------------------------------------

def _restart_self() -> None:
    """Restart the worker process in-place (preserving env vars)."""
    logger.info("Restarting worker process...")
    os.execv(sys.executable, [sys.executable] + sys.argv)


def _clean_build_cache() -> None:
    """Remove all build artifacts from the esphome-versions directory."""
    import shutil
    from version_manager import VERSIONS_BASE
    base = Path(VERSIONS_BASE)
    if not base.exists():
        logger.info("No build cache to clean (%s does not exist)", base)
        return
    removed = 0
    for entry in base.iterdir():
        if entry.is_dir():
            try:
                shutil.rmtree(entry)
                removed += 1
                logger.info("Removed %s", entry.name)
            except Exception as exc:
                logger.warning("Failed to remove %s: %s", entry.name, exc)
    logger.info("Build cache clean complete — removed %d version(s)", removed)


def heartbeat_loop(client_id: str, stop_event: threading.Event) -> None:
    """Send heartbeats to the server until stop_event is set."""
    global _image_upgrade_logged
    while not stop_event.is_set():
        try:
            hb = HeartbeatRequest(
                client_id=client_id,
                system_info=SystemInfo.model_validate(collect_system_info(_ESPHOME_VERSIONS_DIR)),
            )
            resp = post("/api/v1/workers/heartbeat", hb.model_dump(exclude_none=True))
            if resp.status_code == 401:
                _on_auth_failed()
            elif resp.status_code == 404:
                # Server doesn't recognise us — signal main loop to re-register.
                # Log only on the first occurrence; the main loop will clear this.
                if not _reregister_needed.is_set():
                    logger.warning("Server does not know us; will re-register")
                _reregister_needed.set()
            elif resp.ok:
                _on_server_reachable()
                _on_auth_ok()
                try:
                    data = HeartbeatResponse.model_validate(resp.json())
                except ValidationError as exc:
                    logger.warning("Malformed heartbeat response: %s", exc)
                    stop_event.wait(HEARTBEAT_INTERVAL)
                    continue
                # Server may refuse source-code auto-updates if our Docker image
                # is too old to safely receive them (missing system deps, etc.)
                if data.image_upgrade_required:
                    min_v = data.min_image_version or "?"
                    if not _image_upgrade_logged:
                        logger.warning(
                            "Docker image upgrade required: this worker reports IMAGE_VERSION=%s "
                            "but the server's MIN_IMAGE_VERSION=%s. Auto-updates are disabled "
                            "until the Docker image is rebuilt with `docker pull` + restart.",
                            IMAGE_VERSION or "<none>", min_v,
                        )
                        _image_upgrade_logged = True
                else:
                    sv = data.server_client_version
                    if sv and sv != CLIENT_VERSION:
                        logger.info(
                            "Worker update available: local=%s server=%s", CLIENT_VERSION, sv
                        )
                        _update_available.set()
                # Check for max_parallel_jobs config change from UI
                new_jobs = data.set_max_parallel_jobs
                if new_jobs is not None and new_jobs != MAX_PARALLEL_JOBS:
                    logger.info(
                        "Server requested max_parallel_jobs change: %d → %d — restarting",
                        MAX_PARALLEL_JOBS, new_jobs,
                    )
                    # Write new value to env so it persists across restart
                    os.environ["MAX_PARALLEL_JOBS"] = str(new_jobs)
                    _restart_self()
                # Check for clean build cache request from UI
                if data.clean_build_cache:
                    logger.info("Server requested build cache clean — clearing esphome-versions")
                    _clean_build_cache()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            _on_server_unreachable(exc)
        except Exception as exc:
            logger.warning("Heartbeat unexpected error: %s", exc)
        stop_event.wait(HEARTBEAT_INTERVAL)


# ---------------------------------------------------------------------------
# Bundle extraction
# ---------------------------------------------------------------------------

def extract_bundle(bundle_b64: str, dest_dir: str) -> None:
    """Decode and extract the base64 tar.gz bundle into dest_dir."""
    raw = base64.b64decode(bundle_b64)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        try:
            tar.extractall(path=dest_dir, filter="data")
        except TypeError:
            tar.extractall(path=dest_dir)  # Python < 3.12
    logger.debug("Bundle extracted to %s", dest_dir)


# ---------------------------------------------------------------------------
# Job runner
# ---------------------------------------------------------------------------

_update_attempts: int = 0
_MAX_UPDATE_ATTEMPTS: int = 3


def _apply_update(current_client_id: str) -> None:
    """Download updated worker code from server and restart the process.

    Stashes *current_client_id* in the environment so the restarted process
    can re-register in place (keeping the same entry in the server's registry).
    """
    global _update_attempts
    _update_available.clear()
    _update_attempts += 1
    if _update_attempts > _MAX_UPDATE_ATTEMPTS:
        logger.warning(
            "Update failed %d times; giving up until restart", _MAX_UPDATE_ATTEMPTS
        )
        return
    logger.info("Downloading worker update from server...")
    try:
        resp = get("/api/v1/client/code", timeout=60)
        resp.raise_for_status()
        data = resp.json()
        files = data.get("files", {})
        new_version = data.get("version", "?")
        if not files:
            logger.warning("Update response had no files; skipping")
            return
        client_dir = Path(__file__).parent.resolve()
        for filename, content in files.items():
            if not filename.endswith(".py"):
                continue
            target = (client_dir / filename).resolve()
            if target.parent != client_dir:
                logger.warning("Skipping suspicious path in update: %s", filename)
                continue
            target.write_text(content, encoding="utf-8")
            logger.info("Updated %s", filename)
        logger.info("Worker updated to %s — restarting", new_version)
        os.environ["DISTRIBUTED_ESPHOME_CLIENT_ID"] = current_client_id
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as exc:
        logger.warning("Worker update failed: %s", exc)


def _ota_network_diagnostics(target_path: str, cwd: str, env: dict) -> str:
    """Run network diagnostics after an OTA failure.

    Parses the target YAML (best-effort) to find the device IP/hostname,
    then checks TCP connectivity, DNS resolution, and network route.
    Returns a human-readable diagnostics string for the build log.
    """
    import re as _re  # noqa: PLC0415

    lines: list[str] = []

    # Try to find the device address from the YAML config.
    # Priority order (matching ESPHome's own logic):
    #   1. wifi.use_address (explicit override)
    #   2. wifi.manual_ip.static_ip
    #   3. DNS resolution of device name
    device_addr = None
    ota_port = None
    try:
        with open(target_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        # use_address takes priority — ESPHome uses this as the upload target
        use_addr_match = _re.search(r"use_address:\s*['\"]?([^\s'\"#]+)", content)
        if use_addr_match:
            device_addr = use_addr_match.group(1)
            lines.append(f"use_address: {device_addr}")
        # Fall back to static_ip
        if not device_addr:
            ip_match = _re.search(r"static_ip:\s*['\"]?(\d+\.\d+\.\d+\.\d+)", content)
            if ip_match:
                device_addr = ip_match.group(1)
        # Check for OTA port override
        port_match = _re.search(r"port:\s*(\d+)", content.split("ota:")[1] if "ota:" in content else "")
        if port_match:
            ota_port = int(port_match.group(1))
    except Exception:
        logger.debug("Could not parse device address/port from YAML %s", target_path, exc_info=True)

    # Extract device name from the esphome: block (not any other component's name: key).
    # Parse with yaml.safe_load to avoid the regex pitfall of matching the wrong name:.
    device_name = None
    try:
        import yaml as _yaml  # noqa: PLC0415
        with open(target_path, encoding="utf-8", errors="replace") as f:
            raw = _yaml.safe_load(f)
        if isinstance(raw, dict):
            esphome_block = raw.get("esphome") or {}
            if isinstance(esphome_block, dict) and esphome_block.get("name"):
                device_name = str(esphome_block["name"])
    except Exception:
        # Fallback: look for name: directly under an esphome: line
        try:
            with open(target_path, encoding="utf-8", errors="replace") as f:
                content_lines = f.readlines()
            in_esphome = False
            for line in content_lines:
                stripped = line.lstrip()
                # Top-level key (no indent) — check if it's esphome:
                if line and not line[0].isspace() and stripped.startswith("esphome:"):
                    in_esphome = True
                    continue
                elif line and not line[0].isspace():
                    in_esphome = False
                    continue
                if in_esphome:
                    m = _re.match(r'\s+name:\s*["\']?([a-zA-Z0-9_-]+)', line)
                    if m:
                        device_name = m.group(1)
                        break
        except Exception:
            logger.debug("Could not extract device name from YAML %s", target_path, exc_info=True)

    # If use_address is a hostname (not IP), try to resolve it
    if device_addr and not _re.match(r'\d+\.\d+\.\d+\.\d+$', device_addr):
        hostname = device_addr
        try:
            import socket as _socket  # noqa: PLC0415
            device_addr = _socket.gethostbyname(hostname)
            lines.append(f"Resolved {hostname} → {device_addr}")
        except Exception:
            lines.append(f"DNS: {hostname} — FAILED to resolve")
            device_addr = None

    if not device_addr and device_name:
        # Try DNS resolution of the device name (ESPHome devices register as <name>.local)
        try:
            import socket as _socket  # noqa: PLC0415
            device_addr = _socket.gethostbyname(f"{device_name}.local")
            lines.append(f"Resolved {device_name}.local → {device_addr}")
        except Exception:
            lines.append(f"DNS: {device_name}.local — FAILED to resolve")
            # Try without .local
            try:
                device_addr = _socket.gethostbyname(device_name)
                lines.append(f"Resolved {device_name} → {device_addr}")
            except Exception:
                lines.append(f"DNS: {device_name} — FAILED to resolve")

    if not device_addr:
        lines.append("Could not determine device IP for diagnostics")
        return "\n".join(lines)

    # Determine OTA port: ESP8266 uses 8266, ESP32 uses 3232
    if not ota_port:
        # Check both common ports
        ports_to_check = [3232, 8266]
    else:
        ports_to_check = [ota_port]

    lines.append(f"Device IP: {device_addr}")

    # TCP connectivity check
    import socket as _socket  # noqa: PLC0415
    for port in ports_to_check:
        try:
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((device_addr, port))
            if result == 0:
                lines.append(f"TCP {device_addr}:{port} — OPEN (connected)")
            else:
                lines.append(f"TCP {device_addr}:{port} — CLOSED (errno {result})")
            sock.close()
        except _socket.timeout:
            lines.append(f"TCP {device_addr}:{port} — TIMEOUT (5s)")
        except Exception as exc:
            lines.append(f"TCP {device_addr}:{port} — ERROR: {exc}")

    # Ping check (ICMP)
    try:
        ping_result = subprocess.run(
            ["ping", "-c", "3", "-W", "2", device_addr],
            capture_output=True, text=True, timeout=10,
        )
        ping_summary = [ln for ln in ping_result.stdout.splitlines() if "packet" in ln.lower() or "rtt" in ln.lower() or "round-trip" in ln.lower()]
        for line in ping_summary:
            lines.append(f"Ping: {line.strip()}")
        if ping_result.returncode != 0 and not ping_summary:
            lines.append(f"Ping: {device_addr} — UNREACHABLE")
    except Exception as exc:
        lines.append(f"Ping: {exc}")

    # Check our own IP / network interface
    try:
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        sock.connect((device_addr, 80))
        our_ip = sock.getsockname()[0]
        sock.close()
        lines.append(f"Worker IP: {our_ip} (source for reaching {device_addr})")
    except Exception:
        logger.debug("Could not determine worker IP for OTA diagnostics", exc_info=True)

    # Docker network check
    try:
        if os.path.exists("/.dockerenv"):
            lines.append("Running inside Docker container")
            # Check if we're using host networking
            try:
                with open("/proc/1/cgroup", encoding="utf-8", errors="replace") as f:
                    cgroup = f.read()
                if "docker" in cgroup:
                    lines.append("Network mode: bridge (NAT) — consider --network host if OTA fails consistently")
            except Exception:
                logger.debug("Could not read /proc/1/cgroup for Docker network check", exc_info=True)
    except Exception:
        logger.debug("Docker environment check failed", exc_info=True)

    diag_text = "\n".join(lines)
    logger.info("OTA diagnostics for %s:\n%s", device_addr, diag_text)
    return diag_text


# ---------------------------------------------------------------------------
# #45: Per-slot working dirs + shared per-target compile cache.
#
# Two concurrent compiles for the same target used to share one build dir
# under /esphome-versions/builds/<stem>/, racing on PlatformIO's .pio/ files
# and ESPHome's .esphome/ state. The fix:
#
#   /esphome-versions/
#     slots/<slot>/<stem>/   per-slot, per-target working dir (compile here)
#     cache/<stem>/          shared per-target cache of .pio/ + .esphome/
#     cache/<stem>.lock      fcntl lock — serialises rsync in/out per target
#
# Sync-in: only when the slot dir has no .pio/ yet (first compile of this
# target on this slot). Sync-out: always on successful compile, so any other
# slot that later picks up the same target gets a warm cache to start from.
# Both sync operations take the per-target lock.
# ---------------------------------------------------------------------------


def _slot_dir(worker_id: int, target_stem: str) -> str:
    return os.path.join(_ESPHOME_VERSIONS_DIR, "slots", str(worker_id), target_stem)


def _cache_dir(target_stem: str) -> str:
    return os.path.join(_ESPHOME_VERSIONS_DIR, "cache", target_stem)


@contextmanager
def _target_cache_lock(target_stem: str) -> Iterator[None]:
    """Exclusive fcntl lock on a per-target lock file under the cache dir.

    Serialises sync-in/sync-out for a target across slots so two workers
    can't step on each other while rsync'ing the .pio/.esphome subtrees.
    The lock file itself is never deleted — it's just a handle.
    """
    cache_parent = os.path.join(_ESPHOME_VERSIONS_DIR, "cache")
    os.makedirs(cache_parent, exist_ok=True)
    lock_path = os.path.join(cache_parent, f"{target_stem}.lock")
    with open(lock_path, "w", encoding="utf-8") as fp:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)


def _copytree_replace(src: str, dst: str) -> None:
    """Copy *src* tree to *dst*, replacing *dst* if it exists.

    Uses shutil.rmtree + shutil.copytree — acceptable for typical ESPHome
    .pio/.esphome sizes (~50-100MB). Silently tolerates missing src.
    """
    if not os.path.isdir(src):
        return
    if os.path.exists(dst):
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, symlinks=True)


def _sync_cache_into_slot(target_stem: str, slot_dir: str) -> None:
    """On first compile of *target_stem* in *slot_dir*, seed .pio/.esphome
    from the shared cache so the slot benefits from any prior compile on
    any other slot.
    """
    cache_dir = _cache_dir(target_stem)
    if not os.path.isdir(cache_dir):
        return

    slot_pio = os.path.join(slot_dir, ".pio")
    slot_esphome = os.path.join(slot_dir, ".esphome")
    cache_pio = os.path.join(cache_dir, ".pio")
    cache_esphome = os.path.join(cache_dir, ".esphome")

    need_pio = os.path.isdir(cache_pio) and not os.path.isdir(slot_pio)
    need_esphome = os.path.isdir(cache_esphome) and not os.path.isdir(slot_esphome)
    if not (need_pio or need_esphome):
        has_local = os.path.isdir(slot_pio) or os.path.isdir(slot_esphome)
        logger.info(
            "Slot cache sync-in skipped for %s (local=%s, shared=%s)",
            target_stem,
            "has .pio" if has_local else "empty",
            "present" if os.path.isdir(cache_dir) else "absent",
        )
        return

    with _target_cache_lock(target_stem):
        if need_pio:
            logger.info("Slot seeding .pio/ from shared cache for %s", target_stem)
            _copytree_replace(cache_pio, slot_pio)
        if need_esphome:
            logger.info("Slot seeding .esphome/ from shared cache for %s", target_stem)
            _copytree_replace(cache_esphome, slot_esphome)


def _sync_slot_into_cache(target_stem: str, slot_dir: str) -> None:
    """After a successful compile, push .pio/.esphome back to the shared
    cache so subsequent compiles on any slot start warm.
    """
    slot_pio = os.path.join(slot_dir, ".pio")
    slot_esphome = os.path.join(slot_dir, ".esphome")
    if not (os.path.isdir(slot_pio) or os.path.isdir(slot_esphome)):
        return

    cache_dir = _cache_dir(target_stem)
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with _target_cache_lock(target_stem):
            if os.path.isdir(slot_pio):
                _copytree_replace(slot_pio, os.path.join(cache_dir, ".pio"))
            if os.path.isdir(slot_esphome):
                _copytree_replace(slot_esphome, os.path.join(cache_dir, ".esphome"))
        logger.info("Updated shared cache for %s", target_stem)
    except Exception:
        logger.warning("Failed to update shared cache for %s", target_stem, exc_info=True)


def run_job(client_id: str, job: dict, version_manager: VersionManager, worker_id: int = 1) -> None:
    """Execute a single build job end-to-end."""
    global _active_jobs
    with _active_jobs_lock:
        _active_jobs += 1
    job_id = job["job_id"]
    target = job["target"]
    esphome_version = job["esphome_version"]
    bundle_b64 = job["bundle_b64"]
    timeout_seconds = job.get("timeout_seconds", JOB_TIMEOUT)
    ota_only = job.get("ota_only", False)
    validate_only = job.get("validate_only", False)
    download_only = job.get("download_only", False)

    _log_context.current_target = target
    logger.info(
        "Starting job %s: target=%s esphome=%s ota_only=%s validate_only=%s download_only=%s",
        job_id, target, esphome_version, ota_only, validate_only, download_only,
    )

    # Per-slot PlatformIO core directory — prevents cross-slot package conflicts
    # when multiple workers run esphome compile simultaneously.
    pio_dir = os.path.join(_ESPHOME_VERSIONS_DIR, f"pio-slot-{worker_id}")
    try:
        os.makedirs(pio_dir, exist_ok=True)
        subprocess_env = {**os.environ, "PLATFORMIO_CORE_DIR": pio_dir}
        logger.debug("Worker %d using PLATFORMIO_CORE_DIR=%s", worker_id, pio_dir)
    except OSError as exc:
        logger.debug("Could not create pio dir %s (%s); using default PLATFORMIO_CORE_DIR", pio_dir, exc)
        subprocess_env = dict(os.environ)

    # Match server timezone so ESPHome produces identical config_hash.
    # Mismatched TZ → different hash → unnecessary clean rebuild → different firmware binary.
    server_tz = job.get("server_timezone")
    if server_tz:
        subprocess_env["TZ"] = server_tz
        logger.debug("Using server timezone: %s", server_tz)

    # Network timeouts for uv/pip during ESPHome's penv bootstrap. Defaults are
    # aggressive (uv HTTP read = 30s, pip socket = 15s) and cause intermittent
    # "Failed to install Python dependencies into penv" failures on slow or
    # flaky links — see GitHub #6. setdefault lets operators override via the
    # worker env if needed. Both PIP_DEFAULT_TIMEOUT and PIP_TIMEOUT map to
    # pip's --timeout option (verified in pip source).
    subprocess_env.setdefault("UV_HTTP_TIMEOUT", "180")
    subprocess_env.setdefault("UV_HTTP_CONNECT_TIMEOUT", "30")
    subprocess_env.setdefault("PIP_DEFAULT_TIMEOUT", "180")

    # Install ESPHome version (BEFORE starting the timeout timer)
    if ESPHOME_BIN:
        esphome_bin = ESPHOME_BIN
        logger.info("Using esphome binary override: %s", esphome_bin)
    else:
        _report_status(job_id, f"Preparing ESPHome {esphome_version}")
        _flush_log_text(job_id, f"Ensuring ESPHome {esphome_version} is available...\n")
        try:
            esphome_bin = version_manager.ensure_version(esphome_version)
            logger.info("Using esphome binary: %s", esphome_bin)
            _flush_log_text(job_id, f"ESPHome {esphome_version} ready.\n")
        except Exception as exc:
            error_detail = str(exc)
            logger.error("Failed to install esphome==%s: %s", esphome_version, error_detail)
            # Stream the full error to the job log so the user sees it in the terminal
            _flush_log_text(job_id, f"\n\033[31mERROR: Failed to install ESPHome {esphome_version}\033[0m\n{error_detail}\n")
            _submit_result(job_id, "failed", log=None, ota_result=None)
            with _active_jobs_lock:
                _active_jobs -= 1
            return

    # #13: stable per-target build directory so the .esphome/ build cache
    #      (PlatformIO compiled objects) persists across jobs — turns a
    #      60-90s full compile into a 5-10s incremental build.
    # #45: now per-SLOT as well, so concurrent compiles on the same worker
    #      don't race on the same directory. The shared /cache/<stem>/ dir
    #      is synced in on first compile and synced out on success so cache
    #      still reuses across slots via the shared cache. Two slots can
    #      compile the same target in parallel without stepping on each
    #      other — they work in separate slot dirs and only contend on the
    #      brief sync-in/sync-out phases (serialized by a per-target lock).
    target_stem = os.path.splitext(target)[0]
    build_dir = _slot_dir(worker_id, target_stem)
    os.makedirs(build_dir, exist_ok=True)
    try:
        # Seed this slot's .pio/.esphome from the shared cache if this is
        # the first compile of this target on this slot. No-op otherwise.
        _sync_cache_into_slot(target_stem, build_dir)
        # Extract bundle into the stable dir (overwrites changed files;
        # .esphome/ subdir with PlatformIO cache is preserved).
        try:
            extract_bundle(bundle_b64, build_dir)
        except Exception as exc:
            logger.error("Bundle extraction failed: %s", exc)
            _submit_result(job_id, "failed", log=f"Bundle extraction failed: {exc}", ota_result=None)
            return

        target_path = os.path.join(build_dir, target)
        if not os.path.exists(target_path):
            _submit_result(job_id, "failed", log=f"Target file not found in bundle: {target}", ota_result=None)
            return

        # ---------------------------------------------------------------
        # Validation phase (validate_only=True) — runs esphome config and exits
        # ---------------------------------------------------------------
        if validate_only:
            _report_status(job_id, "Validating")
            validate_cmd = [esphome_bin, "config", target_path]
            _log_invocation(job_id, validate_cmd)
            _compile_log, compile_ok = _run_subprocess(
                validate_cmd,
                cwd=build_dir,
                timeout=60,  # validation is fast — 60s is plenty
                label="validate",
                env=subprocess_env,
                job_id=job_id,
            )
            _submit_result(job_id, "success" if compile_ok else "failed", log=None, ota_result=None)
            return  # skip compile and OTA phases

        # ---------------------------------------------------------------
        # Compile-and-download phase (download_only=True) — runs
        # `esphome compile` (no OTA), locates the produced firmware .bin
        # under .esphome/build/<device>/.pioenvs/<device>/, POSTs it to
        # the server, and reports success. FD.4.
        # ---------------------------------------------------------------
        if download_only:
            _report_status(job_id, "Compiling (no OTA)")
            compile_cmd = [esphome_bin, "compile", target_path]
            _log_invocation(job_id, compile_cmd)
            compile_log, compile_ok = _run_subprocess(
                compile_cmd,
                cwd=build_dir,
                timeout=timeout_seconds,
                label="compile",
                env=subprocess_env,
                job_id=job_id,
            )
            if not compile_ok:
                _submit_result(job_id, "failed", log=None, ota_result=None)
                return
            # Compile succeeded — warm the shared cache.
            _sync_slot_into_cache(target_stem, build_dir)

            firmware_path = _locate_firmware_binary(build_dir, target_stem)
            if firmware_path is None:
                _flush_log_text(
                    job_id,
                    "\n\033[31mERROR: Compile succeeded but firmware binary was "
                    "not found under .pioenvs/ — nothing to upload.\033[0m\n",
                )
                _submit_result(job_id, "failed", log=None, ota_result=None)
                return

            _report_status(job_id, "Uploading firmware")
            upload_ok = _upload_firmware(job_id, firmware_path, client_id=client_id)
            if not upload_ok:
                _flush_log_text(
                    job_id,
                    "\n\033[31mERROR: Firmware upload to server failed.\033[0m\n",
                )
                _submit_result(job_id, "failed", log=None, ota_result=None)
                return

            _flush_log_text(
                job_id,
                f"\nFirmware uploaded to server ({firmware_path.stat().st_size} bytes). "
                "Download from the Queue tab.\n",
            )
            _submit_result(job_id, "success", log=None, ota_result=None)
            return

        # ---------------------------------------------------------------
        # Build + OTA via `esphome run` (compile and upload in one step)
        #
        # --no-logs is REQUIRED on `esphome run` so the worker doesn't hang
        # tailing device logs after a successful OTA. It is NOT accepted by
        # `esphome upload` — passing it to the retry path in bug #177 caused
        # the retry to crash with "unrecognized arguments: --no-logs".
        #
        # --device is ALWAYS set:
        #   - ota_address from the server if known (device poller has an IP)
        #   - otherwise the literal string "OTA", which tells ESPHome to
        #     resolve the device itself and skip the interactive upload
        #     target prompt (#176). Without this, ESPHome prompts when the
        #     worker has multiple possible targets (e.g. a USB serial dongle
        #     plus the OTA target), and the worker has no stdin.
        # ---------------------------------------------------------------
        ota_address = job.get("ota_address") or "OTA"

        _report_status(job_id, "Compiling + OTA" + (" (retry)" if ota_only else ""))
        run_cmd = [
            esphome_bin, "run", target_path,
            "--no-logs",
            "--device", ota_address,
        ]
        _log_invocation(job_id, run_cmd)

        # Total timeout covers both compile + OTA
        total_timeout = timeout_seconds + OTA_TIMEOUT
        run_log, run_ok = _run_subprocess(
            run_cmd,
            cwd=build_dir,
            timeout=total_timeout,
            label="compile+OTA",
            env=subprocess_env,
            job_id=job_id,
        )

        if run_ok:
            # #45: compile succeeded — sync the slot's .pio/.esphome back to
            # the shared cache so other slots can start warm next time.
            _sync_slot_into_cache(target_stem, build_dir)
            _submit_result(job_id, "success", log=None, ota_result="success")
        else:
            log_lower = run_log.lower()
            compile_succeeded = "successfully compiled" in log_lower
            ota_failed = compile_succeeded and ("failed" in log_lower or "timed out" in log_lower)

            # #45: if the COMPILE succeeded (even if OTA failed or retried)
            # we still want to promote the build artifacts to the shared
            # cache — a successful compile is worth caching regardless of
            # whether the device was reachable for OTA.
            if compile_succeeded:
                _sync_slot_into_cache(target_stem, build_dir)

            if not compile_succeeded:
                _submit_result(job_id, "failed", log=None, ota_result=None)
            elif ota_failed:
                # Compile succeeded but OTA failed — retry OTA before reporting.
                # Keep job in WORKING state so timeout checker can re-queue if we die.
                # Note: `esphome upload` does NOT accept --no-logs (it never tails
                # device logs anyway), so this retry path only passes --device.
                _flush_log_text(job_id, "\n--- OTA failed, retrying in 5s ---\n")
                time.sleep(5)
                _report_status(job_id, "OTA Retry")
                upload_cmd = [
                    esphome_bin, "upload", target_path,
                    "--device", ota_address,
                ]
                _log_invocation(job_id, upload_cmd)
                retry_log, retry_ok = _run_subprocess(
                    upload_cmd,
                    cwd=build_dir,
                    timeout=OTA_TIMEOUT,
                    label="OTA retry",
                    env=subprocess_env,
                    job_id=job_id,
                )
                if retry_ok:
                    _submit_result(job_id, "success", log=None, ota_result="success")
                else:
                    _submit_result(job_id, "success", log=None, ota_result="failed")
                    diag = _ota_network_diagnostics(target_path, build_dir, subprocess_env)
                    if diag:
                        _flush_log_text(job_id, "\n--- Network Diagnostics ---\n" + diag)
            else:
                # Compile succeeded but something else failed
                _submit_result(job_id, "success", log=None, ota_result="failed")

    finally:
        _log_context.current_target = None
        with _active_jobs_lock:
            _active_jobs -= 1
        # #13: intentionally NOT cleaning up build_dir — the .esphome/
        # subdirectory contains PlatformIO's compiled object cache. Keeping
        # it turns a 60-90s full compile into a 5-10s incremental build.
        # The "Clean Cache" button in the Workers tab already handles
        # cleanup by removing all of /esphome-versions/ including builds/.


def _colorize_log_line(line: str) -> str:
    """Add ANSI color codes to ESPHome log lines based on level prefix."""
    stripped = line.lstrip()
    if stripped.startswith("INFO "):
        return f"\033[32m{line}\033[0m"  # green
    if stripped.startswith("WARNING "):
        return f"\033[33m{line}\033[0m"  # yellow/orange
    if stripped.startswith("ERROR "):
        return f"\033[31m{line}\033[0m"  # red
    return line


def _run_subprocess(
    cmd: list[str],
    cwd: str,
    timeout: int,
    label: str,
    env: Optional[dict] = None,
    job_id: Optional[str] = None,
) -> tuple[str, bool]:
    """
    Run a subprocess with a timeout, streaming output line-by-line.

    Returns (combined_log, success).
    On timeout, kills the process and returns (log + 'TIMED OUT', False).
    *env* is passed directly to Popen; defaults to inheriting the current env.
    *job_id* enables live log streaming — lines are batched and POSTed to the
    server every 2 seconds via ``/api/v1/jobs/{id}/log``.
    """
    FLUSH_INTERVAL = 0.5
    log_chunks: list[str] = []
    flush_buffer: list[str] = []
    last_flush = time.monotonic()
    timed_out = threading.Event()
    logger.info("Running %s: %s", label, " ".join(cmd))

    def _flush_log():
        nonlocal flush_buffer, last_flush
        if not job_id or not flush_buffer:
            return
        text = "".join(flush_buffer)
        flush_buffer = []
        last_flush = time.monotonic()
        try:
            post(f"/api/v1/jobs/{job_id}/log", {"lines": text}, timeout=5)
        except Exception:
            logger.debug("Log flush to server failed for job %s", job_id, exc_info=True)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            env=env,
        )
    except Exception as exc:
        return f"Failed to start process: {exc}", False

    def _kill_on_timeout():
        timed_out.set()
        try:
            proc.kill()
        except Exception:
            logger.debug("Failed to kill timed-out subprocess for %s", label, exc_info=True)

    timer = threading.Timer(timeout, _kill_on_timeout)
    timer.start()
    try:
        # read1() returns whatever bytes are available immediately (no blocking
        # to fill a full buffer), so we flush output to the server promptly.
        assert proc.stdout is not None
        raw: Any = proc.stdout
        while True:
            chunk = raw.read1(8192) if hasattr(raw, 'read1') else raw.read(4096)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            # Colorize log lines for xterm.js display
            colored = "\n".join(_colorize_log_line(ln) for ln in text.split("\n"))
            log_chunks.append(colored)
            flush_buffer.append(colored)
            now = time.monotonic()
            if now - last_flush >= FLUSH_INTERVAL:
                _flush_log()
        proc.wait()
        _flush_log()  # final flush
    finally:
        timer.cancel()

    if timed_out.is_set():
        log = "".join(log_chunks) + f"\n\nTIMED OUT after {timeout}s"
        logger.warning("%s timed out after %ds", label, timeout)
        return log, False

    success = proc.returncode == 0
    log = "".join(log_chunks)
    logger.info("%s finished: returncode=%d", label, proc.returncode)
    return log, success


def _flush_log_text(job_id: str, text: str) -> None:
    """Send a chunk of log text to the server for live streaming."""
    try:
        post(
            f"/api/v1/jobs/{job_id}/log",
            JobLogAppend(lines=text).model_dump(),
            timeout=5,
        )
    except Exception:
        logger.debug("Log text flush failed for job %s", job_id, exc_info=True)


def _log_invocation(job_id: str, cmd: list[str]) -> None:
    """Log an esphome invocation to BOTH the Python logger and the user-visible
    job log stream.

    Bug reports are much easier to triage when the exact command line is in
    the log the user copy-pastes from the UI.
    """
    line = "Invoking: " + " ".join(cmd)
    logger.info(line)
    # Blue-ish ANSI so it stands out in the xterm viewer without looking alarming.
    _flush_log_text(job_id, f"\033[36m{line}\033[0m\n")


def _report_status(job_id: str, status_text: str) -> None:
    """Fire-and-forget status update to server."""
    try:
        post(
            f"/api/v1/jobs/{job_id}/status",
            JobStatusUpdate(status_text=status_text).model_dump(),
            timeout=5,
        )
    except Exception:
        logger.debug("Status update failed for job %s (%s)", job_id, status_text, exc_info=True)


def _submit_result(
    job_id: str,
    status: str,
    log: Optional[str],
    ota_result: Optional[str],
) -> None:
    """POST job result to server, retrying a few times on network errors."""
    # Build + validate the submission via the typed model. ``status`` is a
    # Literal["success","failed"] on the wire — pydantic will reject anything
    # else before it is ever sent. The cast + model_validate path makes mypy
    # happy without silencing the check with a blanket ignore.
    submission = JobResultSubmission.model_validate(
        {"status": status, "log": log, "ota_result": ota_result}
    )
    payload = submission.model_dump(exclude_none=True)

    for attempt in range(3):
        try:
            resp = post(f"/api/v1/jobs/{job_id}/result", payload, timeout=30)
            if resp.ok:
                logger.info("Submitted result for job %s: status=%s", job_id, status)
                return
            logger.warning(
                "Server rejected result for job %s: %d %s",
                job_id, resp.status_code, resp.text,
            )
            return
        except Exception as exc:
            logger.warning("Failed to submit result (attempt %d): %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(2)


def _locate_firmware_binary(build_dir: str, target_stem: str) -> Optional[Path]:
    """Find the compiled firmware .bin under .esphome/build/<device>/.

    ESPHome layout after `esphome compile` is:
      {build_dir}/.esphome/build/{device_name}/.pioenvs/{device_name}/firmware.factory.bin   (ESP32)
      {build_dir}/.esphome/build/{device_name}/.pioenvs/{device_name}/firmware.bin           (ESP8266)

    The device name can differ from the target filename stem if the
    YAML uses substitutions. Walk the build tree and pick the largest
    `firmware.*.bin` we find — on ESP32 that's `firmware.factory.bin`
    (~1-2MB, the full flash image); on ESP8266 it's `firmware.bin`.
    Logs what it picked so ESPHome-version-specific layout changes are
    diagnosable from the job log.
    """
    esphome_build = Path(build_dir) / ".esphome" / "build"
    if not esphome_build.is_dir():
        logger.warning(
            "Build tree %s does not exist — compile likely failed or produced no artifacts",
            esphome_build,
        )
        return None

    # Prefer .factory.bin (full flash image) when present; fall back to
    # firmware.bin (ESP8266 / OTA-only ESP32 build variant).
    candidates: list[Path] = []
    for device_dir in esphome_build.iterdir():
        if not device_dir.is_dir():
            continue
        for name in ("firmware.factory.bin", "firmware.bin"):
            p = device_dir / ".pioenvs" / device_dir.name / name
            if p.is_file():
                candidates.append(p)

    if not candidates:
        logger.warning("No firmware binary found under %s", esphome_build)
        return None

    # factory.bin > firmware.bin (lexicographic puts factory first which is fine)
    candidates.sort(key=lambda p: (0 if "factory" in p.name else 1, -p.stat().st_size))
    picked = candidates[0]
    logger.info(
        "Located firmware binary for %s: %s (%d bytes)",
        target_stem, picked, picked.stat().st_size,
    )
    return picked


def _upload_firmware(job_id: str, path: Path, client_id: Optional[str] = None) -> bool:
    """POST the compiled binary to the server. Returns True on success.

    Failure reasons are surfaced into the job's log (via
    ``_flush_log_text``) so the user can diagnose from the Queue-tab
    Log modal without access to the worker's stdout.
    """
    try:
        data = path.read_bytes()
    except Exception as exc:
        msg = f"Failed to read firmware {path}: {exc}"
        logger.error(msg)
        _flush_log_text(job_id, f"\n\033[31mUPLOAD ERROR: {msg}\033[0m\n")
        return False

    last_err = ""
    for attempt in range(3):
        try:
            resp = post_bytes(
                f"/api/v1/jobs/{job_id}/firmware",
                data,
                timeout=600,
                client_id=client_id,
            )
            if resp.ok:
                logger.info(
                    "Uploaded firmware for job %s (%d bytes) → server",
                    job_id, len(data),
                )
                return True
            last_err = f"HTTP {resp.status_code}: {resp.text[:300]}"
            logger.warning(
                "Server rejected firmware for job %s: %s",
                job_id, last_err,
            )
            # Server rejections are deterministic — no retry.
            break
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Firmware upload attempt %d failed for job %s: %s",
                attempt + 1, job_id, last_err,
            )
            if attempt < 2:
                time.sleep(3)
    _flush_log_text(
        job_id,
        f"\n\033[31mUPLOAD ERROR: {last_err or 'unknown failure'}\033[0m\n",
    )
    return False


def _submit_ota_result(job_id: str, ota_result: str, ota_log: Optional[str]) -> None:
    """POST OTA result (and log) update to server."""
    for attempt in range(3):
        try:
            resp = post(
                f"/api/v1/jobs/{job_id}/result",
                {"status": "success", "ota_result": ota_result, "log": ota_log},
                timeout=30,
            )
            if resp.ok:
                logger.info("OTA result for job %s: %s", job_id, ota_result)
                return
        except Exception as exc:
            logger.warning("Failed to submit OTA result (attempt %d): %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(2)


# ---------------------------------------------------------------------------
# Worker loop (one per parallel slot)
# ---------------------------------------------------------------------------

def worker_loop(
    worker_id: int,
    client_id: str,
    version_manager: VersionManager,
    stop_event: threading.Event,
) -> None:
    """Poll for jobs and execute them. Runs in its own thread."""
    _log_context.worker_id = worker_id
    _log_context.current_target = None
    logger.info("Worker %d started", worker_id)
    while not stop_event.is_set():
        # Pause polling when update or re-register is pending so the main
        # thread can reach idle state and handle the event.
        if _reregister_needed.is_set() or _update_available.is_set():
            stop_event.wait(1)
            continue

        try:
            resp = requests.get(
                f"{SERVER_URL}/api/v1/jobs/next",
                headers={**HEADERS, "X-Client-Id": client_id, "X-Worker-Id": str(worker_id)},
                timeout=30,
            )
            _on_server_reachable()
            if resp.status_code == 401:
                _on_auth_failed()
                stop_event.wait(POLL_INTERVAL)
            elif resp.status_code == 204:
                _on_auth_ok()
                stop_event.wait(POLL_INTERVAL)
            elif resp.status_code == 200:
                _on_auth_ok()
                try:
                    assignment = JobAssignment.model_validate(resp.json())
                except ValidationError as exc:
                    logger.warning(
                        "Worker %d: malformed job assignment from server: %s",
                        worker_id, exc,
                    )
                    stop_event.wait(POLL_INTERVAL)
                    continue
                logger.info(
                    "Worker %d claimed job %s for target %s",
                    worker_id, assignment.job_id, assignment.target,
                )
                run_job(client_id, assignment.model_dump(), version_manager, worker_id)
                # No sleep after work — immediately poll for next job
            else:
                logger.warning(
                    "Worker %d: unexpected response from jobs/next: %d",
                    worker_id, resp.status_code,
                )
                stop_event.wait(POLL_INTERVAL)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            _on_server_unreachable(exc)
            stop_event.wait(POLL_INTERVAL)
        except Exception as exc:
            logger.exception("Worker %d: unexpected error in poll loop: %s", worker_id, exc)
            stop_event.wait(POLL_INTERVAL)

    logger.info("Worker %d stopped", worker_id)


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------

def _initial_version_check(client_id: str) -> None:
    """Do one synchronous heartbeat immediately after registration.

    If the server has a newer worker version, sets _update_available so the
    main loop applies the update before picking up any jobs.
    """
    try:
        resp = post("/api/v1/workers/heartbeat", {
            "client_id": client_id,
            "system_info": collect_system_info(_ESPHOME_VERSIONS_DIR),
        }, timeout=10)
        if resp.ok:
            sv = resp.json().get("server_client_version")
            if sv and sv != CLIENT_VERSION:
                logger.info(
                    "Update available before first poll: local=%s server=%s",
                    CLIENT_VERSION, sv,
                )
                _update_available.set()
    except Exception as exc:
        logger.debug("Initial version check failed (non-fatal): %s", exc)


def _stop_workers(worker_stop: threading.Event, worker_threads: list[threading.Thread]) -> None:
    """Signal workers to stop and wait for them to finish their current jobs."""
    worker_stop.set()
    for t in worker_threads:
        t.join()


def _launch_workers(
    client_id: str,
    version_manager: VersionManager,
) -> tuple[threading.Event, list[threading.Thread]]:
    """Start MAX_PARALLEL_JOBS worker threads. Returns (stop_event, threads)."""
    stop = threading.Event()
    threads = []
    for i in range(MAX_PARALLEL_JOBS):
        t = threading.Thread(
            target=worker_loop,
            args=(i + 1, client_id, version_manager, stop),
            daemon=True,
            name=f"worker-{i + 1}",
        )
        t.start()
        threads.append(t)
    return stop, threads


def main() -> None:
    import signal  # noqa: PLC0415

    logger.info(
        "ESPHome Build Worker starting (hostname=%s, workers=%d)",
        HOSTNAME, MAX_PARALLEL_JOBS,
    )

    # Handle SIGTERM (sent by Docker on `docker stop`) — raise in main thread
    _shutdown_requested = threading.Event()

    def _sigterm_handler(signum, frame):
        logger.info("Received SIGTERM, shutting down")
        _shutdown_requested.set()

    signal.signal(signal.SIGTERM, _sigterm_handler)

    version_manager = VersionManager(max_versions=MAX_ESPHOME_VERSIONS)

    # Pre-seed the requested ESPHome version so the first job runs immediately
    if ESPHOME_SEED_VERSION and not ESPHOME_BIN:
        logger.info("Pre-seeding ESPHome %s", ESPHOME_SEED_VERSION)
        try:
            version_manager.ensure_version(ESPHOME_SEED_VERSION)
            logger.info("ESPHome %s ready", ESPHOME_SEED_VERSION)
        except Exception as exc:
            logger.warning("Failed to pre-seed ESPHome %s: %s", ESPHOME_SEED_VERSION, exc)

    # Register with server
    client_id = register()

    # Check for available update before accepting any work
    _initial_version_check(client_id)

    # Start heartbeat thread
    stop_heartbeat = threading.Event()
    hb_thread = threading.Thread(
        target=heartbeat_loop,
        args=(client_id, stop_heartbeat),
        daemon=True,
        name="heartbeat",
    )
    hb_thread.start()

    # Apply update immediately if detected (before starting workers)
    if _update_available.is_set():
        stop_heartbeat.set()
        hb_thread.join(timeout=2)
        _apply_update(client_id)  # may os.execv — never returns on success
        # Update failed — restart heartbeat
        stop_heartbeat = threading.Event()
        hb_thread = threading.Thread(
            target=heartbeat_loop,
            args=(client_id, stop_heartbeat),
            daemon=True,
            name="heartbeat",
        )
        hb_thread.start()

    logger.info("Starting %d worker(s), polling every %ds", MAX_PARALLEL_JOBS, POLL_INTERVAL)
    worker_stop, worker_threads = _launch_workers(client_id, version_manager)

    try:
        while not _shutdown_requested.is_set():
            # Re-register if the heartbeat told us the server doesn't know us.
            # Wait until all workers are idle so in-flight jobs can complete.
            if _reregister_needed.is_set() and _is_idle():
                _reregister_needed.clear()
                _stop_workers(worker_stop, worker_threads)
                stop_heartbeat.set()
                hb_thread.join(timeout=2)

                client_id = register()

                stop_heartbeat = threading.Event()
                hb_thread = threading.Thread(
                    target=heartbeat_loop,
                    args=(client_id, stop_heartbeat),
                    daemon=True,
                    name="heartbeat",
                )
                hb_thread.start()
                worker_stop, worker_threads = _launch_workers(client_id, version_manager)

            # Apply pending update only when all workers are idle
            elif _update_available.is_set() and _is_idle():
                _stop_workers(worker_stop, worker_threads)
                stop_heartbeat.set()
                hb_thread.join(timeout=2)
                _apply_update(client_id)  # may os.execv — never returns on success
                # Update failed — restart heartbeat and workers
                stop_heartbeat = threading.Event()
                hb_thread = threading.Thread(
                    target=heartbeat_loop,
                    args=(client_id, stop_heartbeat),
                    daemon=True,
                    name="heartbeat",
                )
                hb_thread.start()
                worker_stop, worker_threads = _launch_workers(client_id, version_manager)

            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down (Ctrl-C)")
    finally:
        worker_stop.set()
        stop_heartbeat.set()
        hb_thread.join(timeout=2)
        deregister(client_id)


if __name__ == "__main__":
    main()
