"""HI.12 — DeviceInfo builder tests (HI.11)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from esphome_fleet.const import DOMAIN
from esphome_fleet.device import hub_device_info, target_device_info, worker_device_info


def test_hub_device_info_identifies_by_entry_id() -> None:
    info = hub_device_info("entry-xyz", "http://homeassistant.local:8765")
    assert info["identifiers"] == {(DOMAIN, "hub:entry-xyz")}
    assert info["name"] == "ESPHome Fleet"
    assert info["configuration_url"] == "http://homeassistant.local:8765"


def test_target_device_info_prefers_friendly_name() -> None:
    target = {
        "target": "living-room.yaml",
        "friendly_name": "Living Room Sensor",
        "device_name": "Living Room",
    }
    info = target_device_info(target, "entry-xyz")
    assert info["identifiers"] == {(DOMAIN, "target:living-room.yaml")}
    assert info["name"] == "Living Room Sensor"
    assert info["via_device"] == (DOMAIN, "hub:entry-xyz")


def test_target_device_info_falls_back_to_device_name() -> None:
    target = {"target": "bedroom.yaml", "device_name": "Bedroom Sensor"}
    info = target_device_info(target, "entry-xyz")
    assert info["name"] == "Bedroom Sensor"


def test_target_device_info_falls_back_to_filename_stem() -> None:
    target = {"target": "kitchen-light.yaml"}
    info = target_device_info(target, "entry-xyz")
    assert info["name"] == "kitchen-light"


def test_target_device_info_model_combines_platform_and_board() -> None:
    target = {"target": "foo.yaml", "platform": "esp32", "board": "esp32dev"}
    info = target_device_info(target, "entry-xyz")
    assert info["model"] == "esp32 · esp32dev"


def test_target_device_info_model_falls_back_when_metadata_missing() -> None:
    info = target_device_info({"target": "foo.yaml"}, "entry-xyz")
    assert info["model"] == "ESPHome device"


def test_target_device_info_suggested_area_copied_from_yaml() -> None:
    info = target_device_info(
        {"target": "foo.yaml", "area": "Living Room"}, "entry-xyz"
    )
    assert info["suggested_area"] == "Living Room"


def test_target_device_info_attaches_mac_connection() -> None:
    """#27 — MAC triggers a CONNECTION_NETWORK_MAC so HA merges with ESPHome."""
    info = target_device_info(
        {"target": "foo.yaml", "mac_address": "AA:BB:CC:DD:EE:FF"},
        "entry-xyz",
    )
    assert info["connections"] == {(CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")}


def test_target_device_info_normalizes_colonless_mac() -> None:
    """ESPHome native-API form (no colons, upper-case) is normalized."""
    info = target_device_info(
        {"target": "foo.yaml", "mac_address": "AABBCCDDEEFF"},
        "entry-xyz",
    )
    assert info["connections"] == {(CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")}


def test_target_device_info_skips_connection_when_mac_missing() -> None:
    info = target_device_info({"target": "foo.yaml"}, "entry-xyz")
    assert "connections" not in info


def test_target_device_info_skips_connection_when_mac_invalid() -> None:
    info = target_device_info(
        {"target": "foo.yaml", "mac_address": "not-a-mac"},
        "entry-xyz",
    )
    assert "connections" not in info


def test_worker_device_info_names_worker_with_suffix() -> None:
    worker = {
        "client_id": "abc123",
        "hostname": "build-box",
        "client_version": "1.4.1-dev.5",
        "system_info": {"cpu_model": "Intel i7", "os_version": "Debian 12"},
    }
    info = worker_device_info(worker, "entry-xyz")
    assert info["identifiers"] == {(DOMAIN, "worker:abc123")}
    assert info["name"] == "build-box (worker)"
    assert info["sw_version"] == "1.4.1-dev.5"
    assert info["model"] == "Intel i7 · Debian 12"


def test_worker_device_info_handles_missing_system_info() -> None:
    info = worker_device_info({"client_id": "xyz", "hostname": "w"}, "entry-xyz")
    assert info["model"] == "Build worker"


# --- #39: stale-device cleanup tests ---


def _make_device(identifiers, config_entries):
    """Minimal device stub for _register_devices tests."""
    return SimpleNamespace(
        identifiers=set(tuple(i) for i in identifiers),
        config_entries=set(config_entries),
        id=f"dev-{hash(tuple(tuple(i) for i in identifiers)) % 10000}",
        name="test-device",
    )


def test_register_devices_removes_stale_fleet_only_device() -> None:
    """#39 — a Fleet-only device whose target vanished gets removed."""
    from esphome_fleet import _register_devices

    stale_device = _make_device(
        identifiers=[(DOMAIN, "target:deleted.yaml")],
        config_entries=["entry-1"],
    )

    registry = MagicMock()
    registry.async_get_or_create = MagicMock()
    registry.async_remove_device = MagicMock()
    registry.async_update_device = MagicMock()

    with patch("esphome_fleet.dr.async_get", return_value=registry):
        with patch(
            "esphome_fleet.dr.async_entries_for_config_entry",
            return_value=[stale_device],
        ):
            hass = SimpleNamespace()
            entry = SimpleNamespace(entry_id="entry-1")
            coordinator = SimpleNamespace(
                data={"targets": [], "workers": []},
                base_url="http://test:8765",
            )
            _register_devices(hass, entry, coordinator)

    registry.async_remove_device.assert_called_once_with(stale_device.id)
    registry.async_update_device.assert_not_called()


def test_register_devices_detaches_stale_merged_device() -> None:
    """#39 — a merged device keeps its row; we only detach our entry."""
    from esphome_fleet import _register_devices

    merged_device = _make_device(
        identifiers=[(DOMAIN, "target:removed.yaml")],
        config_entries=["entry-1", "esphome-entry-2"],
    )

    registry = MagicMock()
    registry.async_get_or_create = MagicMock()
    registry.async_remove_device = MagicMock()
    registry.async_update_device = MagicMock()

    with patch("esphome_fleet.dr.async_get", return_value=registry):
        with patch(
            "esphome_fleet.dr.async_entries_for_config_entry",
            return_value=[merged_device],
        ):
            hass = SimpleNamespace()
            entry = SimpleNamespace(entry_id="entry-1")
            coordinator = SimpleNamespace(
                data={"targets": [], "workers": []},
                base_url="http://test:8765",
            )
            _register_devices(hass, entry, coordinator)

    registry.async_remove_device.assert_not_called()
    registry.async_update_device.assert_called_once_with(
        merged_device.id, remove_config_entry_id="entry-1"
    )


def test_register_devices_keeps_live_devices() -> None:
    """#39 — devices whose targets still exist are not touched."""
    from esphome_fleet import _register_devices

    live_device = _make_device(
        identifiers=[(DOMAIN, "target:still-here.yaml")],
        config_entries=["entry-1"],
    )

    registry = MagicMock()
    registry.async_get_or_create = MagicMock()
    registry.async_remove_device = MagicMock()
    registry.async_update_device = MagicMock()

    with patch("esphome_fleet.dr.async_get", return_value=registry):
        with patch(
            "esphome_fleet.dr.async_entries_for_config_entry",
            return_value=[live_device],
        ):
            hass = SimpleNamespace()
            entry = SimpleNamespace(entry_id="entry-1")
            coordinator = SimpleNamespace(
                data={
                    "targets": [{"target": "still-here.yaml"}],
                    "workers": [],
                },
                base_url="http://test:8765",
            )
            _register_devices(hass, entry, coordinator)

    registry.async_remove_device.assert_not_called()
    registry.async_update_device.assert_not_called()
