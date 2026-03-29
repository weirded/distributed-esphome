"""Unit tests for DevicePoller — device name → YAML mapping and data model."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make server code importable
sys.path.insert(0, str(Path(__file__).parent.parent / "ha-addon" / "server"))

# Patch heavy optional dependencies before importing device_poller
sys.modules.setdefault("zeroconf", MagicMock())
sys.modules.setdefault("zeroconf.asyncio", MagicMock())
sys.modules.setdefault("aioesphomeapi", MagicMock())

from device_poller import Device, DevicePoller  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def poller():
    return DevicePoller(poll_interval=60)


TARGETS = ["living_room.yaml", "bedroom.yaml", "kitchen.yaml", "garage_door.yaml"]


# ---------------------------------------------------------------------------
# Device name → YAML mapping
# ---------------------------------------------------------------------------

def test_map_known_target(poller):
    poller.update_compile_targets(TARGETS)
    result = poller._map_target("living_room")
    assert result == "living_room.yaml"


def test_map_known_target_underscore(poller):
    poller.update_compile_targets(TARGETS)
    result = poller._map_target("garage_door")
    assert result == "garage_door.yaml"


def test_map_unknown_device_returns_none(poller):
    poller.update_compile_targets(TARGETS)
    result = poller._map_target("unknown_device")
    assert result is None


def test_map_empty_targets(poller):
    poller.update_compile_targets([])
    result = poller._map_target("living_room")
    assert result is None


def test_update_compile_targets_remaps_existing_devices(poller):
    """Existing devices should get their compile_target updated when targets change."""
    # Add a device manually
    poller._devices["living_room"] = Device(
        name="living_room",
        ip_address="192.168.1.10",
        compile_target=None,
    )

    poller.update_compile_targets(TARGETS)

    assert poller._devices["living_room"].compile_target == "living_room.yaml"


def test_unmanaged_device_has_none_compile_target(poller):
    poller.update_compile_targets(TARGETS)
    poller._devices["mystery_device"] = Device(
        name="mystery_device",
        ip_address="192.168.1.99",
        compile_target=poller._map_target("mystery_device"),
    )
    dev = poller._devices["mystery_device"]
    assert dev.compile_target is None


# ---------------------------------------------------------------------------
# Device model
# ---------------------------------------------------------------------------

def test_device_to_dict():
    from datetime import datetime, timezone
    now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    dev = Device(
        name="living_room",
        ip_address="192.168.1.10",
        online=True,
        running_version="2024.3.1",
        last_seen=now,
        compile_target="living_room.yaml",
    )
    d = dev.to_dict()
    assert d["name"] == "living_room"
    assert d["ip_address"] == "192.168.1.10"
    assert d["online"] is True
    assert d["running_version"] == "2024.3.1"
    assert d["compile_target"] == "living_room.yaml"
    assert "last_seen" in d


def test_device_to_dict_none_fields():
    dev = Device(name="dev1", ip_address="", online=False)
    d = dev.to_dict()
    assert d["running_version"] is None
    assert d["last_seen"] is None
    assert d["compile_target"] is None


# ---------------------------------------------------------------------------
# get_devices
# ---------------------------------------------------------------------------

def test_get_devices_empty(poller):
    assert poller.get_devices() == []


def test_get_devices_returns_all(poller):
    poller._devices["d1"] = Device(name="d1", ip_address="1.1.1.1")
    poller._devices["d2"] = Device(name="d2", ip_address="2.2.2.2")
    devs = poller.get_devices()
    assert len(devs) == 2
    names = {d.name for d in devs}
    assert names == {"d1", "d2"}


# ---------------------------------------------------------------------------
# update_compile_targets: multiple calls
# ---------------------------------------------------------------------------

def test_update_targets_idempotent(poller):
    poller.update_compile_targets(TARGETS)
    poller.update_compile_targets(TARGETS)
    assert poller._compile_targets == TARGETS


def test_update_targets_with_new_set(poller):
    poller.update_compile_targets(["old.yaml"])
    poller._devices["old"] = Device(name="old", ip_address="1.2.3.4", compile_target="old.yaml")

    new_targets = ["new_device.yaml"]
    poller.update_compile_targets(new_targets)

    # Old device should now have no compile target (not in new set)
    assert poller._devices["old"].compile_target is None


# ---------------------------------------------------------------------------
# Stem matching edge cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("device_name, targets, expected", [
    ("living_room", ["living_room.yaml"], "living_room.yaml"),
    ("bedroom", ["bedroom.yaml", "living_room.yaml"], "bedroom.yaml"),
    ("no_match", ["living_room.yaml"], None),
    ("living_room", [], None),
    ("a", ["a.yaml"], "a.yaml"),
])
def test_map_target_parametrized(device_name, targets, expected, poller):
    poller.update_compile_targets(targets)
    assert poller._map_target(device_name) == expected
