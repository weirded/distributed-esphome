"""ESPHome distributed build client — polling loop, heartbeat, job runner."""

from __future__ import annotations

import base64
import io
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import requests


from version_manager import VersionManager

# ---------------------------------------------------------------------------
# Client version — must match the add-on VERSION file; bumped on each release.
# The server returns this value in heartbeat responses so outdated clients
# can detect the mismatch and self-update.
# ---------------------------------------------------------------------------

CLIENT_VERSION = "0.0.40"

# ---------------------------------------------------------------------------
# System information gathering (stdlib only — no psutil dependency)
# ---------------------------------------------------------------------------

# Captured at process start so uptime can be computed on each heartbeat.
_PROCESS_START_TIME: float = time.monotonic()


def _get_os_version() -> str:
    """Return a human-readable OS version string using only stdlib."""
    system = platform.system()

    if system == "Darwin":
        # e.g. "macOS 15.3"
        mac_ver = platform.mac_ver()[0]
        return f"macOS {mac_ver}" if mac_ver else "macOS"

    if system == "Linux":
        # Parse /etc/os-release for NAME and VERSION_ID (most distros)
        os_release: dict[str, str] = {}
        try:
            with open("/etc/os-release", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        key, _, val = line.partition("=")
                        os_release[key.strip()] = val.strip().strip('"')
        except OSError:
            pass

        name = os_release.get("NAME") or os_release.get("ID", "")
        version = os_release.get("VERSION_ID", "")
        if name and version:
            return f"{name} {version}"
        if name:
            return name

        # Fallback for minimal containers without /etc/os-release
        kernel = platform.release()
        return f"Linux {kernel}" if kernel else "Linux"

    # Windows or other
    return platform.platform()


def _get_cpu_model() -> str:
    """Return CPU model string using stdlib and /proc/cpuinfo or sysctl."""
    system = platform.system()

    if system == "Darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=3,
            )
            model = result.stdout.strip()
            if model:
                return model
        except Exception:
            pass
        # Apple Silicon reports via hw.model (e.g. "Apple M1 Pro")
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.model"],
                capture_output=True, text=True, timeout=3,
            )
            model = result.stdout.strip()
            if model:
                return model
        except Exception:
            pass

    if system == "Linux":
        # Try /proc/cpuinfo — "model name" on x86, "Model name" or "Hardware" on ARM
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if ":" in line:
                        key, _, val = line.partition(":")
                        key = key.strip().lower()
                        if key in ("model name", "hardware", "cpu model"):
                            val = val.strip()
                            if val:
                                return val
        except OSError:
            pass

    # Generic fallback
    machine = platform.machine()
    processor = platform.processor()
    return processor or machine or "Unknown"


def _get_total_memory_bytes() -> Optional[int]:
    """Return total physical memory in bytes using stdlib only."""
    system = platform.system()

    if system == "Linux":
        # Parse /proc/meminfo
        try:
            with open("/proc/meminfo", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        # Format: "MemTotal:     16384000 kB"
                        parts = line.split()
                        if len(parts) >= 2:
                            kb = int(parts[1])
                            return kb * 1024
        except (OSError, ValueError):
            pass

    if system == "Darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=3,
            )
            return int(result.stdout.strip())
        except Exception:
            pass

    return None


def _format_memory(bytes_: int) -> str:
    """Return a human-readable memory string, e.g. '16 GB' or '512 MB'."""
    gb = bytes_ / (1024 ** 3)
    if gb >= 1:
        # Round to nearest whole GB for clean display
        return f"{round(gb)} GB"
    mb = bytes_ / (1024 ** 2)
    return f"{round(mb)} MB"


def _format_uptime(seconds: float) -> str:
    """Return uptime as a compact human-readable string, e.g. '2d 3h' or '45m'."""
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"


def collect_system_info() -> dict:
    """Gather hardware/OS details using stdlib only. All fields are best-effort.

    When running in Docker on a non-Linux host, the container sees the VM's
    Linux.  Set ``HOST_PLATFORM`` to override ``os_version`` with the actual
    host OS (e.g. ``macOS 15.3 (Apple M1 Pro)``).
    """
    cpu_count = os.cpu_count()
    mem_bytes = _get_total_memory_bytes()

    os_version = os.environ.get("HOST_PLATFORM") or _get_os_version()

    info: dict = {
        "cpu_arch": platform.machine(),
        "os_version": os_version,
        "cpu_cores": cpu_count,
        "cpu_model": _get_cpu_model(),
        "total_memory": _format_memory(mem_bytes) if mem_bytes is not None else None,
        "uptime": _format_uptime(time.monotonic() - _PROCESS_START_TIME),
    }
    return info


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

# Active job counter — incremented/decremented by run_job(); main loop
# waits for this to reach zero before applying updates or re-registering.
_active_jobs: int = 0
_active_jobs_lock: threading.Lock = threading.Lock()

# ---------------------------------------------------------------------------
# Connectivity / auth state — deduplicate repeated log messages
# ---------------------------------------------------------------------------
# Both the heartbeat thread and the main poll loop share these flags.
# Python's GIL makes simple bool reads/writes atomic enough for this purpose.
_server_reachable: bool = True   # False once we've logged "server offline"
_auth_ok: bool = True            # False once we've logged "auth failed"
_reregister_needed: threading.Event = threading.Event()  # set by heartbeat on 404


def _is_idle() -> bool:
    """Return True when no jobs are currently running across all workers."""
    with _active_jobs_lock:
        return _active_jobs == 0


def _on_server_unreachable(exc: Exception) -> None:
    global _server_reachable
    if _server_reachable:
        logger.warning("Server went offline: %s", exc)
        _server_reachable = False


def _on_server_reachable() -> None:
    global _server_reachable
    if not _server_reachable:
        logger.info("Server came back online")
        _server_reachable = True


def _on_auth_failed() -> None:
    global _auth_ok
    if _auth_ok:
        logger.warning("Authentication failed (token mismatch?) — will keep retrying silently")
        _auth_ok = False


def _on_auth_ok() -> None:
    global _auth_ok
    if not _auth_ok:
        logger.info("Authentication restored")
        _auth_ok = True


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def post(path: str, data: dict, timeout: int = 30) -> requests.Response:
    url = f"{SERVER_URL}{path}"
    return requests.post(url, json=data, headers=HEADERS, timeout=timeout)


def get(path: str, params: Optional[dict] = None, timeout: int = 30) -> requests.Response:
    url = f"{SERVER_URL}{path}"
    return requests.get(url, params=params, headers={**HEADERS, "Content-Type": "application/json"}, timeout=timeout)


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
        pass
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
        pass


def deregister(client_id: str) -> None:
    """Tell the server to remove this client (best-effort on shutdown)."""
    try:
        resp = post("/api/v1/clients/deregister", {"client_id": client_id})
        if resp.ok:
            logger.info("Deregistered client %s", client_id)
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
            sysinfo = collect_system_info()
            payload: dict = {
                "hostname": HOSTNAME,
                "platform": PLATFORM,
                "client_version": CLIENT_VERSION,
                "max_parallel_jobs": MAX_PARALLEL_JOBS,
                "system_info": sysinfo,
            }
            if existing_id:
                payload["client_id"] = existing_id
            resp = post("/api/v1/clients/register", payload)
            resp.raise_for_status()
            client_id = resp.json()["client_id"]
            _save_client_id(client_id)
            logger.info("Registered as client %s (version %s)", client_id, CLIENT_VERSION)
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

def heartbeat_loop(client_id: str, stop_event: threading.Event) -> None:
    """Send heartbeats to the server until stop_event is set."""
    while not stop_event.is_set():
        try:
            resp = post("/api/v1/clients/heartbeat", {
                "client_id": client_id,
                "system_info": collect_system_info(),
            })
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
                data = resp.json()
                sv = data.get("server_client_version")
                if sv and sv != CLIENT_VERSION:
                    logger.info(
                        "Client update available: local=%s server=%s", CLIENT_VERSION, sv
                    )
                    _update_available.set()
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
        tar.extractall(path=dest_dir, filter="data")
    logger.debug("Bundle extracted to %s", dest_dir)


# ---------------------------------------------------------------------------
# Job runner
# ---------------------------------------------------------------------------

_update_attempts: int = 0
_MAX_UPDATE_ATTEMPTS: int = 3


def _apply_update(current_client_id: str) -> None:
    """Download updated client code from server and restart the process.

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
    logger.info("Downloading client update from server...")
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
        logger.info("Client updated to %s — restarting", new_version)
        os.environ["DISTRIBUTED_ESPHOME_CLIENT_ID"] = current_client_id
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as exc:
        logger.warning("Client update failed: %s", exc)


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
        pass

    # Extract device name for DNS fallback
    device_name = None
    try:
        with open(target_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _re.match(r'\s*name:\s*["\']?([a-zA-Z0-9_-]+)', line)
                if m:
                    device_name = m.group(1)
                    break
    except Exception:
        pass

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
        ping_summary = [l for l in ping_result.stdout.splitlines() if "packet" in l.lower() or "rtt" in l.lower() or "round-trip" in l.lower()]
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
        lines.append(f"Client IP: {our_ip} (source for reaching {device_addr})")
    except Exception:
        pass

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
                pass
    except Exception:
        pass

    diag_text = "\n".join(lines)
    logger.info("OTA diagnostics for %s:\n%s", device_addr, diag_text)
    return diag_text


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

    _log_context.current_target = target
    logger.info("Starting job %s: target=%s esphome=%s ota_only=%s", job_id, target, esphome_version, ota_only)

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

    # Install ESPHome version (BEFORE starting the timeout timer)
    if ESPHOME_BIN:
        esphome_bin = ESPHOME_BIN
        logger.info("Using esphome binary override: %s", esphome_bin)
    else:
        _report_status(job_id, f"Downloading ESPHome {esphome_version}")
        try:
            esphome_bin = version_manager.ensure_version(esphome_version)
            logger.info("Using esphome binary: %s", esphome_bin)
        except Exception as exc:
            logger.error("Failed to install esphome==%s: %s", esphome_version, exc)
            _submit_result(job_id, "failed", log=f"Version install failed: {exc}", ota_result=None)
            with _active_jobs_lock:
                _active_jobs -= 1
            return

    tmp_dir = tempfile.mkdtemp(prefix="esphome-job-")
    try:
        # Extract bundle
        try:
            extract_bundle(bundle_b64, tmp_dir)
        except Exception as exc:
            logger.error("Bundle extraction failed: %s", exc)
            _submit_result(job_id, "failed", log=f"Bundle extraction failed: {exc}", ota_result=None)
            return

        target_path = os.path.join(tmp_dir, target)
        if not os.path.exists(target_path):
            _submit_result(job_id, "failed", log=f"Target file not found in bundle: {target}", ota_result=None)
            return

        # ---------------------------------------------------------------
        # Compile phase — timer starts NOW
        # ---------------------------------------------------------------
        _report_status(job_id, "Compiling" + (" (OTA retry)" if ota_only else ""))
        compile_log, compile_ok = _run_subprocess(
            [esphome_bin, "compile", target_path],
            cwd=tmp_dir,
            timeout=timeout_seconds,
            label="compile",
            env=subprocess_env,
            job_id=job_id,
        )

        if not compile_ok:
            _submit_result(job_id, "failed", log=compile_log, ota_result=None)
            return

        # Compile succeeded — report success first
        _submit_result(job_id, "success", log=compile_log, ota_result=None)

        # ---------------------------------------------------------------
        # OTA phase (with one retry on failure)
        # ---------------------------------------------------------------
        ota_result = "failed"
        ota_logs: list[str] = []
        for attempt in range(2):
            if attempt > 0:
                logger.info("OTA failed, retrying in 5s (attempt %d/2)", attempt + 1)
                _report_status(job_id, "OTA Retry")
                time.sleep(5)
            _report_status(job_id, "OTA Upgrade")
            ota_log, ota_ok = _run_subprocess(
                [esphome_bin, "upload", target_path],
                cwd=tmp_dir,
                timeout=OTA_TIMEOUT,
                label=f"OTA upload (attempt {attempt + 1})",
                env=subprocess_env,
                job_id=job_id,
            )
            ota_logs.append(ota_log)
            if ota_ok:
                ota_result = "success"
                break
            if ota_log.endswith("TIMED OUT"):
                break  # Don't retry timeouts

        # Run network diagnostics on OTA failure to help debug
        if ota_result == "failed":
            diag = _ota_network_diagnostics(target_path, tmp_dir, subprocess_env)
            if diag:
                ota_logs.append("\n--- Network Diagnostics ---\n" + diag)

        logger.info("OTA result for job %s: %s", job_id, ota_result)
        _submit_ota_result(job_id, ota_result, "\n".join(ota_logs))

    finally:
        _log_context.current_target = None
        with _active_jobs_lock:
            _active_jobs -= 1
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            logger.debug("Cleaned up temp dir %s", tmp_dir)
        except Exception:
            pass


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
    FLUSH_INTERVAL = 2.0
    log_lines: list[str] = []
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
            pass  # non-critical

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            text=True,
            env=env,
        )
    except Exception as exc:
        return f"Failed to start process: {exc}", False

    def _kill_on_timeout():
        timed_out.set()
        try:
            proc.kill()
        except Exception:
            pass

    timer = threading.Timer(timeout, _kill_on_timeout)
    timer.start()
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            log_lines.append(line)
            flush_buffer.append(line)
            if time.monotonic() - last_flush >= FLUSH_INTERVAL:
                _flush_log()
        proc.wait()
        _flush_log()  # final flush
    finally:
        timer.cancel()

    if timed_out.is_set():
        log = "".join(log_lines) + f"\n\nTIMED OUT after {timeout}s"
        logger.warning("%s timed out after %ds", label, timeout)
        return log, False

    success = proc.returncode == 0
    log = "".join(log_lines)
    logger.info("%s finished: returncode=%d", label, proc.returncode)
    return log, success


def _report_status(job_id: str, status_text: str) -> None:
    """Fire-and-forget status update to server."""
    try:
        post(f"/api/v1/jobs/{job_id}/status", {"status_text": status_text}, timeout=5)
    except Exception:
        pass  # Non-critical; never block job execution on a status update failure


def _submit_result(
    job_id: str,
    status: str,
    log: Optional[str],
    ota_result: Optional[str],
) -> None:
    """POST job result to server, retrying a few times on network errors."""
    payload: dict = {"status": status, "log": log}
    if ota_result is not None:
        payload["ota_result"] = ota_result

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


def _submit_ota_result(job_id: str, ota_result: str, ota_log: str) -> None:
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
                job = resp.json()
                logger.info(
                    "Worker %d claimed job %s for target %s",
                    worker_id, job["job_id"], job["target"],
                )
                run_job(client_id, job, version_manager, worker_id)
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

    If the server has a newer client version, sets _update_available so the
    main loop applies the update before picking up any jobs.
    """
    try:
        resp = post("/api/v1/clients/heartbeat", {
            "client_id": client_id,
            "system_info": collect_system_info(),
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
        "ESPHome Build Client starting (hostname=%s, workers=%d)",
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
