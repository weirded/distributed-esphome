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

    def _evict_lru(self) -> None:
        """Remove the least-recently-used version from disk and LRU cache.

        Must be called with self._lock held.
        """
        if not self._lru:
            return
        version, path = next(iter(self._lru.items()))
        logger.info("Evicting ESPHome version %s from %s", version, path)
        try:
            shutil.rmtree(str(path), ignore_errors=True)
        except Exception:
            logger.exception("Failed to remove version dir %s", path)
        del self._lru[version]

    def _install(self, version: str) -> None:
        """Create a venv and install esphome==version into it.

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
        result = subprocess.run(
            [str(pip), "install", "--no-cache-dir", f"esphome=={version}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Cleanup on failure
            shutil.rmtree(str(venv_dir), ignore_errors=True)
            raise RuntimeError(
                f"pip install esphome=={version} failed:\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
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
                        self._evict_lru()
                    install_event = threading.Event()
                    self._installing[version] = install_event

            if wait_event is not None:
                logger.debug("Waiting for esphome==%s install in progress...", version)
                wait_event.wait()
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
