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


# ---------------------------------------------------------------------------
# B.1 — VersionManager concurrency stress tests
# ---------------------------------------------------------------------------

def test_ensure_version_concurrent_same_version_installs_once(tmp_path):
    """10 threads requesting the same version must trigger exactly one install.

    The other 9 threads must block on the shared ``_installing`` event and
    return the same esphome binary path once the installer finishes. Regression
    for the race where two threads both decide to install before either sets
    ``_installing[version]``.
    """
    vm = VersionManager(versions_base=tmp_path, max_versions=3)

    install_calls: list[str] = []
    install_call_lock = threading.Lock()
    install_started = threading.Event()
    release_install = threading.Event()

    def slow_install(version: str) -> None:
        """Simulate a slow pip install — hold the version lock so all other
        threads have time to arrive at the waiter branch."""
        with install_call_lock:
            install_calls.append(version)
        install_started.set()
        # Block until the test tells us to finish, so we can verify the other
        # 9 threads are all blocked on the shared install event.
        release_install.wait(timeout=5)
        _add_fake_version(tmp_path, version)

    results: list[str] = []
    errors: list[Exception] = []
    results_lock = threading.Lock()

    def worker() -> None:
        try:
            path = vm.ensure_version("2026.3.3")
            with results_lock:
                results.append(path)
        except Exception as exc:  # pragma: no cover — fail the test if hit
            errors.append(exc)

    with patch.object(vm, "_install", side_effect=slow_install):
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()

        # Wait for the installer thread to actually start, then give the
        # other 9 threads a beat to arrive at the wait branch.
        assert install_started.wait(timeout=2), "installer did not start"
        time.sleep(0.2)

        # Release the installer so every thread can proceed.
        release_install.set()

        for t in threads:
            t.join(timeout=10)

    assert not errors, f"worker threads raised: {errors}"
    assert len(results) == 10
    # Exactly one install call despite 10 concurrent requests.
    assert install_calls == ["2026.3.3"], (
        f"expected single install, got {install_calls}"
    )
    # All threads returned the same binary path.
    assert len(set(results)) == 1


def test_ensure_version_concurrent_distinct_versions_all_install(tmp_path):
    """Multiple threads requesting different versions each trigger their own
    install in parallel. No deadlock, no cross-contamination."""
    vm = VersionManager(versions_base=tmp_path, max_versions=10)

    install_calls: list[str] = []
    install_call_lock = threading.Lock()

    def fake_install(version: str) -> None:
        with install_call_lock:
            install_calls.append(version)
        # A brief sleep so the installs overlap in time.
        time.sleep(0.05)
        _add_fake_version(tmp_path, version)

    errors: list[Exception] = []

    def worker(version: str) -> None:
        try:
            vm.ensure_version(version)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    with patch.object(vm, "_install", side_effect=fake_install):
        versions = [f"2026.{i}.0" for i in range(5)]
        threads = [threading.Thread(target=worker, args=(v,)) for v in versions]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

    assert not errors
    assert sorted(install_calls) == sorted(versions)
    # LRU contains exactly the 5 installed versions (max was 10, no eviction).
    assert set(vm.installed_versions()) == set(versions)


def test_ensure_version_lru_full_preserves_keep_version_under_contention(tmp_path):
    """When the LRU is full and a new version is being installed, the
    installing version must never be evicted even while another thread is
    actively asking for it (``keep_version`` contract)."""
    # Pre-seed max_versions distinct installs.
    _add_fake_version(tmp_path, "v1")
    _add_fake_version(tmp_path, "v2")
    _add_fake_version(tmp_path, "v3")
    vm = VersionManager(versions_base=tmp_path, max_versions=3)

    # Touch v2 and v3 so v1 is the LRU.
    vm.get_esphome_path("v2")
    vm.get_esphome_path("v3")

    install_started = threading.Event()
    release_install = threading.Event()

    def slow_install(version: str) -> None:
        install_started.set()
        release_install.wait(timeout=5)
        _add_fake_version(tmp_path, version)

    errors: list[Exception] = []

    def installer() -> None:
        try:
            vm.ensure_version("v4")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    with patch.object(vm, "_install", side_effect=slow_install):
        t_install = threading.Thread(target=installer)
        t_install.start()

        # Wait for the installer to start. At this point v1 has been evicted
        # (to make room for v4) and v4 is in _installing.
        assert install_started.wait(timeout=2)

        # Spawn another thread that asks for v4 — it should block on the
        # install event and never cause v4 itself to be evicted.
        waiter_done = threading.Event()

        def waiter() -> None:
            try:
                vm.ensure_version("v4")
            finally:
                waiter_done.set()

        t_wait = threading.Thread(target=waiter)
        t_wait.start()

        # Release the installer.
        release_install.set()

        t_install.join(timeout=10)
        t_wait.join(timeout=10)
        assert waiter_done.is_set()

    assert not errors
    # v1 was the LRU, so it should have been evicted to make room for v4.
    # v4 must still be present — neither thread should have evicted the version
    # currently being installed.
    remaining = set(vm.installed_versions())
    assert "v4" in remaining
    assert "v1" not in remaining
    assert len(remaining) <= 3


# ---------------------------------------------------------------------------
# B.4 — OTA retry regression test (bug #177)
#
# The retry path after a successful compile + failed OTA must use
# ``esphome upload``, NOT ``esphome run``, and must NOT pass ``--no-logs``
# (which ``esphome upload`` rejects with "unrecognized arguments").
# ---------------------------------------------------------------------------

def test_run_job_ota_retry_uses_upload_without_no_logs(tmp_path, monkeypatch):
    import client as client_module

    # The run_job function touches a lot — install, extract, subprocess,
    # result submission. We stub every collaborator so only the command-
    # construction logic runs.
    _add_fake_version(tmp_path, "2024.3.1")

    # #13: run_job now uses a stable per-target build dir under
    # _ESPHOME_VERSIONS_DIR. Point it at tmp_path so the test doesn't
    # try to write to /esphome-versions/.
    monkeypatch.setattr(client_module, "_ESPHOME_VERSIONS_DIR", str(tmp_path))

    commands: list[list[str]] = []

    def fake_run_subprocess(cmd, cwd, timeout, label, env=None, job_id=None):
        commands.append(list(cmd))
        # First call = "compile+OTA" via `esphome run`: simulate a compile
        # success + OTA failure. Subsequent call = retry via `esphome upload`:
        # simulate a fresh (uninteresting) success.
        if label == "compile+OTA":
            return (
                "INFO Successfully compiled program.\nERROR Error resolving OTA target: Connect failed\n",
                False,
            )
        return ("upload ok", True)

    submitted: list[tuple[str, str, object]] = []

    def fake_submit(job_id, status, log=None, ota_result=None):
        submitted.append((status, ota_result, log))

    monkeypatch.setattr(client_module, "_run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(client_module, "_submit_result", fake_submit)
    monkeypatch.setattr(client_module, "_flush_log_text", lambda *a, **k: None)
    monkeypatch.setattr(client_module, "_log_invocation", lambda *a, **k: None)
    monkeypatch.setattr(client_module, "_report_status", lambda *a, **k: None)
    # Skip the OTA diagnostics network calls on failure path.
    monkeypatch.setattr(client_module, "_ota_network_diagnostics", lambda *a, **k: "")
    # Skip the 5-second sleep between compile and retry.
    monkeypatch.setattr(client_module.time, "sleep", lambda _s: None)

    # Minimal bundle: a tar.gz containing a single empty target YAML.
    import base64
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"esphome:\n  name: dev\n"
        info = tarfile.TarInfo(name="dev.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    bundle_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    vm = VersionManager(versions_base=tmp_path, max_versions=3)
    job = {
        "job_id": "j1",
        "target": "dev.yaml",
        "esphome_version": "2024.3.1",
        "bundle_b64": bundle_b64,
        "timeout_seconds": 60,
        "ota_only": False,
        "validate_only": False,
        "ota_address": "10.0.0.5",
    }

    client_module.run_job("client-1", job, vm, worker_id=1)

    # Exactly two subprocess invocations: compile+OTA run, then upload retry.
    assert len(commands) == 2, f"expected 2 subprocess calls, got {len(commands)}: {commands}"

    first, second = commands
    # First call: `esphome run ... --no-logs ... --device 10.0.0.5`
    assert "run" in first and "--no-logs" in first and "--device" in first
    assert "10.0.0.5" in first

    # Second call: `esphome upload` — MUST NOT contain --no-logs or `run`.
    assert "upload" in second, f"retry must use 'upload' verb: {second}"
    assert "run" not in second, f"retry must NOT use 'run' verb: {second}"
    assert "--no-logs" not in second, (
        f"retry command must NOT pass --no-logs (esphome upload rejects it): {second}"
    )
    assert "--device" in second and "10.0.0.5" in second

    # The result submission records the OTA retry succeeded.
    assert submitted[-1][0] == "success"
    assert submitted[-1][1] == "success"


# ---------------------------------------------------------------------------
# #45 — Per-slot working dirs + shared per-target cache
# ---------------------------------------------------------------------------


def test_slot_and_cache_dir_helpers(tmp_path, monkeypatch):
    """_slot_dir and _cache_dir compose the expected paths under the base."""
    import client as client_module  # noqa: PLC0415
    monkeypatch.setattr(client_module, "_ESPHOME_VERSIONS_DIR", str(tmp_path))
    assert client_module._slot_dir(2, "kitchen") == str(tmp_path / "slots" / "2" / "kitchen")
    assert client_module._cache_dir("kitchen") == str(tmp_path / "cache" / "kitchen")


def test_copytree_replace_overwrites_existing(tmp_path):
    """_copytree_replace wipes the destination tree before copying."""
    import client as client_module  # noqa: PLC0415

    src = tmp_path / "src"
    src.mkdir()
    (src / "new.txt").write_text("new")

    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "stale.txt").write_text("stale")

    client_module._copytree_replace(str(src), str(dst))

    # Old file is gone, new file is present
    assert not (dst / "stale.txt").exists()
    assert (dst / "new.txt").read_text() == "new"


def test_copytree_replace_noop_when_src_missing(tmp_path):
    """Missing source is a silent no-op (dst left intact)."""
    import client as client_module  # noqa: PLC0415
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "keep.txt").write_text("keep")
    client_module._copytree_replace(str(tmp_path / "missing"), str(dst))
    assert (dst / "keep.txt").read_text() == "keep"


def test_sync_cache_into_slot_seeds_pio_on_first_compile(tmp_path, monkeypatch):
    """Slot with no .pio/ pulls from the shared cache on sync-in."""
    import client as client_module  # noqa: PLC0415
    monkeypatch.setattr(client_module, "_ESPHOME_VERSIONS_DIR", str(tmp_path))

    # Seed cache
    cache_pio = tmp_path / "cache" / "dev" / ".pio" / "build"
    cache_pio.mkdir(parents=True)
    (cache_pio / "firmware.o").write_text("obj")

    # Empty slot dir
    slot_dir = tmp_path / "slots" / "1" / "dev"
    slot_dir.mkdir(parents=True)

    client_module._sync_cache_into_slot("dev", str(slot_dir))

    # .pio/ is now populated in the slot dir
    assert (slot_dir / ".pio" / "build" / "firmware.o").read_text() == "obj"


def test_sync_cache_into_slot_skips_when_slot_already_has_pio(tmp_path, monkeypatch):
    """If the slot already has its own .pio/, the sync-in is a no-op — the
    slot's local cache is more relevant than the shared one."""
    import client as client_module  # noqa: PLC0415
    monkeypatch.setattr(client_module, "_ESPHOME_VERSIONS_DIR", str(tmp_path))

    # Cache has one version
    cache_pio = tmp_path / "cache" / "dev" / ".pio"
    cache_pio.mkdir(parents=True)
    (cache_pio / "shared.txt").write_text("cache")

    # Slot already has its own version
    slot_pio = tmp_path / "slots" / "1" / "dev" / ".pio"
    slot_pio.mkdir(parents=True)
    (slot_pio / "local.txt").write_text("slot")

    client_module._sync_cache_into_slot("dev", str(slot_pio.parent))

    # Slot kept its own state, didn't adopt shared cache
    assert (slot_pio / "local.txt").exists()
    assert not (slot_pio / "shared.txt").exists()


def test_sync_slot_into_cache_promotes_to_shared(tmp_path, monkeypatch):
    """After a successful compile, slot .pio/ is promoted to the shared cache."""
    import client as client_module  # noqa: PLC0415
    monkeypatch.setattr(client_module, "_ESPHOME_VERSIONS_DIR", str(tmp_path))

    slot_pio = tmp_path / "slots" / "2" / "dev" / ".pio" / "build"
    slot_pio.mkdir(parents=True)
    (slot_pio / "firmware.bin").write_text("binary")

    client_module._sync_slot_into_cache("dev", str(slot_pio.parent.parent))

    cache_firmware = tmp_path / "cache" / "dev" / ".pio" / "build" / "firmware.bin"
    assert cache_firmware.read_text() == "binary"


def test_sync_slot_into_cache_replaces_old_cache(tmp_path, monkeypatch):
    """Sync-out replaces the entire cache tree (stale files in cache removed)."""
    import client as client_module  # noqa: PLC0415
    monkeypatch.setattr(client_module, "_ESPHOME_VERSIONS_DIR", str(tmp_path))

    # Old cache has a stale artifact
    cache_build = tmp_path / "cache" / "dev" / ".pio" / "build"
    cache_build.mkdir(parents=True)
    (cache_build / "stale.o").write_text("stale")

    # Slot has a fresh compile result
    slot_build = tmp_path / "slots" / "1" / "dev" / ".pio" / "build"
    slot_build.mkdir(parents=True)
    (slot_build / "fresh.o").write_text("fresh")

    client_module._sync_slot_into_cache("dev", str(slot_build.parent.parent))

    # Stale gone, fresh present
    assert not (cache_build / "stale.o").exists()
    assert (cache_build / "fresh.o").read_text() == "fresh"


def test_target_cache_lock_is_exclusive(tmp_path, monkeypatch):
    """Two threads trying to acquire the same per-target lock are serialized."""
    import client as client_module  # noqa: PLC0415
    import threading as _threading
    import time as _time
    monkeypatch.setattr(client_module, "_ESPHOME_VERSIONS_DIR", str(tmp_path))

    events: list[tuple[str, float]] = []
    start = _threading.Event()

    def worker(name: str, hold_for: float) -> None:
        start.wait()
        with client_module._target_cache_lock("dev"):
            events.append((f"{name}-acquired", _time.monotonic()))
            _time.sleep(hold_for)
            events.append((f"{name}-released", _time.monotonic()))

    t1 = _threading.Thread(target=worker, args=("a", 0.15))
    t2 = _threading.Thread(target=worker, args=("b", 0.05))
    t1.start()
    t2.start()
    start.set()
    t1.join()
    t2.join()

    # Exactly 4 events, first-acquired then first-released then second-acquired then second-released
    assert len(events) == 4
    seq = [e[0].split("-")[1] for e in events]
    assert seq == ["acquired", "released", "acquired", "released"], (
        f"lock not exclusive, events: {events}"
    )


def test_clean_build_cache_preserves_esphome_venvs(tmp_path, monkeypatch):
    """Regression for bug #119: "Clean Cache" must not wipe ESPHome venvs.

    The embedded local-worker shares ``/data/esphome-versions/`` with the
    server's lazy-installed venv. Pre-fix, ``_clean_build_cache`` blindly
    rmtree'd every subdirectory — including the venv the server was
    actively using — leaving the server unable to bundle until restart.
    Anything with ``bin/esphome`` is now preserved.
    """
    import client as client_module  # noqa: PLC0415
    monkeypatch.setattr(client_module, "_ESPHOME_VERSIONS_DIR", str(tmp_path))

    # Two ESPHome venvs (have bin/esphome) — must survive the clean.
    for ver in ("2026.4.2", "2026.4.3"):
        (tmp_path / ver / "bin").mkdir(parents=True)
        (tmp_path / ver / "bin" / "esphome").write_text("#!/bin/sh\n")

    # Build cache directories — must be removed.
    (tmp_path / "cache" / "dev").mkdir(parents=True)
    (tmp_path / "slots" / "1" / "dev").mkdir(parents=True)
    (tmp_path / "pio-slot-1").mkdir()
    (tmp_path / "platformio").mkdir()

    client_module._clean_build_cache()

    # Venvs preserved
    assert (tmp_path / "2026.4.2" / "bin" / "esphome").exists()
    assert (tmp_path / "2026.4.3" / "bin" / "esphome").exists()

    # Build caches gone
    assert not (tmp_path / "cache").exists()
    assert not (tmp_path / "slots").exists()
    assert not (tmp_path / "pio-slot-1").exists()
    assert not (tmp_path / "platformio").exists()


def test_clean_build_cache_removes_all_when_no_venvs(tmp_path, monkeypatch):
    """When the directory has no venv-shaped dirs, every subdir is removed."""
    import client as client_module  # noqa: PLC0415
    monkeypatch.setattr(client_module, "_ESPHOME_VERSIONS_DIR", str(tmp_path))

    (tmp_path / "cache" / "dev").mkdir(parents=True)
    (tmp_path / "slots").mkdir()
    (tmp_path / "platformio").mkdir()

    client_module._clean_build_cache()

    assert list(tmp_path.iterdir()) == []
