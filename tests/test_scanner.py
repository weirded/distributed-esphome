"""Unit tests for the YAML scanner and bundle creator."""

from __future__ import annotations

import io
import sys
import tarfile
from pathlib import Path

import pytest

# Make server code importable
sys.path.insert(0, str(Path(__file__).parent.parent / "ha-addon" / "server"))

from scanner import create_bundle, get_esphome_version, scan_configs  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "esphome_configs"


# ---------------------------------------------------------------------------
# scan_configs
# ---------------------------------------------------------------------------

def test_scan_finds_yaml_files():
    targets = scan_configs(str(FIXTURES))
    assert "device1.yaml" in targets
    assert "device2.yaml" in targets


def test_scan_excludes_secrets_yaml():
    targets = scan_configs(str(FIXTURES))
    assert "secrets.yaml" not in targets
    assert not any(t.lower() == "secrets.yaml" for t in targets)


def test_scan_excludes_subdirectory_yaml():
    """Only top-level YAMLs should be returned."""
    targets = scan_configs(str(FIXTURES))
    assert not any("packages" in t for t in targets)


def test_scan_nonexistent_dir():
    targets = scan_configs("/nonexistent/path/that/does/not/exist")
    assert targets == []


def test_scan_returns_sorted_list():
    targets = scan_configs(str(FIXTURES))
    assert targets == sorted(targets)


def test_scan_only_returns_filenames():
    """Results should be filenames only, not full paths."""
    targets = scan_configs(str(FIXTURES))
    for t in targets:
        assert "/" not in t
        assert t.endswith(".yaml")


def test_scan_empty_dir(tmp_path):
    targets = scan_configs(str(tmp_path))
    assert targets == []


def test_scan_dir_with_only_secrets(tmp_path):
    (tmp_path / "secrets.yaml").write_text("key: val")
    targets = scan_configs(str(tmp_path))
    assert targets == []


# ---------------------------------------------------------------------------
# create_bundle
# ---------------------------------------------------------------------------

def test_bundle_is_tar_gz():
    raw = create_bundle(str(FIXTURES))
    assert isinstance(raw, bytes)
    assert len(raw) > 0
    # gzip magic bytes
    assert raw[:2] == b"\x1f\x8b"


def test_bundle_includes_secrets_yaml():
    raw = create_bundle(str(FIXTURES))
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        names = tar.getnames()
    assert "secrets.yaml" in names


def test_bundle_includes_device_yamls():
    raw = create_bundle(str(FIXTURES))
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        names = tar.getnames()
    assert "device1.yaml" in names
    assert "device2.yaml" in names


def test_bundle_includes_subdirectory():
    raw = create_bundle(str(FIXTURES))
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        names = tar.getnames()
    assert any("packages" in n for n in names), f"packages/ not found in bundle: {names}"
    assert any("common.yaml" in n for n in names)


def test_bundle_preserves_content():
    raw = create_bundle(str(FIXTURES))
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        f = tar.extractfile("secrets.yaml")
        content = f.read().decode()
    assert "wifi_ssid" in content
    assert "wifi_password" in content


def test_bundle_paths_are_relative():
    """Archive paths should not start with '/' (absolute) or include the base dir prefix."""
    raw = create_bundle(str(FIXTURES))
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        for name in tar.getnames():
            assert not name.startswith("/"), f"Absolute path in bundle: {name}"


def test_bundle_empty_dir(tmp_path):
    """Bundle of empty directory should be a valid but empty tar.gz."""
    raw = create_bundle(str(tmp_path))
    assert raw[:2] == b"\x1f\x8b"
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        assert tar.getnames() == []


# ---------------------------------------------------------------------------
# get_esphome_version
# ---------------------------------------------------------------------------

def test_get_esphome_version_returns_string():
    ver = get_esphome_version()
    assert isinstance(ver, str)
    assert len(ver) > 0


def test_get_esphome_version_returns_unknown_when_not_installed():
    """If esphome is not installed, should return 'unknown' without crashing."""
    import importlib.metadata as meta
    original = meta.version

    def mock_version(pkg):
        if pkg == "esphome":
            raise meta.PackageNotFoundError(pkg)
        return original(pkg)

    meta.version = mock_version
    try:
        ver = get_esphome_version()
        assert ver == "unknown"
    finally:
        meta.version = original
