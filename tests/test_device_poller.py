"""Unit tests for DevicePoller — device name → YAML mapping and data model."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Patch heavy optional dependencies before importing device_poller.
# These are only needed at runtime (mDNS discovery, device API, ICMP ping)
# and are not available in the test environment.
sys.modules.setdefault("zeroconf", MagicMock())
sys.modules.setdefault("zeroconf.asyncio", MagicMock())
sys.modules.setdefault("aioesphomeapi", MagicMock())
_icmplib_stub = MagicMock()
sys.modules.setdefault("icmplib", _icmplib_stub)

from device_poller import Device, DevicePoller


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


# ---------------------------------------------------------------------------
# Hyphen/underscore normalization (bug #159)
# ---------------------------------------------------------------------------

def test_map_target_hyphen_to_underscore(poller):
    """mDNS advertises underscores but esphome.name uses hyphens."""
    poller.update_compile_targets(["led-controller-v2.yaml"])
    # mDNS name has underscores
    assert poller._map_target("led_controller_v2") == "led-controller-v2.yaml"


def test_map_target_underscore_to_hyphen(poller):
    """Reverse direction: config uses underscores, mDNS could use either."""
    poller.update_compile_targets(["led_controller.yaml"])
    assert poller._map_target("led-controller") == "led_controller.yaml"


def test_map_target_name_map_hyphen_normalization(poller):
    """name_to_target map entries also match with normalized hyphens/underscores."""
    poller.update_compile_targets(
        ["rocket-lamp.yaml"],
        name_to_target={"led-controller-v2-rocket-lamp": "rocket-lamp.yaml"},
    )
    # mDNS advertises with underscores
    assert poller._map_target("led_controller_v2_rocket_lamp") == "rocket-lamp.yaml"


# ---------------------------------------------------------------------------
# _ping_device
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ping_device_returns_true_when_alive(poller):
    """_ping_device returns True when icmplib reports the host is alive."""
    alive_host = MagicMock()
    alive_host.is_alive = True
    with patch("device_poller._PING_AVAILABLE", True), \
         patch("icmplib.async_ping", new=AsyncMock(return_value=alive_host)):
        result = await poller._ping_device("living_room", "192.168.1.10")
    assert result is True


@pytest.mark.asyncio
async def test_ping_device_returns_false_when_not_alive(poller):
    """_ping_device returns False when icmplib reports no response."""
    dead_host = MagicMock()
    dead_host.is_alive = False
    with patch("device_poller._PING_AVAILABLE", True), \
         patch("icmplib.async_ping", new=AsyncMock(return_value=dead_host)):
        result = await poller._ping_device("living_room", "192.168.1.10")
    assert result is False


@pytest.mark.asyncio
async def test_ping_device_returns_false_on_exception(poller):
    """_ping_device swallows exceptions and returns False."""
    with patch("device_poller._PING_AVAILABLE", True), \
         patch("icmplib.async_ping", new=AsyncMock(side_effect=OSError("socket error"))):
        result = await poller._ping_device("living_room", "192.168.1.10")
    assert result is False


# ---------------------------------------------------------------------------
# _query_device ping fallback behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_device_ping_fallback_marks_online(poller):
    """When API fails (non-encryption error) but ping succeeds, device is online."""
    import device_poller as dp

    poller._devices["living_room"] = Device(
        name="living_room", ip_address="192.168.1.10", online=False
    )

    mock_client = MagicMock()
    mock_client.connect = AsyncMock(side_effect=ConnectionRefusedError("refused"))
    mock_client.disconnect = AsyncMock()

    alive_host = MagicMock()
    alive_host.is_alive = True

    with patch.object(dp.aioesphomeapi, "APIClient", return_value=mock_client), \
         patch("device_poller._PING_AVAILABLE", True), \
         patch("icmplib.async_ping", new=AsyncMock(return_value=alive_host)), \
         patch.object(poller, "_save_cache"):
        await poller._query_device("living_room", "192.168.1.10")

    dev = poller._devices["living_room"]
    assert dev.online is True
    assert dev.last_seen is not None


@pytest.mark.asyncio
async def test_query_device_ping_fallback_marks_offline(poller):
    """When both API and ping fail, device is marked offline."""
    import device_poller as dp

    poller._devices["living_room"] = Device(
        name="living_room", ip_address="192.168.1.10", online=True
    )

    mock_client = MagicMock()
    mock_client.connect = AsyncMock(side_effect=ConnectionRefusedError("refused"))
    mock_client.disconnect = AsyncMock()

    dead_host = MagicMock()
    dead_host.is_alive = False

    with patch.object(dp.aioesphomeapi, "APIClient", return_value=mock_client), \
         patch("device_poller._PING_AVAILABLE", True), \
         patch("icmplib.async_ping", new=AsyncMock(return_value=dead_host)), \
         patch.object(poller, "_save_cache"):
        await poller._query_device("living_room", "192.168.1.10")

    dev = poller._devices["living_room"]
    assert dev.online is False


@pytest.mark.asyncio
async def test_query_device_ping_skipped_when_unavailable(poller):
    """When _PING_AVAILABLE is False, no ping is attempted and device goes offline."""
    import device_poller as dp

    poller._devices["living_room"] = Device(
        name="living_room", ip_address="192.168.1.10", online=True
    )

    mock_client = MagicMock()
    mock_client.connect = AsyncMock(side_effect=ConnectionRefusedError("refused"))
    mock_client.disconnect = AsyncMock()

    with patch.object(dp.aioesphomeapi, "APIClient", return_value=mock_client), \
         patch("device_poller._PING_AVAILABLE", False), \
         patch.object(poller, "_ping_device", new=AsyncMock()) as mock_ping, \
         patch.object(poller, "_save_cache"):
        await poller._query_device("living_room", "192.168.1.10")

    mock_ping.assert_not_called()
    assert poller._devices["living_room"].online is False


@pytest.mark.asyncio
async def test_query_device_encryption_error_skips_ping(poller):
    """Encryption errors mark the device online immediately without pinging."""
    import device_poller as dp

    poller._devices["living_room"] = Device(
        name="living_room", ip_address="192.168.1.10", online=False
    )

    mock_client = MagicMock()
    mock_client.connect = AsyncMock(side_effect=Exception("Bad encryption key"))
    mock_client.disconnect = AsyncMock()

    with patch.object(dp.aioesphomeapi, "APIClient", return_value=mock_client), \
         patch("device_poller._PING_AVAILABLE", True), \
         patch.object(poller, "_ping_device", new=AsyncMock()) as mock_ping, \
         patch.object(poller, "_save_cache"):
        await poller._query_device("living_room", "192.168.1.10")

    mock_ping.assert_not_called()
    assert poller._devices["living_room"].online is True
