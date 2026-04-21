"""Unit tests for the YAML scanner and bundle creator."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from scanner import (
    _extract_metadata,
    build_name_to_target_map,
    create_bundle,
    create_stub_yaml,
    duplicate_device,
    get_device_address,
    get_device_metadata,
    get_esphome_version,
    scan_configs,
)


def _empty_meta() -> dict:
    """Return a fresh empty metadata dict matching get_device_metadata's shape."""
    return {
        "friendly_name": None,
        "device_name": None,
        "device_name_raw": None,
        "comment": None,
        "area": None,
        "project_name": None,
        "project_version": None,
        "has_web_server": False,
    }

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
    import scanner

    original = meta.version
    original_selected = scanner._selected_esphome_version

    def mock_version(pkg):
        if pkg == "esphome":
            raise meta.PackageNotFoundError(pkg)
        return original(pkg)

    meta.version = mock_version
    scanner._selected_esphome_version = None
    # SE.7: without the failure flag set, the new logic assumes the
    # lazy-install is in flight and returns "installing". This test
    # exercises the "install won't help" terminal state, so simulate
    # the failure flag too.
    scanner._esphome_install_failed = True
    try:
        ver = get_esphome_version()
        assert ver == "unknown"
    finally:
        meta.version = original
        scanner._selected_esphome_version = original_selected
        scanner._esphome_install_failed = False


# ---------------------------------------------------------------------------
# get_device_metadata — extracting name/friendly_name/area/comment/project
# ---------------------------------------------------------------------------

def _write_yaml(config_dir: Path, name: str, content: str) -> None:
    (config_dir / name).write_text(content)


# ---------------------------------------------------------------------------
# _extract_metadata — call directly with hand-crafted dicts.
#
# These tests deliberately bypass _resolve_esphome_config (which is fragile
# across ESPHome versions: a tiny test fixture that the local 2026.3.1
# accepts can be rejected by 2026.3.3 in CI). Calling _extract_metadata with
# a pre-resolved dict tests OUR extraction logic, not ESPHome's schema.
#
# End-to-end coverage of the resolver path lives in the fixture-based tests
# below, which use the known-good device1.yaml fixture.
# ---------------------------------------------------------------------------

def test_metadata_extracts_name_and_friendly_name():
    config = {
        "esphome": {
            "name": "living-room-sensor",
            "friendly_name": "Living Room Sensor",
        },
    }
    meta = _empty_meta()
    _extract_metadata(config, meta)
    assert meta["device_name_raw"] == "living-room-sensor"
    assert meta["device_name"] == "Living Room Sensor"
    assert meta["friendly_name"] == "Living Room Sensor"


def test_metadata_extracts_area_and_comment():
    config = {
        "esphome": {
            "name": "dev",
            "area": "Kitchen",
            "comment": "Over the sink",
        },
    }
    meta = _empty_meta()
    _extract_metadata(config, meta)
    assert meta["area"] == "Kitchen"
    assert meta["comment"] == "Over the sink"


def test_metadata_extracts_project():
    config = {
        "esphome": {
            "name": "dev",
            "project": {"name": "example.device", "version": "1.2.3"},
        },
    }
    meta = _empty_meta()
    _extract_metadata(config, meta)
    assert meta["project_name"] == "example.device"
    assert meta["project_version"] == "1.2.3"


def test_metadata_detects_web_server():
    config = {
        "esphome": {"name": "dev"},
        "web_server": {"port": 80},
    }
    meta = _empty_meta()
    _extract_metadata(config, meta)
    assert meta["has_web_server"] is True


def test_metadata_missing_web_server():
    config = {"esphome": {"name": "dev"}}
    meta = _empty_meta()
    _extract_metadata(config, meta)
    assert meta["has_web_server"] is False


def test_metadata_detects_web_server_with_no_value():
    """#74: ESPHome allows `web_server:` with no value (enables with defaults).

    YAML parses this as {"web_server": None}. The detection must check
    for key PRESENCE, not key VALUE.
    """
    config = {"esphome": {"name": "dev"}, "web_server": None}
    meta = _empty_meta()
    _extract_metadata(config, meta)
    assert meta["has_web_server"] is True


def test_metadata_all_fields_none_for_minimal_config():
    """A minimal config with only esphome.name leaves the optional fields untouched."""
    config = {"esphome": {"name": "dev"}}
    meta = _empty_meta()
    _extract_metadata(config, meta)
    assert meta["device_name_raw"] == "dev"
    assert meta["friendly_name"] is None
    assert meta["area"] is None
    assert meta["comment"] is None
    assert meta["project_name"] is None
    assert meta["project_version"] is None
    assert meta["has_web_server"] is False


def test_metadata_no_esphome_block():
    """A config that's missing the esphome block leaves metadata as defaults."""
    meta = _empty_meta()
    _extract_metadata({}, meta)
    assert meta["device_name_raw"] is None
    assert meta["friendly_name"] is None


# ---------------------------------------------------------------------------
# build_name_to_target_map
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# build_name_to_target_map — exercised against the known-good FIXTURES dir
# instead of inline tmp_path configs (which break across ESPHome versions).
# device1.yaml has esphome.name=device1 + api.encryption.key, so it covers
# the stem fallback, the device-name mapping, and encryption key extraction
# in one shot.
# ---------------------------------------------------------------------------

def test_name_map_uses_filename_stem_fallback():
    """Filename stem is always in the map as a fallback."""
    name_map, _, _, _ = build_name_to_target_map(str(FIXTURES), ["device1.yaml"])
    assert name_map["device1"] == "device1.yaml"


def test_name_map_extracts_encryption_key():
    """API encryption keys are extracted and keyed by device name."""
    _, keys, _, _ = build_name_to_target_map(str(FIXTURES), ["device1.yaml"])
    # The fixture's secrets.yaml maps api_encryption_key to a real base64 key
    assert "device1" in keys
    assert keys["device1"]  # non-empty


def test_name_map_resolves_despite_unresolved_substitution():
    """Bug #22: YAMLs with an undefined substitution (e.g. ${pretty_name}
    referenced but not declared) must still produce scanner metadata —
    the resolver has to pass ``ignore_missing=True`` to ESPHome's
    substitution pass when available, otherwise any missing reference
    raises and the entire config silently returns empty.
    """
    name_map, keys, overrides, _ = build_name_to_target_map(
        str(FIXTURES), ["unresolved_subs_device.yaml"],
    )
    # The device_name substitution resolves, so the device name itself
    # must make it into the name_map.
    assert "un-sub-device" in name_map, (
        f"name_map is missing resolved device name; got {name_map}"
    )
    assert name_map["un-sub-device"] == "unresolved_subs_device.yaml"
    # API encryption key must be extracted (keyed by resolved name).
    assert "un-sub-device" in keys
    # Address override is always registered — at minimum the mdns fallback.
    assert "un-sub-device" in overrides


def test_name_map_encryption_keys_include_underscore_variant():
    """Bug #11 (1.6.1): aioesphomeapi / mDNS often normalise hyphenated
    device names to underscores (``un-sub-device`` → ``un_sub_device``),
    so the encryption-key map must carry BOTH forms. Pre-1.6.1 only the
    name_map did this mirroring; the key map didn't, and live logs for
    an encrypted ``my-device`` silently fell through to an unencrypted
    handshake that the device rejects."""
    _, keys, _, _ = build_name_to_target_map(
        str(FIXTURES), ["unresolved_subs_device.yaml"],
    )
    assert "un-sub-device" in keys
    assert "un_sub_device" in keys
    # Both aliases must point at the same key (not accidentally distinct).
    assert keys["un-sub-device"] == keys["un_sub_device"]


def test_get_device_metadata_uses_friendly_name_for_unresolved_subs():
    """Bug #22 follow-up: get_device_metadata must still extract
    device_name for a YAML that contains an unresolved substitution.
    (friendly_name may be None when it references an undefined sub; the
    UI falls back to device_name in that case — but device_name must NOT
    be None, which is what the regression had before.)
    """
    from scanner import get_device_metadata

    meta = get_device_metadata(str(FIXTURES), "unresolved_subs_device.yaml")
    assert meta["device_name"] is not None, (
        "device_name should resolve from ${device_name} even when friendly_name doesn't"
    )
    # device_name is title-cased ("un-sub-device" → "Un Sub Device")
    assert "Un Sub Device" in meta["device_name"]


def test_name_map_empty_targets(tmp_path):
    name_map, keys, overrides, sources = build_name_to_target_map(str(tmp_path), [])
    assert name_map == {}
    assert keys == {}
    assert overrides == {}
    assert sources == {}


# ---------------------------------------------------------------------------
# get_device_address — bug #179
# Mirrors ESPHome CORE.address: wifi → ethernet → openthread, each honoring
# use_address → manual_ip.static_ip → {name}.local fallback.
# ---------------------------------------------------------------------------

def test_get_device_address_wifi_use_address():
    config = {"wifi": {"use_address": "192.168.1.42"}}
    assert get_device_address(config, "dev") == ("192.168.1.42", "wifi_use_address")


def test_get_device_address_wifi_static_ip():
    config = {"wifi": {"manual_ip": {"static_ip": "10.0.0.5"}}}
    assert get_device_address(config, "dev") == ("10.0.0.5", "wifi_static_ip")


def test_get_device_address_wifi_default_to_mdns():
    config = {"wifi": {"ssid": "test"}}
    assert get_device_address(config, "dev") == ("dev.local", "mdns_default")


def test_get_device_address_ethernet_use_address():
    config = {"ethernet": {"use_address": "10.0.0.10"}}
    assert get_device_address(config, "dev") == ("10.0.0.10", "ethernet_use_address")


def test_get_device_address_ethernet_static_ip():
    config = {"ethernet": {"manual_ip": {"static_ip": "10.0.0.11"}}}
    assert get_device_address(config, "dev") == ("10.0.0.11", "ethernet_static_ip")


def test_get_device_address_ethernet_default_to_mdns():
    config = {"ethernet": {"type": "LAN8720"}}
    assert get_device_address(config, "dev") == ("dev.local", "mdns_default")


def test_get_device_address_openthread_use_address():
    """Thread-only devices: openthread.use_address overrides everything."""
    config = {"openthread": {"use_address": "fd00::1"}}
    assert get_device_address(config, "thread-dev") == ("fd00::1", "openthread_use_address")


def test_get_device_address_openthread_default_to_mdns():
    """Thread-only device with no explicit address falls back to mDNS hostname."""
    config = {"openthread": {"network_key": "deadbeef"}}
    assert get_device_address(config, "thread-dev") == ("thread-dev.local", "mdns_default")


def test_get_device_address_nothing_configured():
    """Empty config (no network block at all) falls back to {name}.local."""
    config = {"esphome": {"name": "minimal"}}
    assert get_device_address(config, "minimal") == ("minimal.local", "mdns_default")


# Bonus: wifi takes precedence over ethernet/openthread when multiple are present
def test_get_device_address_wifi_wins_over_ethernet():
    config = {
        "wifi": {"use_address": "192.168.1.42"},
        "ethernet": {"use_address": "10.0.0.10"},
    }
    assert get_device_address(config, "dev") == ("192.168.1.42", "wifi_use_address")


# ---------------------------------------------------------------------------
# build_name_to_target_map populates address_overrides for ALL targets (#179)
# ---------------------------------------------------------------------------

# The static-IP, DHCP, and Thread-only cases are exercised by the
# FIXTURE-based tests below, which use real known-good ESPHome configs in
# tests/fixtures/esphome_configs/. Inline tmp_path tests for these would be
# fragile across ESPHome versions because the resolver's schema changes
# from version to version.


# ---------------------------------------------------------------------------
# Fixture-based integration tests for #186 — verify the real fixture YAMLs
# (which include !secret + manual_ip / openthread blocks) actually parse
# through ESPHome's full resolution pipeline and yield the right metadata.
# These exercise the same code path the production code uses, not isolated
# helper functions.
# ---------------------------------------------------------------------------

def test_static_ip_fixture_resolves_address():
    """Fixture: tests/fixtures/esphome_configs/static_ip_device.yaml"""
    _, _, overrides, sources = build_name_to_target_map(
        str(FIXTURES), ["static_ip_device.yaml"],
    )
    assert overrides.get("static-ip-device") == "192.168.1.99"
    assert sources.get("static-ip-device") == "wifi_static_ip"


def test_thread_only_fixture_resolves_to_mdns():
    """Fixture: tests/fixtures/esphome_configs/thread_only_device.yaml

    A Thread-only device with no wifi/ethernet block should still get an
    address override (falling back to {name}.local). Without this, the YAML
    row never exists and any later mDNS discovery duplicates it (#179).
    """
    _, _, overrides, sources = build_name_to_target_map(
        str(FIXTURES), ["thread_only_device.yaml"],
    )
    assert "thread-only-device" in overrides
    assert overrides["thread-only-device"] == "thread-only-device.local"
    assert sources["thread-only-device"] == "mdns_default"


def test_static_ip_fixture_metadata():
    """Static-IP device's friendly_name still resolves correctly."""
    meta = get_device_metadata(str(FIXTURES), "static_ip_device.yaml")
    assert meta["friendly_name"] == "Static IP Device"
    assert meta["device_name_raw"] == "static-ip-device"


# ---------------------------------------------------------------------------
# Per-device metadata comment block (read_device_meta / write_device_meta)
# ---------------------------------------------------------------------------

from scanner import read_device_meta, write_device_meta


def test_read_device_meta_empty_file(tmp_path):
    """File with no metadata block returns empty dict."""
    f = tmp_path / "device.yaml"
    f.write_text("esphome:\n  name: test\n")
    assert read_device_meta(str(tmp_path), "device.yaml") == {}


def test_read_device_meta_basic(tmp_path):
    """Reads a well-formed block with pin_version and schedule (new marker)."""
    f = tmp_path / "device.yaml"
    f.write_text(
        "# esphome-fleet:\n"
        "#   pin_version: 2026.3.3\n"
        "#   schedule: 0 2 * * 0\n"
        "#   schedule_enabled: true\n"
        "\n"
        "esphome:\n"
        "  name: test\n"
    )
    meta = read_device_meta(str(tmp_path), "device.yaml")
    assert meta["pin_version"] == "2026.3.3"
    assert meta["schedule"] == "0 2 * * 0"
    assert meta["schedule_enabled"] is True


def test_read_device_meta_legacy_marker(tmp_path):
    """Legacy `# distributed-esphome:` marker is still readable (backward compat)."""
    f = tmp_path / "device.yaml"
    f.write_text(
        "# distributed-esphome:\n"
        "#   pin_version: 2026.3.3\n"
        "\n"
        "esphome:\n"
        "  name: test\n"
    )
    meta = read_device_meta(str(tmp_path), "device.yaml")
    assert meta["pin_version"] == "2026.3.3"


def test_read_device_meta_with_tags(tmp_path):
    """Tags field parses correctly."""
    f = tmp_path / "device.yaml"
    f.write_text(
        "# distributed-esphome:\n"
        "#   tags: office, sensors\n"
        "\n"
        "esphome:\n"
        "  name: test\n"
    )
    meta = read_device_meta(str(tmp_path), "device.yaml")
    assert meta["tags"] == "office, sensors"


def test_read_device_meta_ignores_deep_comments(tmp_path):
    """Block must be at the TOP of the file, before any YAML content."""
    f = tmp_path / "device.yaml"
    f.write_text(
        "esphome:\n"
        "  name: test\n"
        "\n"
        "# distributed-esphome:\n"
        "#   pin_version: should-not-match\n"
    )
    assert read_device_meta(str(tmp_path), "device.yaml") == {}


def test_read_device_meta_with_leading_blank_lines(tmp_path):
    """Blank lines before the marker are OK."""
    f = tmp_path / "device.yaml"
    f.write_text(
        "\n"
        "\n"
        "# distributed-esphome:\n"
        "#   pin_version: 2026.3.3\n"
        "\n"
        "esphome:\n"
        "  name: test\n"
    )
    meta = read_device_meta(str(tmp_path), "device.yaml")
    assert meta["pin_version"] == "2026.3.3"


def test_write_device_meta_adds_block(tmp_path):
    """Adds a block to a file that has none."""
    f = tmp_path / "device.yaml"
    f.write_text("esphome:\n  name: test\n")

    write_device_meta(str(tmp_path), "device.yaml", {"pin_version": "2026.3.3"})

    content = f.read_text()
    assert "# esphome-fleet:" in content
    # Writer should emit the explanatory header so users know not to remove it.
    assert "ESPHome Fleet" in content
    assert "#   pin_version: 2026.3.3" in content
    # Original content is preserved
    assert "esphome:" in content
    assert "name: test" in content


def test_write_device_meta_replaces_block(tmp_path):
    """Replaces an existing block with new values."""
    f = tmp_path / "device.yaml"
    f.write_text(
        "# esphome-fleet:\n"
        "#   pin_version: old\n"
        "\n"
        "esphome:\n"
        "  name: test\n"
    )

    write_device_meta(str(tmp_path), "device.yaml", {"pin_version": "new", "schedule": "0 2 * * *"})

    content = f.read_text()
    assert "old" not in content
    assert "# esphome-fleet:" in content
    assert "#   pin_version: new" in content
    assert "#   schedule: 0 2 * * *" in content


def test_write_device_meta_migrates_legacy_marker(tmp_path):
    """Writer migrates a legacy `# distributed-esphome:` block to the new marker."""
    f = tmp_path / "device.yaml"
    f.write_text(
        "# distributed-esphome:\n"
        "#   pin_version: old\n"
        "\n"
        "esphome:\n"
        "  name: test\n"
    )

    write_device_meta(str(tmp_path), "device.yaml", {"pin_version": "new"})

    content = f.read_text()
    # Old marker gone, new marker present.
    assert "distributed-esphome" not in content
    assert "# esphome-fleet:" in content
    assert "#   pin_version: new" in content


def test_write_device_meta_removes_block_when_empty(tmp_path):
    """Empty dict removes the block entirely (including legacy marker + header)."""
    f = tmp_path / "device.yaml"
    f.write_text(
        "# distributed-esphome:\n"
        "#   pin_version: 2026.3.3\n"
        "\n"
        "esphome:\n"
        "  name: test\n"
    )

    write_device_meta(str(tmp_path), "device.yaml", {})

    content = f.read_text()
    assert "distributed-esphome" not in content
    assert "esphome-fleet" not in content
    assert "esphome:" in content


def test_write_device_meta_preserves_other_comments(tmp_path):
    """Other comment lines in the file survive the write."""
    f = tmp_path / "device.yaml"
    f.write_text(
        "# My device config\n"
        "esphome:\n"
        "  name: test\n"
        "# End of file\n"
    )

    write_device_meta(str(tmp_path), "device.yaml", {"schedule": "0 2 * * *"})

    content = f.read_text()
    assert "# My device config" in content
    assert "# End of file" in content
    assert "# esphome-fleet:" in content


def test_write_device_meta_invalidates_cache(tmp_path):
    """_config_cache entry is removed after write."""
    from scanner import _config_cache

    f = tmp_path / "device.yaml"
    f.write_text("esphome:\n  name: test\n")
    _config_cache["device.yaml"] = (0.0, {"fake": True})

    write_device_meta(str(tmp_path), "device.yaml", {"pin_version": "1.0"})
    assert "device.yaml" not in _config_cache


def test_roundtrip_read_write(tmp_path):
    """write then read returns the same dict."""
    f = tmp_path / "device.yaml"
    f.write_text("esphome:\n  name: test\n")

    meta = {
        "pin_version": "2026.3.3",
        "schedule": "0 2 * * 0",
        "schedule_enabled": True,
        "tags": "office, sensors",
    }
    write_device_meta(str(tmp_path), "device.yaml", meta)
    result = read_device_meta(str(tmp_path), "device.yaml")
    assert result == meta



# ---------------------------------------------------------------------------
# create_stub_yaml (CD.1)
# ---------------------------------------------------------------------------


def test_create_stub_yaml_has_name():
    """Stub YAML should contain esphome.name set to the provided name."""
    import yaml
    result = create_stub_yaml("kitchen-sensor")
    data = yaml.safe_load(result)
    assert data == {"esphome": {"name": "kitchen-sensor"}}


def test_create_stub_yaml_round_trips():
    """Stub YAML must parse via yaml.safe_load without errors (PY-1)."""
    import yaml
    result = create_stub_yaml("test-device")
    # Should not raise
    parsed = yaml.safe_load(result)
    assert isinstance(parsed, dict)
    assert parsed["esphome"]["name"] == "test-device"


def test_create_stub_yaml_contains_guidance_comment():
    """Stub should include a hint comment so the user knows where to add content."""
    result = create_stub_yaml("foo")
    assert "Add board" in result


# ---------------------------------------------------------------------------
# duplicate_device (CD.2)
# ---------------------------------------------------------------------------


def test_duplicate_device_rewrites_name(tmp_path):
    """Duplicated YAML has esphome.name set to new_name."""
    import yaml
    src = tmp_path / "source.yaml"
    src.write_text("esphome:\n  name: original\n  comment: Hello\n")

    result = duplicate_device(str(tmp_path), "source.yaml", "duplicated")
    data = yaml.safe_load(result)
    assert data["esphome"]["name"] == "duplicated"
    # Other fields preserved
    assert data["esphome"]["comment"] == "Hello"


def test_duplicate_device_preserves_other_fields(tmp_path):
    """Duplicated YAML keeps substitutions, packages, sensors, etc."""
    import yaml
    src = tmp_path / "src.yaml"
    src.write_text(
        "esphome:\n"
        "  name: my-device\n"
        "wifi:\n"
        "  ssid: home\n"
        "sensor:\n"
        "  - platform: dht\n"
        "    pin: GPIO4\n"
    )

    result = duplicate_device(str(tmp_path), "src.yaml", "my-device-2")
    data = yaml.safe_load(result)
    assert data["esphome"]["name"] == "my-device-2"
    assert data["wifi"]["ssid"] == "home"
    assert data["sensor"][0]["platform"] == "dht"


def test_duplicate_device_rewrites_substitution(tmp_path):
    """When esphome.name is ${substitutions.name}, rewrite the substitution."""
    import yaml
    src = tmp_path / "src.yaml"
    src.write_text(
        "substitutions:\n"
        "  name: old-name\n"
        "  display_name: Old\n"
        "esphome:\n"
        "  name: ${name}\n"
    )

    result = duplicate_device(str(tmp_path), "src.yaml", "new-name")
    data = yaml.safe_load(result)
    # substitution is rewritten, esphome.name keeps the indirection
    assert data["substitutions"]["name"] == "new-name"
    assert data["esphome"]["name"] == "${name}"
    # Other substitutions untouched
    assert data["substitutions"]["display_name"] == "Old"


def test_duplicate_device_missing_source(tmp_path):
    """Missing source file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        duplicate_device(str(tmp_path), "nonexistent.yaml", "new")


def test_duplicate_device_invalid_yaml(tmp_path):
    """Non-parseable source raises ValueError."""
    src = tmp_path / "bad.yaml"
    src.write_text("{{{invalid yaml")
    with pytest.raises(ValueError):
        duplicate_device(str(tmp_path), "bad.yaml", "new")


def test_duplicate_device_no_esphome_block(tmp_path):
    """Source YAML without esphome block gets one added with the new name."""
    import yaml
    src = tmp_path / "src.yaml"
    src.write_text("wifi:\n  ssid: home\n")

    result = duplicate_device(str(tmp_path), "src.yaml", "new-device")
    data = yaml.safe_load(result)
    assert data["esphome"]["name"] == "new-device"
    assert data["wifi"]["ssid"] == "home"


def test_duplicate_device_preserves_include_tags(tmp_path):
    """#43: !include / !secret / custom ESPHome tags survive the round-trip."""
    src = tmp_path / "src.yaml"
    src.write_text(
        "esphome:\n  name: device\n"
        "packages:\n"
        "  common: !include .common.yaml\n"
        "  athom: !include .athom-plug.yaml\n"
        "wifi:\n"
        "  ap:\n"
        "    password: !secret ap_password\n"
    )

    result = duplicate_device(str(tmp_path), "src.yaml", "new-device")
    # name was rewritten
    assert "name: new-device" in result
    # All three custom tags preserved (we can't use yaml.safe_load to verify
    # because that's exactly what used to choke — string-match the output).
    assert "!include '.common.yaml'" in result or "!include .common.yaml" in result
    assert "!include '.athom-plug.yaml'" in result or "!include .athom-plug.yaml" in result
    assert "!secret 'ap_password'" in result or "!secret ap_password" in result


def test_duplicate_device_strips_use_address(tmp_path):
    """#54: wifi.use_address is stripped so the duplicate doesn't inherit
    the source's IP and show "online" just because the server can still
    reach the original device at that address. Other wifi fields
    (ssid, password) are preserved.
    """
    import yaml
    src = tmp_path / "src.yaml"
    src.write_text(
        "esphome:\n  name: device\n"
        "wifi:\n  use_address: 192.168.1.100\n  ssid: home\n"
    )
    result = duplicate_device(str(tmp_path), "src.yaml", "device-copy")
    data = yaml.safe_load(result)
    assert "use_address" not in data["wifi"]
    assert data["wifi"]["ssid"] == "home"


def test_duplicate_device_strips_manual_static_ip(tmp_path):
    """#54: wifi.manual_ip.static_ip is stripped for the same reason."""
    import yaml
    src = tmp_path / "src.yaml"
    src.write_text(
        "esphome:\n  name: device\n"
        "wifi:\n"
        "  ssid: home\n"
        "  manual_ip:\n"
        "    static_ip: 192.168.1.50\n"
        "    gateway: 192.168.1.1\n"
    )
    result = duplicate_device(str(tmp_path), "src.yaml", "device-copy")
    data = yaml.safe_load(result)
    # static_ip removed; gateway preserved (not an identity pin).
    manual_ip = data["wifi"].get("manual_ip") or {}
    assert "static_ip" not in manual_ip
    assert manual_ip.get("gateway") == "192.168.1.1"


def test_duplicate_device_strips_ethernet_and_openthread_addresses(tmp_path):
    """#54: same treatment for ethernet.use_address and openthread."""
    import yaml
    src = tmp_path / "src.yaml"
    src.write_text(
        "esphome:\n  name: device\n"
        "ethernet:\n  use_address: 10.0.0.10\n  type: LAN8720\n"
        "openthread:\n  use_address: fd00::1\n"
    )
    result = duplicate_device(str(tmp_path), "src.yaml", "device-copy")
    data = yaml.safe_load(result)
    assert "use_address" not in data["ethernet"]
    assert data["ethernet"]["type"] == "LAN8720"
    assert "use_address" not in data["openthread"]


def test_duplicate_device_preserves_includes_with_substitution_rewrite(tmp_path):
    """Combined: substitution rewrite + !include preservation."""
    src = tmp_path / "src.yaml"
    src.write_text(
        "substitutions:\n  name: old\n"
        "packages:\n"
        "  common: !include .common.yaml\n"
        "esphome:\n  name: ${name}\n"
    )

    result = duplicate_device(str(tmp_path), "src.yaml", "fresh")
    # substitution rewritten
    assert "name: fresh" in result
    # esphome.name still references the substitution
    assert "name: ${name}" in result
    # include preserved
    assert "!include" in result


def test_duplicate_device_rewrites_substitutions_name_with_implicit_esphome_name(tmp_path):
    """#43 follow-up: source has substitutions.name AND top-level esphome block
    without a name field (the actual device name comes from an included
    package that uses ${name}). Duplicate should rewrite substitutions.name
    so the rename propagates into the includes, and leave the top-level
    esphome block alone (no redundant literal name)."""
    src = tmp_path / "src.yaml"
    src.write_text(
        "substitutions:\n"
        "  name: athom-plug-1\n"
        "  display_name: Office Speakers\n"
        "esphome:\n"
        "  area: Office\n"
        "packages:\n"
        "  common: !include .common.yaml\n"
        "  athom: !include .athom-plug.yaml\n"
    )

    result = duplicate_device(str(tmp_path), "src.yaml", "athom-plug-1-copy")
    # substitutions.name rewritten — this is the key fix
    assert "name: athom-plug-1-copy" in result
    assert "athom-plug-1" not in result.replace("athom-plug-1-copy", "")
    # No literal esphome.name injected (the includes will pull it from ${name})
    # Rough check: esphome block doesn't gain an explicit name line.
    # The resulting esphome block should still be just "area: Office".
    import yaml as _yaml
    class _Loader(_yaml.SafeLoader):
        pass
    _Loader.add_multi_constructor("!", lambda loader, suf, node: None)
    parsed = _yaml.load(result, Loader=_Loader)
    assert "name" not in parsed["esphome"]
    # Other substitutions preserved
    assert parsed["substitutions"]["display_name"] == "Office Speakers"


def test_resolve_failure_logs_warning(tmp_path, caplog):
    """DL.5: malformed YAML resolve failure promotes to WARNING with
    the target filename + exception type (issue #60 diagnostic).
    """
    import logging
    from scanner import _resolve_esphome_config

    bad = tmp_path / "broken.yaml"
    # !secret reference a secret that doesn't exist — ESPHome's resolve
    # pipeline raises. The test only cares that our catch path logs WARNING.
    bad.write_text(
        "esphome:\n"
        "  name: broken\n"
        "wifi:\n"
        "  password: !secret nonexistent_secret\n"
    )
    with caplog.at_level(logging.WARNING, logger="scanner"):
        result = _resolve_esphome_config(str(tmp_path), "broken.yaml")
    assert result is None
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("broken.yaml" in r.getMessage() for r in warnings), (
        f"expected WARNING mentioning broken.yaml, got: {[r.getMessage() for r in warnings]}"
    )
