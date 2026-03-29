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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

SERVER_URL = os.environ["SERVER_URL"].rstrip("/")
SERVER_TOKEN = os.environ["SERVER_TOKEN"]
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "1"))
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "10"))
JOB_TIMEOUT = int(os.environ.get("JOB_TIMEOUT", "300"))
OTA_TIMEOUT = int(os.environ.get("OTA_TIMEOUT", "120"))
MAX_ESPHOME_VERSIONS = int(os.environ.get("MAX_ESPHOME_VERSIONS", "3"))
HOSTNAME = os.environ.get("HOSTNAME", socket.gethostname())
PLATFORM = os.environ.get("PLATFORM", sys.platform)
ESPHOME_BIN = os.environ.get("ESPHOME_BIN")  # If set, skip version manager
ESPHOME_SEED_VERSION = os.environ.get("ESPHOME_SEED_VERSION")  # Pre-download on startup

HEADERS = {
    "Authorization": f"Bearer {SERVER_TOKEN}",
    "Content-Type": "application/json",
}

# ---------------------------------------------------------------------------
# Client version — must match the add-on VERSION file; bumped on each release.
# The server returns this value in heartbeat responses so outdated clients
# can detect the mismatch and self-update.
# ---------------------------------------------------------------------------

CLIENT_VERSION = "0.0.2"

# Set when the heartbeat detects a newer server-side client bundle.
# Checked in the main loop so updates only happen between jobs.
_update_available: threading.Event = threading.Event()
_in_job: bool = False

# ---------------------------------------------------------------------------
# Connectivity / auth state — deduplicate repeated log messages
# ---------------------------------------------------------------------------
# Both the heartbeat thread and the main poll loop share these flags.
# Python's GIL makes simple bool reads/writes atomic enough for this purpose.
_server_reachable: bool = True   # False once we've logged "server offline"
_auth_ok: bool = True            # False once we've logged "auth failed"
_reregister_needed: threading.Event = threading.Event()  # set by heartbeat on 404


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
    """Register with server and return client_id. Retries until successful."""
    while True:
        try:
            resp = post("/api/v1/clients/register", {
                "hostname": HOSTNAME,
                "platform": PLATFORM,
                "client_version": CLIENT_VERSION,
            })
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


def _apply_update() -> None:
    """Download updated client code from server and restart the process."""
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
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as exc:
        logger.warning("Client update failed: %s", exc)


def run_job(client_id: str, job: dict, version_manager: VersionManager) -> None:
    """Execute a single build job end-to-end."""
    global _in_job
    _in_job = True
    job_id = job["job_id"]
    target = job["target"]
    esphome_version = job["esphome_version"]
    bundle_b64 = job["bundle_b64"]
    timeout_seconds = job.get("timeout_seconds", JOB_TIMEOUT)

    logger.info("Starting job %s: target=%s esphome=%s", job_id, target, esphome_version)

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
        _in_job = False
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
) -> tuple[str, bool]:
    """
    Run a subprocess with a timeout.

    Returns (combined_log, success).
    On timeout, kills the process and returns (log + 'TIMED OUT', False).
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
# Main polling loop
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("ESPHome Build Client starting (hostname=%s)", HOSTNAME)

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

    # Start heartbeat thread
    stop_heartbeat = threading.Event()
    hb_thread = threading.Thread(
        target=heartbeat_loop,
        args=(client_id, stop_heartbeat),
        daemon=True,
        name="heartbeat",
    )
    hb_thread.start()

    logger.info("Polling for jobs every %ds", POLL_INTERVAL)

    try:
        while True:
            # Re-register if the heartbeat told us the server doesn't know us
            if _reregister_needed.is_set() and not _in_job:
                _reregister_needed.clear()
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

            # Apply pending update only when idle (no job running)
            if _update_available.is_set() and not _in_job:
                _apply_update()  # may os.execv — never returns on success

            did_work = False
            try:
                resp = requests.get(
                    f"{SERVER_URL}/api/v1/jobs/next",
                    headers={**HEADERS, "X-Client-Id": client_id},
                    timeout=30,
                )
                _on_server_reachable()
                if resp.status_code == 401:
                    _on_auth_failed()
                elif resp.status_code == 204:
                    _on_auth_ok()
                elif resp.status_code == 200:
                    _on_auth_ok()
                    job = resp.json()
                    logger.info("Claimed job %s for target %s", job["job_id"], job["target"])
                    run_job(client_id, job, version_manager)
                    did_work = True
                else:
                    logger.warning("Unexpected response from jobs/next: %d", resp.status_code)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                _on_server_unreachable(exc)
            except Exception as exc:
                logger.exception("Unexpected error in poll loop: %s", exc)

            if not did_work:
                time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        stop_heartbeat.set()


if __name__ == "__main__":
    main()
