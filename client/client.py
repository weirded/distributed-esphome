"""ESPHome distributed build client — polling loop, heartbeat, job runner."""

from __future__ import annotations

import base64
import io
import logging
import os
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

CLIENT_VERSION = "0.0.13"

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

def register() -> str:
    """Register with server and return client_id. Retries until successful.

    If DISTRIBUTED_ESPHOME_CLIENT_ID is set in the environment (stashed before
    an auto-update os.execv), sends it so the server can update in place.
    """
    existing_id = os.environ.pop("DISTRIBUTED_ESPHOME_CLIENT_ID", None)
    while True:
        try:
            payload: dict = {
                "hostname": HOSTNAME,
                "platform": PLATFORM,
                "client_version": CLIENT_VERSION,
                "max_parallel_jobs": MAX_PARALLEL_JOBS,
            }
            if existing_id:
                payload["client_id"] = existing_id
            resp = post("/api/v1/clients/register", payload)
            resp.raise_for_status()
            client_id = resp.json()["client_id"]
            logger.info("Registered as client %s (version %s)", client_id, CLIENT_VERSION)
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
            resp = post("/api/v1/clients/heartbeat", {"client_id": client_id})
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

    _log_context.current_target = target
    logger.info("Starting job %s: target=%s esphome=%s", job_id, target, esphome_version)

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
        _report_status(job_id, "Compiling")
        compile_log, compile_ok = _run_subprocess(
            [esphome_bin, "compile", target_path],
            cwd=tmp_dir,
            timeout=timeout_seconds,
            label="compile",
            env=subprocess_env,
        )

        if not compile_ok:
            if compile_log.endswith("TIMED OUT"):
                _submit_result(job_id, "failed", log=compile_log, ota_result=None)
            else:
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
            )
            ota_logs.append(ota_log)
            if ota_ok:
                ota_result = "success"
                break
            if ota_log.endswith("TIMED OUT"):
                break  # Don't retry timeouts

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
) -> tuple[str, bool]:
    """
    Run a subprocess with a timeout.

    Returns (combined_log, success).
    On timeout, kills the process and returns (log + 'TIMED OUT', False).
    *env* is passed directly to Popen; defaults to inheriting the current env.
    """
    log_lines: list[str] = []
    logger.info("Running %s: %s", label, " ".join(cmd))

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

    try:
        stdout, _ = proc.communicate(timeout=timeout)
        if stdout:
            log_lines.append(stdout)
        success = proc.returncode == 0
        log = "".join(log_lines)
        logger.info("%s finished: returncode=%d", label, proc.returncode)
        return log, success
    except subprocess.TimeoutExpired:
        proc.kill()
        remaining, _ = proc.communicate()
        if remaining:
            log_lines.append(remaining)
        log = "".join(log_lines) + f"\n\nTIMED OUT after {timeout}s"
        logger.warning("%s timed out after %ds", label, timeout)
        return log, False
    except Exception as exc:
        try:
            proc.kill()
        except Exception:
            pass
        return f"Unexpected error: {exc}", False


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
        resp = post("/api/v1/clients/heartbeat", {"client_id": client_id}, timeout=10)
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
    logger.info(
        "ESPHome Build Client starting (hostname=%s, workers=%d)",
        HOSTNAME, MAX_PARALLEL_JOBS,
    )

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
        while True:
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
        logger.info("Shutting down")
    finally:
        worker_stop.set()
        stop_heartbeat.set()


if __name__ == "__main__":
    main()
