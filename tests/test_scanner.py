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


def test_scan_missing_dir_logs_info_once(tmp_path, caplog):
    """Bug #86: a missing config dir is a config state (no ESPHome
    builder add-on, or user hasn't created the dir yet), not a crash
    condition. Log it once at INFO, then DEBUG on every subsequent
    scan so the log doesn't flood every poll tick.
    """
    import logging
    import scanner as scanner_module

    missing = tmp_path / "does_not_exist"
    scanner_module._missing_config_dirs_logged.discard(str(missing))

    try:
        with caplog.at_level(logging.DEBUG, logger="scanner"):
            scan_configs(str(missing))
            scan_configs(str(missing))
            scan_configs(str(missing))

        info_lines = [r for r in caplog.records if r.levelno == logging.INFO and "does not exist yet" in r.message]
        debug_lines = [r for r in caplog.records if r.levelno == logging.DEBUG and "still missing" in r.message]
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "does not exist or is not a directory" in r.message]

        # Exactly one INFO line total, regardless of how many scans.
        assert len(info_lines) == 1, f"Expected 1 INFO line, got {len(info_lines)}"
        # Subsequent scans log DEBUG.
        assert len(debug_lines) == 2, f"Expected 2 DEBUG lines, got {len(debug_lines)}"
        # No WARNING — the old flood-prone log level is gone.
        assert warnings == []
    finally:
        scanner_module._missing_config_dirs_logged.discard(str(missing))


def test_scan_resurfaced_dir_resets_suppression(tmp_path, caplog):
    """When the missing dir reappears, log an INFO that scans have
    resumed — and if it disappears again later, the 'missing' INFO
    should fire again (suppression state must reset).
    """
    import logging
    import scanner as scanner_module

    d = tmp_path / "esphome"
    scanner_module._missing_config_dirs_logged.discard(str(d))

    try:
        with caplog.at_level(logging.INFO, logger="scanner"):
            scan_configs(str(d))  # missing → INFO
            d.mkdir()
            scan_configs(str(d))  # present → INFO "resuming"
            import shutil
            shutil.rmtree(d)
            scan_configs(str(d))  # missing again → INFO

        messages = [r.message for r in caplog.records if r.name == "scanner"]
        missing_count = sum(1 for m in messages if "does not exist yet" in m)
        resumed_count = sum(1 for m in messages if "now available" in m)
        assert missing_count == 2
        assert resumed_count == 1
    finally:
        scanner_module._missing_config_dirs_logged.discard(str(d))


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
# create_bundle — BD (WORKITEMS-1.6.2). Per-target bundles via
# ESPHome's ConfigBundleCreator ship only referenced files + filtered
# secrets. Every test below is structured as a regression guard for a
# specific leak the pre-BD rglob path permitted.
# ---------------------------------------------------------------------------

def _bundle_names(raw: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        return tar.getnames()


def _bundle_file_bytes(raw: bytes, name: str) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        fp = tar.extractfile(name)
        assert fp is not None, f"{name} missing from bundle: {tar.getnames()}"
        return fp.read()


def test_bundle_is_tar_gz():
    raw = create_bundle(str(FIXTURES), "device1.yaml")
    assert isinstance(raw, bytes)
    assert len(raw) > 0
    # gzip magic bytes
    assert raw[:2] == b"\x1f\x8b"


def test_bundle_ships_the_target_yaml():
    names = _bundle_names(create_bundle(str(FIXTURES), "device1.yaml"))
    assert "device1.yaml" in names


def test_bundle_paths_are_relative():
    """Archive paths must not start with '/' — workers extract into a
    per-slot dir and an absolute path would escape it."""
    names = _bundle_names(create_bundle(str(FIXTURES), "device1.yaml"))
    for name in names:
        assert not name.startswith("/"), f"Absolute path in bundle: {name}"


def test_bundle_includes_manifest():
    """ConfigBundleCreator always emits a manifest.json at the tree root."""
    names = _bundle_names(create_bundle(str(FIXTURES), "device1.yaml"))
    assert "manifest.json" in names


# --- BD.3.3 — bundle for target X does NOT ship unrelated target Y ----------

def test_bundle_omits_unrelated_targets():
    """Pre-BD regression guard: bundle for device1 used to include
    every .yaml in the config directory. ConfigBundleCreator walks
    the validated config and only adds files the target references,
    so device2.yaml (and anything else not `!include`d by device1)
    must not be in the archive.
    """
    names = _bundle_names(create_bundle(str(FIXTURES), "device1.yaml"))
    assert "device2.yaml" not in names, (
        f"bundle for device1.yaml leaked device2.yaml — full list: {names}"
    )


def test_bundle_omits_unrelated_package_files(tmp_path):
    """Package files unreferenced by the target aren't shipped."""
    (tmp_path / "secrets.yaml").write_text(
        'wifi_ssid: "bundle-test-ssid"\nwifi_password: "bundle-test-password-long-enough"\nota_password: "bundle-test-ota-password"\n'
    )
    (tmp_path / "device-a.yaml").write_text(
        "esphome:\n  name: device-a\n"
        "esp8266:\n  board: d1_mini\n"
        "wifi:\n  ssid: !secret wifi_ssid\n  password: !secret wifi_password\n"
    )
    # A second target that uses an included package — that package
    # file must not ship with device-a's bundle.
    (tmp_path / "packages").mkdir()
    (tmp_path / "packages" / "shared.yaml").write_text(
        "logger:\n  level: DEBUG\n"
    )
    (tmp_path / "device-b.yaml").write_text(
        "esphome:\n  name: device-b\n"
        "esp8266:\n  board: d1_mini\n"
        "wifi:\n  ssid: !secret wifi_ssid\n  password: !secret wifi_password\n"
        "packages:\n  shared: !include packages/shared.yaml\n"
    )
    names = _bundle_names(create_bundle(str(tmp_path), "device-a.yaml"))
    assert "packages/shared.yaml" not in names
    assert "device-b.yaml" not in names


# --- BD.3.1 — `.git/` never ships -------------------------------------------

def test_bundle_excludes_git_dir(tmp_path):
    """Pre-BD regression guard: rglob shipped `.git/config` (containing
    remote URLs + any wired-up push credentials) and loose objects to
    every claiming worker. ConfigBundleCreator walks the config tree,
    not the filesystem, so `.git/*` never appears.
    """
    (tmp_path / "secrets.yaml").write_text(
        'wifi_ssid: "bundle-test-ssid"\nwifi_password: "bundle-test-password-long-enough"\nota_password: "bundle-test-ota-password"\n'
    )
    (tmp_path / "device.yaml").write_text(
        "esphome:\n  name: my-device\n"
        "esp8266:\n  board: d1_mini\n"
        "wifi:\n  ssid: !secret wifi_ssid\n  password: !secret wifi_password\n"
    )
    # Seed a believable-looking `.git/` tree with a push URL + a loose
    # object so a regression can't pass by checking for just the dir name.
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        "[remote \"origin\"]\n"
        "  url = https://ghp_SUPERSECRETPAT@github.com/user/repo.git\n"
    )
    (git_dir / "objects" / "ab").mkdir(parents=True)
    (git_dir / "objects" / "ab" / "cdef1234").write_bytes(b"\x78\x9c\x01\x00\x00")

    raw = create_bundle(str(tmp_path), "device.yaml")
    names = _bundle_names(raw)
    assert not any(".git" in n.split("/") for n in names), (
        f".git leaked in bundle: {[n for n in names if '.git' in n]}"
    )


# --- BD.3.2 — secrets.yaml is filtered to referenced keys only --------------

def test_bundle_filters_secrets_to_referenced_keys(tmp_path):
    """Pre-BD regression guard: rglob shipped the entire secrets.yaml
    (every device's WiFi PSK, API noise-PSK, OTA password) to every
    worker. ConfigBundleCreator loads secrets.yaml, intersects with the
    keys actually `!secret`-referenced by the bundled YAML tree, and
    only ships those keys.
    """
    (tmp_path / "secrets.yaml").write_text(
        'wifi_ssid: "my-ssid"\n'
        'wifi_password: "my-wifi-password"\n'
        'ota_password: "my-ota-password"\n'
        'api_encryption_key: "Zp82U4SqCqe55xkDDuPXzsoNhcmEws7/HbNXsv2qOGI="\n'
        'other_device_api_key: "OTHER-DEVICE-PSK-MUST-NOT-LEAK"\n'
        'unused_backdoor_password: "ALSO-MUST-NOT-LEAK"\n'
    )
    (tmp_path / "device.yaml").write_text(
        "esphome:\n  name: my-device\n"
        "esp8266:\n  board: d1_mini\n"
        "wifi:\n  ssid: !secret wifi_ssid\n  password: !secret wifi_password\n"
    )
    secrets_content = _bundle_file_bytes(
        create_bundle(str(tmp_path), "device.yaml"), "secrets.yaml",
    ).decode()

    # Keys this target references — must be present.
    assert "wifi_ssid" in secrets_content
    assert "wifi_password" in secrets_content

    # Keys this target does NOT reference — must be filtered out.
    assert "other_device_api_key" not in secrets_content
    assert "OTHER-DEVICE-PSK-MUST-NOT-LEAK" not in secrets_content
    assert "unused_backdoor_password" not in secrets_content
    assert "ALSO-MUST-NOT-LEAK" not in secrets_content


def test_bundle_raises_on_validation_error(tmp_path):
    """BD intentionally has no fallback — a target that fails ESPHome's
    full validator can't be dispatched until the YAML is fixed. Better
    than silently shipping the full config directory.
    """
    (tmp_path / "secrets.yaml").write_text('wifi_ssid: "bundle-test-ssid"\nwifi_password: "bundle-test-password-long-enough"\n')
    # Invalid: `esp8266.board` is missing.
    (tmp_path / "broken.yaml").write_text(
        "esphome:\n  name: broken\n"
        "esp8266: {}\n"
        "wifi:\n  ssid: !secret wifi_ssid\n  password: !secret wifi_password\n"
    )
    with pytest.raises(Exception):
        create_bundle(str(tmp_path), "broken.yaml")


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


def test_metadata_extracts_area_from_dict_form():
    """Bug #18: ESPHome's newer schema accepts ``area: {name: ..., id: ...}``.
    The extractor must surface the human-readable name rather than the
    repr of the dict (which renders as a JSON-looking blob in the UI).
    """
    config = {
        "esphome": {
            "name": "dev",
            "area": {"name": "Living Room", "id": "lr1"},
        },
    }
    meta = _empty_meta()
    _extract_metadata(config, meta)
    assert meta["area"] == "Living Room"


def test_metadata_extracts_area_from_dict_form_id_fallback():
    """Bug #18: dict area with no name still resolves via the id."""
    config = {
        "esphome": {
            "name": "dev",
            "area": {"id": "lr1"},
        },
    }
    meta = _empty_meta()
    _extract_metadata(config, meta)
    assert meta["area"] == "lr1"


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
# #84: wifi.domain is honored because we run ESPHome's full validator
# (which injects `wifi.use_address = CORE.name + config[CONF_DOMAIN]`).
# Before this fix, the substitution-only pipeline left use_address unset and
# our waterfall fell through to `{name}.local` regardless of `domain:`.
# ---------------------------------------------------------------------------

def test_wifi_domain_fixture_resolves_address():
    """Fixture: tests/fixtures/esphome_configs/wifi_domain.yaml

    Device declares ``wifi.domain: .example.internal`` but no ``use_address``.
    After full validation, ``wifi.use_address`` is injected as
    ``wifi-domain-device.example.internal`` — that must propagate to
    ``address_overrides`` so the worker OTAs to the right host, not
    ``wifi-domain-device.local``.
    """
    _, _, overrides, sources = build_name_to_target_map(
        str(FIXTURES), ["wifi_domain.yaml"],
    )
    assert overrides.get("wifi-domain-device") == "wifi-domain-device.example.internal"
    # Source is `wifi_use_address` (not `mdns_default` — the pre-fix bug)
    # because the validator set `use_address`, not `manual_ip.static_ip`.
    assert sources.get("wifi-domain-device") == "wifi_use_address"


def test_static_ip_fixture_keeps_static_ip_source_label():
    """After full validation, a static-IP config keeps its `_static_ip` source.

    The wifi validator promotes ``manual_ip.static_ip`` into ``use_address``
    (so ESPHome itself connects to the static IP). Our ``get_device_address``
    detects that match and keeps the legacy source label so the Devices-tab
    tooltip still reads "wifi static_ip" rather than "wifi.use_address".
    Regression guard alongside the #84 fix.
    """
    _, _, overrides, sources = build_name_to_target_map(
        str(FIXTURES), ["static_ip_device.yaml"],
    )
    assert overrides.get("static-ip-device") == "192.168.1.99"
    assert sources.get("static-ip-device") == "wifi_static_ip"


def test_get_device_address_validated_use_address_from_static_ip():
    """Direct unit-level check for the source-label heuristic.

    When both ``use_address`` and ``manual_ip.static_ip`` are present and
    equal, source is ``_static_ip`` (the pattern ``validate_config``
    produces when it promotes a static IP). When they differ, source is
    ``_use_address`` (explicit override or domain-injection).
    """
    # validator-produced shape for a static-IP config
    config = {
        "wifi": {
            "use_address": "10.0.0.5",
            "manual_ip": {"static_ip": "10.0.0.5"},
        }
    }
    assert get_device_address(config, "dev") == ("10.0.0.5", "wifi_static_ip")

    # validator-produced shape for a domain config — use_address is
    # `{name}{domain}`, manual_ip absent
    config = {
        "wifi": {"use_address": "dev.example.com"},
    }
    assert get_device_address(config, "dev") == ("dev.example.com", "wifi_use_address")

    # explicit override with unrelated static_ip (edge case but spec-level
    # correct: explicit use_address wins, source is use_address)
    config = {
        "wifi": {
            "use_address": "10.0.0.99",  # explicit, differs from static
            "manual_ip": {"static_ip": "10.0.0.5"},
        }
    }
    assert get_device_address(config, "dev") == ("10.0.0.99", "wifi_use_address")


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


def test_write_device_meta_routing_extra_round_trip(tmp_path):
    """TG.2: per-device additive routing rules (`routing_extra`) round-trip
    through the YAML metadata comment block as a list of rule dicts.
    The comment-block writer doesn't need to know the rule shape — it
    just YAML-dumps whatever ``meta`` it gets and the reader parses it
    back through ``yaml.safe_load``."""
    f = tmp_path / "device.yaml"
    f.write_text("esphome:\n  name: test\n")

    routing_extra = [
        {
            "name": "device-only-fast",
            "severity": "required",
            "device_match": [{"op": "all_of", "tags": ["kitchen"]}],
            "worker_match": [{"op": "all_of", "tags": ["fast"]}],
        },
    ]
    write_device_meta(str(tmp_path), "device.yaml", {"routing_extra": routing_extra})

    meta = read_device_meta(str(tmp_path), "device.yaml")
    assert meta == {"routing_extra": routing_extra}
    # Original YAML preserved.
    assert "esphome:" in f.read_text()
    assert "name: test" in f.read_text()


def test_write_device_meta_clearing_only_tags_strips_block(tmp_path):
    """Bug #9 regression: clearing the last tag (the only meta key) removes
    the whole comment block, not an empty `tags:` line.

    Models the dialog-save path: the UI sends `{tags: null}` to
    /ui/api/targets/{filename}/meta when the user clears every chip;
    update_target_meta turns null into a `meta.pop("tags")`; if `tags`
    was the only key in the YAML metadata block, the resulting empty
    dict triggers the whole-block strip path here.
    """
    f = tmp_path / "device.yaml"
    f.write_text(
        "# esphome-fleet:\n"
        "#   tags: office, sensors\n"
        "\n"
        "esphome:\n"
        "  name: test\n"
    )

    # Pop the only key (what update_target_meta does on tags=null):
    meta = read_device_meta(str(tmp_path), "device.yaml")
    meta.pop("tags", None)
    write_device_meta(str(tmp_path), "device.yaml", meta)

    content = f.read_text()
    assert "esphome-fleet" not in content
    assert "tags:" not in content
    assert "office" not in content
    # Original YAML survives.
    assert "esphome:" in content
    assert "name: test" in content


def test_write_device_meta_clearing_tags_with_other_keys_keeps_block(tmp_path):
    """Bug #9 partner: clearing tags but leaving other meta keys preserves
    the block (just minus the `tags:` line).
    """
    f = tmp_path / "device.yaml"
    f.write_text(
        "# esphome-fleet:\n"
        "#   pin_version: 2026.3.3\n"
        "#   tags: office, sensors\n"
        "\n"
        "esphome:\n"
        "  name: test\n"
    )

    meta = read_device_meta(str(tmp_path), "device.yaml")
    meta.pop("tags", None)
    write_device_meta(str(tmp_path), "device.yaml", meta)

    content = f.read_text()
    assert "# esphome-fleet:" in content
    assert "pin_version: 2026.3.3" in content
    assert "tags:" not in content
    assert "office" not in content


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
