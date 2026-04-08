"""Unit tests for the YAML scanner and bundle creator."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from scanner import (
    build_name_to_target_map,
    create_bundle,
    get_device_metadata,
    get_esphome_version,
    scan_configs,
)

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


# ---------------------------------------------------------------------------
# get_device_metadata — extracting name/friendly_name/area/comment/project
# ---------------------------------------------------------------------------

def _write_yaml(config_dir: Path, name: str, content: str) -> None:
    (config_dir / name).write_text(content)


def test_metadata_extracts_name_and_friendly_name(tmp_path):
    _write_yaml(tmp_path, "dev.yaml", """\
esphome:
  name: living-room-sensor
  friendly_name: Living Room Sensor

esp8266:
  board: d1_mini
""")
    meta = get_device_metadata(str(tmp_path), "dev.yaml")
    assert meta["device_name_raw"] == "living-room-sensor"
    assert meta["device_name"] == "Living Room Sensor"
    assert meta["friendly_name"] == "Living Room Sensor"


def test_metadata_extracts_area_and_comment(tmp_path):
    _write_yaml(tmp_path, "dev.yaml", """\
esphome:
  name: dev
  area: Kitchen
  comment: Over the sink

esp8266:
  board: d1_mini
""")
    meta = get_device_metadata(str(tmp_path), "dev.yaml")
    assert meta["area"] == "Kitchen"
    assert meta["comment"] == "Over the sink"


def test_metadata_extracts_project(tmp_path):
    _write_yaml(tmp_path, "dev.yaml", """\
esphome:
  name: dev
  project:
    name: example.device
    version: "1.2.3"

esp8266:
  board: d1_mini
""")
    meta = get_device_metadata(str(tmp_path), "dev.yaml")
    assert meta["project_name"] == "example.device"
    assert meta["project_version"] == "1.2.3"


def test_metadata_detects_web_server(tmp_path):
    _write_yaml(tmp_path, "dev.yaml", """\
esphome:
  name: dev

esp8266:
  board: d1_mini

web_server:
  port: 80
""")
    meta = get_device_metadata(str(tmp_path), "dev.yaml")
    assert meta["has_web_server"] is True


def test_metadata_missing_web_server(tmp_path):
    _write_yaml(tmp_path, "dev.yaml", """\
esphome:
  name: dev

esp8266:
  board: d1_mini
""")
    meta = get_device_metadata(str(tmp_path), "dev.yaml")
    assert meta["has_web_server"] is False


def test_metadata_substitutions_resolved(tmp_path):
    """${substitutions} in area/comment should be resolved from the substitutions block."""
    _write_yaml(tmp_path, "dev.yaml", """\
substitutions:
  device_name: living_room
  room_area: Living Room

esphome:
  name: ${device_name}
  area: ${room_area}

esp8266:
  board: d1_mini
""")
    meta = get_device_metadata(str(tmp_path), "dev.yaml")
    assert meta["area"] == "Living Room"


def test_metadata_all_fields_none_for_empty_config(tmp_path):
    """A minimal config with no metadata still returns a well-formed dict."""
    _write_yaml(tmp_path, "dev.yaml", """\
esphome:
  name: dev

esp8266:
  board: d1_mini
""")
    meta = get_device_metadata(str(tmp_path), "dev.yaml")
    assert meta["device_name_raw"] == "dev"
    assert meta["friendly_name"] is None
    assert meta["area"] is None
    assert meta["comment"] is None
    assert meta["project_name"] is None
    assert meta["project_version"] is None
    assert meta["has_web_server"] is False


# ---------------------------------------------------------------------------
# build_name_to_target_map
# ---------------------------------------------------------------------------

def test_name_map_uses_filename_stem_fallback(tmp_path):
    """Filename stem is always in the map as a fallback."""
    _write_yaml(tmp_path, "bedroom.yaml", """\
esphome:
  name: bedroom

esp8266:
  board: d1_mini
""")
    name_map, _, _ = build_name_to_target_map(str(tmp_path), ["bedroom.yaml"])
    assert name_map["bedroom"] == "bedroom.yaml"


def test_name_map_maps_esphome_name_to_target(tmp_path):
    """esphome.name (may differ from filename) is mapped to the filename."""
    _write_yaml(tmp_path, "kitchen.yaml", """\
esphome:
  name: kitchen-under-cabinet

esp8266:
  board: d1_mini
""")
    name_map, _, _ = build_name_to_target_map(str(tmp_path), ["kitchen.yaml"])
    assert name_map["kitchen-under-cabinet"] == "kitchen.yaml"
    # And the underscore-normalized variant for mDNS (bug #159)
    assert name_map["kitchen_under_cabinet"] == "kitchen.yaml"


def test_name_map_extracts_encryption_key(tmp_path):
    """API encryption keys are extracted and keyed by device name."""
    _write_yaml(tmp_path, "dev.yaml", """\
esphome:
  name: dev

esp8266:
  board: d1_mini

api:
  encryption:
    key: "SGVsbG9Xb3JsZEhlbGxvV29ybGRIZWxsb1dvcmxkRWVFRQ=="
""")
    _, keys, _ = build_name_to_target_map(str(tmp_path), ["dev.yaml"])
    assert keys["dev"] == "SGVsbG9Xb3JsZEhlbGxvV29ybGRIZWxsb1dvcmxkRWVFRQ=="


def test_name_map_extracts_use_address(tmp_path):
    """wifi.use_address overrides are captured."""
    _write_yaml(tmp_path, "dev.yaml", """\
esphome:
  name: dev

esp8266:
  board: d1_mini

wifi:
  ssid: test
  password: test
  use_address: 192.168.1.42
""")
    _, _, overrides = build_name_to_target_map(str(tmp_path), ["dev.yaml"])
    assert overrides["dev"] == "192.168.1.42"


def test_name_map_empty_targets(tmp_path):
    name_map, keys, overrides = build_name_to_target_map(str(tmp_path), [])
    assert name_map == {}
    assert keys == {}
    assert overrides == {}
