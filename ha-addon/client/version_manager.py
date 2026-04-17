"""ESPHome version manager with LRU eviction."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
from collections import OrderedDict
from pathlib import Path

logger = logging.getLogger(__name__)

VERSIONS_BASE = Path(os.environ.get("ESPHOME_VERSIONS_DIR", "/esphome-versions"))
MAX_ESPHOME_VERSIONS = int(os.environ.get("MAX_ESPHOME_VERSIONS", "3"))
# Minimum free disk percentage before we start evicting versions
MIN_FREE_DISK_PCT = int(os.environ.get("MIN_FREE_DISK_PCT", "10"))

# SC.3: directory that holds `<version>.txt` hash-pinned constraints
# files, shipped inside the worker Docker image. When a file exists
# for the requested version, `_install` runs
# `pip install --require-hashes -c <file> esphome==<version>` so the
# wheel set cryptographically matches what we pinned.
ESPHOME_CONSTRAINTS_DIR = Path(__file__).parent / "esphome-constraints"


def _constraints_for(version: str) -> Path | None:
    """Return the hash-pinned constraints file path for *version*, or None.

    Per SC.3, a missing constraints file logs a WARNING in `_install`
    rather than refusing the install — keeps older ESPHome versions
    from getting locked out by this release. Roadmap (SECURITY_AUDIT
    F-18) is to flip this to a hard refusal once we ship constraints
    for every version we actually support.

    **Linux-only scope.** The committed constraints files are generated
    by `scripts/regen-esphome-constraints.sh` inside a `python:3.11-slim`
    (linux/amd64) container. `pip-compile` there only resolves the
    transitive deps for Linux — packages like `bleak` have a conditional
    `pyobjc-core>=10.3` dep gated on `platform_system == "Darwin"` that
    doesn't flow into the resolved graph on Linux and therefore isn't
    committed to the `.txt`. Trying `pip install --require-hashes -r <file>`
    on macOS then fails at install time with *"In --require-hashes mode,
    all requirements must have their versions pinned with ==: pyobjc-core
    from …"*. Linux workers (Docker containers, Raspberry Pi, x86_64
    build hosts) are the primary deployment target; macOS / Windows
    workers fall through to the WARN+unpinned path, preserving the
    pre-SC.3 behavior they had anyway.
    """
    if not sys.platform.startswith("linux"):
        logger.info(
            "Skipping hash-pinned install on %s — constraints files are "
            "linux-only (pip-compile doesn't resolve platform-conditional "
            "transitives like bleak→pyobjc-core on non-Darwin hosts). "
            "Unpinned install will proceed. (SC.3)",
            sys.platform,
        )
        return None
    candidate = ESPHOME_CONSTRAINTS_DIR / f"{version}.txt"
    return candidate if candidate.is_file() else None


class VersionManager:
    """
    Manages multiple ESPHome virtualenv installations.

    Each version lives in ``{VERSIONS_BASE}/{version}/``.
    An LRU cache evicts the oldest version when the count would
    exceed ``max_versions``.

    Thread-safe: multiple workers may call ensure_version() concurrently.
    Two workers requesting the same version share a single install run.
    """

    def __init__(
        self,
        versions_base: Path = VERSIONS_BASE,
        max_versions: int = MAX_ESPHOME_VERSIONS,
    ) -> None:
        self._base = versions_base
        self._max_versions = max_versions
        # OrderedDict[version_str, Path]: most-recent at end
        self._lru: OrderedDict[str, Path] = OrderedDict()
        self._lock = threading.Lock()
        # Per-version Events for in-progress installs; signals waiters when done
        self._installing: dict[str, threading.Event] = {}
        self._base.mkdir(parents=True, exist_ok=True)
        self._load_existing()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_existing(self) -> None:
        """Scan disk for already-installed versions and load them into LRU."""
        for entry in sorted(self._base.iterdir(), key=lambda p: p.stat().st_mtime):
            if entry.is_dir() and (entry / "bin" / "esphome").exists():
                self._lru[entry.name] = entry
        logger.info(
            "Found %d existing ESPHome versions: %s",
            len(self._lru),
            list(self._lru.keys()),
        )

    def _venv_path(self, version: str) -> Path:
        return self._base / version

    def _esphome_bin(self, version: str) -> Path:
        return self._venv_path(version) / "bin" / "esphome"

    def _is_installed(self, version: str) -> bool:
        return self._esphome_bin(version).exists()

    def _evict_lru(self, keep_version: str | None = None) -> bool:
        """Remove the least-recently-used version from disk and LRU cache.

        Must be called with self._lock held.
        Skips *keep_version* if provided (the version about to be installed).
        Returns True if a version was evicted, False if nothing to evict.
        """
        for version, path in self._lru.items():
            if version == keep_version:
                continue
            logger.info("Evicting ESPHome version %s from %s", version, path)
            try:
                shutil.rmtree(str(path), ignore_errors=True)
            except Exception:
                logger.exception("Failed to remove version dir %s", path)
            del self._lru[version]
            return True
        return False

    def _free_disk_pct(self) -> float | None:
        """Return free disk percentage on the versions volume, or None on error."""
        try:
            st = os.statvfs(str(self._base))
            total = st.f_frsize * st.f_blocks
            free = st.f_frsize * st.f_bavail
            return (free / total) * 100 if total > 0 else None
        except Exception:
            return None

    def _ensure_disk_space(self, keep_version: str | None = None) -> None:
        """Evict LRU versions until free disk exceeds MIN_FREE_DISK_PCT.

        Must be called with self._lock held.
        """
        while len(self._lru) > 1:  # always keep at least the current version
            pct = self._free_disk_pct()
            if pct is None or pct >= MIN_FREE_DISK_PCT:
                break
            logger.warning(
                "Disk free %.1f%% < %d%% threshold — evicting unused ESPHome version",
                pct, MIN_FREE_DISK_PCT,
            )
            if not self._evict_lru(keep_version=keep_version):
                break

    def _install(self, version: str) -> None:
        """Create a venv and install esphome==version into it.

        SC.3: when ``esphome-constraints/<version>.txt`` is present next
        to this module, the install runs with
        ``pip install --require-hashes --no-cache-dir -r <file>`` —
        every wheel (esphome + every transitive) must match one of the
        SHA-256 hashes in the file or pip refuses. Note `-r` (not `-c`):
        the generated file is a full hash-pinned **requirements** file
        (pip-compile output), not a constraints file — constraints
        files don't install anything on their own, and pip's
        `--require-hashes` mode fails if any requirement on the command
        line is unpinned (the original bug this replaces: `-c <file>
        esphome==<version>` gave 'Hashes are required in
        --require-hashes mode, but they are missing' for the
        command-line `esphome==<version>` arg).

        Missing constraints file → install proceeds unpinned with a
        WARNING logged; operators can see the gap in logs and ship a
        constraints file for that version in a follow-up image.

        Must NOT be called with self._lock held (long-running subprocess).
        """
        venv_dir = self._venv_path(version)
        logger.info("Installing esphome==%s into %s", version, venv_dir)

        # Create venv
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
            capture_output=True,
            text=True,
        )

        pip = venv_dir / "bin" / "pip"
        constraints_path = _constraints_for(version)
        install_cmd: list[str] = [str(pip), "install", "--no-cache-dir"]
        if constraints_path is not None:
            logger.info(
                "Using hash-pinned requirements for esphome==%s (SC.3): %s",
                version, constraints_path,
            )
            install_cmd.extend([
                "--require-hashes",
                "-r", str(constraints_path),
            ])
            # Note: no explicit `esphome==<version>` arg — the
            # requirements file already pins it (pip-compile output).
            # Adding it would reintroduce the "Hashes are required in
            # --require-hashes mode" error this branch exists to fix.
        else:
            logger.warning(
                "No hash-pinned constraints shipped for esphome==%s — "
                "install will resolve transitive deps unpinned. Generate "
                "one via scripts/regen-esphome-constraints.sh and bump "
                "IMAGE_VERSION in a follow-up image. (SC.3)",
                version,
            )
            install_cmd.append(f"esphome=={version}")

        logger.info("Running: %s", " ".join(install_cmd))
        result = subprocess.run(
            install_cmd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr_excerpt = (result.stderr or "")[-2000:]  # last 2000 chars
            stdout_excerpt = (result.stdout or "")[-1000:]
            logger.error(
                "pip install esphome==%s failed (exit %d):\nstderr: %s\nstdout: %s",
                version, result.returncode, stderr_excerpt, stdout_excerpt,
            )
            # Cleanup on failure
            shutil.rmtree(str(venv_dir), ignore_errors=True)
            raise RuntimeError(
                f"pip install esphome=={version} failed (exit {result.returncode}):\n"
                f"{stderr_excerpt}"
            )

        logger.info("esphome==%s installed successfully", version)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ensure_version(self, version: str) -> str:
        """
        Ensure ESPHome *version* is installed.

        Returns the path to the ``esphome`` binary.
        Installs if necessary; evicts LRU version if limit would be exceeded.
        Thread-safe: concurrent calls for the same version share one install.
        """
        while True:
            install_event: threading.Event | None = None
            wait_event: threading.Event | None = None

            with self._lock:
                if self._is_installed(version):
                    if version in self._lru:
                        self._lru.move_to_end(version)
                    else:
                        self._lru[version] = self._venv_path(version)
                    logger.debug("esphome==%s already installed", version)
                    return str(self._esphome_bin(version))

                if version in self._installing:
                    # Another thread is installing this version — wait for it
                    wait_event = self._installing[version]
                else:
                    # We'll do the install; evict if at capacity
                    while len(self._lru) >= self._max_versions:
                        self._evict_lru(keep_version=version)
                    # Also evict if disk is low
                    self._ensure_disk_space(keep_version=version)
                    install_event = threading.Event()
                    self._installing[version] = install_event

            if wait_event is not None:
                logger.debug("Waiting for esphome==%s install in progress...", version)
                if not wait_event.wait(timeout=600):  # 10 minute timeout
                    logger.error("Timed out waiting for esphome==%s install", version)
                    raise RuntimeError(f"Timed out waiting for esphome=={version} install (another thread may have crashed)")
                continue  # re-check from the top

            # We own the install — run outside the lock (slow subprocess)
            assert install_event is not None
            try:
                self._install(version)
                with self._lock:
                    self._lru[version] = self._venv_path(version)
                    self._installing.pop(version, None)
            except Exception:
                with self._lock:
                    self._installing.pop(version, None)
                install_event.set()  # wake up any waiters
                raise

            install_event.set()  # wake up waiters
            return str(self._esphome_bin(version))

    def get_esphome_path(self, version: str) -> str:
        """Return the path to the esphome binary for *version* (must be installed)."""
        path = self._esphome_bin(version)
        if not path.exists():
            raise FileNotFoundError(
                f"esphome=={version} is not installed at {path}. "
                "Call ensure_version() first."
            )
        with self._lock:
            if version in self._lru:
                self._lru.move_to_end(version)
        return str(path)

    def installed_versions(self) -> list[str]:
        """Return list of installed versions (LRU order, oldest first)."""
        with self._lock:
            return list(self._lru.keys())
