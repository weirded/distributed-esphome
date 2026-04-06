"""Unit tests for client version management and timeout behavior."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from version_manager import VersionManager


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vm(tmp_path):
    """VersionManager with tmp_path as base and max 3 versions."""
    return VersionManager(versions_base=tmp_path, max_versions=3)


def _add_fake_version(tmp_path: Path, version: str) -> None:
    """Create a fake installed version directory with a stub esphome binary."""
    venv = tmp_path / version / "bin"
    venv.mkdir(parents=True, exist_ok=True)
    esphome = venv / "esphome"
    esphome.write_text("#!/bin/sh\necho fake esphome\n")
    esphome.chmod(0o755)


# ---------------------------------------------------------------------------
# VersionManager: basic operations
# ---------------------------------------------------------------------------

def test_installed_versions_empty(vm):
    assert vm.installed_versions() == []


def test_get_esphome_path_raises_if_not_installed(vm):
    with pytest.raises(FileNotFoundError):
        vm.get_esphome_path("9.9.9")


def test_get_esphome_path_returns_path_when_installed(tmp_path):
    _add_fake_version(tmp_path, "2024.3.1")
    vm = VersionManager(versions_base=tmp_path, max_versions=3)
    path = vm.get_esphome_path("2024.3.1")
    assert path.endswith("esphome")
    assert Path(path).exists()


def test_installed_versions_loaded_from_disk(tmp_path):
    _add_fake_version(tmp_path, "2024.1.0")
    _add_fake_version(tmp_path, "2024.2.0")
    vm = VersionManager(versions_base=tmp_path, max_versions=3)
    versions = vm.installed_versions()
    assert "2024.1.0" in versions
    assert "2024.2.0" in versions


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------

def test_eviction_at_limit_plus_one(tmp_path):
    """When 3 versions are installed and a 4th is requested, LRU is evicted."""
    _add_fake_version(tmp_path, "2024.1.0")
    _add_fake_version(tmp_path, "2024.2.0")
    _add_fake_version(tmp_path, "2024.3.0")
    vm = VersionManager(versions_base=tmp_path, max_versions=3)

    # Access order: 2024.1.0, 2024.2.0, 2024.3.0 (oldest = 2024.1.0)
    # Request a 4th version — pip install will be called
    with patch.object(vm, "_install") as mock_install:
        def fake_install(version):
            _add_fake_version(tmp_path, version)

        mock_install.side_effect = fake_install
        vm.ensure_version("2024.4.0")

    # 2024.1.0 (LRU) should have been evicted
    remaining = vm.installed_versions()
    assert "2024.1.0" not in remaining
    assert "2024.4.0" in remaining
    assert len(remaining) <= 3


def test_eviction_respects_lru_order(tmp_path):
    """After accessing version 1, version 2 becomes the LRU."""
    _add_fake_version(tmp_path, "v1")
    _add_fake_version(tmp_path, "v2")
    _add_fake_version(tmp_path, "v3")
    vm = VersionManager(versions_base=tmp_path, max_versions=3)

    # Access v1 to make it MRU
    vm.get_esphome_path("v1")  # now LRU = v2

    evicted = []

    def fake_evict(keep_version=None):
        for version in vm._lru:
            if version == keep_version:
                continue
            evicted.append(version)
            del vm._lru[version]
            return True
        return False

    with patch.object(vm, "_evict_lru", side_effect=fake_evict):
        with patch.object(vm, "_install", side_effect=lambda v: _add_fake_version(tmp_path, v)):
            vm.ensure_version("v4")

    assert evicted[0] == "v2", f"Expected v2 to be evicted, got {evicted}"


def test_no_eviction_under_limit(tmp_path):
    """Installing a version when under the limit should not evict anything."""
    _add_fake_version(tmp_path, "v1")
    _add_fake_version(tmp_path, "v2")
    vm = VersionManager(versions_base=tmp_path, max_versions=3)

    with patch.object(vm, "_evict_lru") as mock_evict:
        with patch.object(vm, "_install", side_effect=lambda v: _add_fake_version(tmp_path, v)):
            vm.ensure_version("v3")

    mock_evict.assert_not_called()


def test_already_installed_no_reinstall(tmp_path):
    """ensure_version on an already-installed version must not call _install."""
    _add_fake_version(tmp_path, "2024.3.1")
    vm = VersionManager(versions_base=tmp_path, max_versions=3)

    with patch.object(vm, "_install") as mock_install:
        path = vm.ensure_version("2024.3.1")

    mock_install.assert_not_called()
    assert "esphome" in path


def test_ensure_version_updates_lru(tmp_path):
    """Accessing a version should move it to the end (MRU) in the LRU dict."""
    _add_fake_version(tmp_path, "v1")
    _add_fake_version(tmp_path, "v2")
    vm = VersionManager(versions_base=tmp_path, max_versions=3)

    # v1 and v2 loaded; v1 first (LRU)
    vm.ensure_version("v1")  # access v1 -> move to MRU

    lru_keys = list(vm._lru.keys())
    assert lru_keys[-1] == "v1", f"v1 should be MRU; got {lru_keys}"


# ---------------------------------------------------------------------------
# Subprocess timeout simulation (tests _run_subprocess indirectly)
# ---------------------------------------------------------------------------

def test_run_subprocess_success(tmp_path):
    """Import and test _run_subprocess directly."""
    import client as client_module  # noqa: PLC0415

    log, ok = client_module._run_subprocess(
        [sys.executable, "-c", "print('hello')"],
        cwd=str(tmp_path),
        timeout=10,
        label="test",
    )
    assert ok
    assert "hello" in log


def test_run_subprocess_failure(tmp_path):
    import client as client_module  # noqa: PLC0415

    log, ok = client_module._run_subprocess(
        [sys.executable, "-c", "import sys; sys.exit(1)"],
        cwd=str(tmp_path),
        timeout=10,
        label="test-fail",
    )
    assert not ok


def test_run_subprocess_timeout(tmp_path):
    """A process that sleeps longer than timeout should be killed and return TIMED OUT."""
    import client as client_module  # noqa: PLC0415

    log, ok = client_module._run_subprocess(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=str(tmp_path),
        timeout=1,
        label="test-timeout",
    )
    assert not ok
    assert "TIMED OUT" in log


def test_run_subprocess_captures_output(tmp_path):
    import client as client_module  # noqa: PLC0415

    log, ok = client_module._run_subprocess(
        [sys.executable, "-c", "print('stdout line'); import sys; print('stderr line', file=sys.stderr)"],
        cwd=str(tmp_path),
        timeout=10,
        label="test-output",
    )
    assert ok
    assert "stdout line" in log


# ---------------------------------------------------------------------------
# client.py: ensure SERVER_URL and SERVER_TOKEN env vars are set for import
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def set_required_env(monkeypatch):
    monkeypatch.setenv("SERVER_URL", "http://localhost:8765")
    monkeypatch.setenv("SERVER_TOKEN", "test-token")
