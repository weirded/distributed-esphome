"""Unit tests for DevicePoller — device name → YAML mapping and data model."""

from __future__ import annotations

import json
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

    # #59: old device (never seen online, no last_seen) is purged as a stale
    # proactive entry when its YAML target is deleted.
    assert "old" not in poller._devices


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


# ---------------------------------------------------------------------------
# bug #179 — IPv6 address parsing and merge-by-normalized-name
# ---------------------------------------------------------------------------

def test_extract_address_prefers_parsed_addresses(poller):
    """When ServiceInfo.parsed_addresses() returns strings, use them directly."""
    info = MagicMock()
    info.addresses = [b"\xc0\xa8\x01\x10"]  # 192.168.1.16 (4 bytes)
    info.parsed_addresses.return_value = ["192.168.1.16"]
    assert poller._extract_address(info) == "192.168.1.16"


def test_extract_address_prefers_ipv4_when_both_present(poller):
    info = MagicMock()
    info.addresses = []
    info.parsed_addresses.return_value = ["fd00::1", "192.168.1.20"]
    assert poller._extract_address(info) == "192.168.1.20"


def test_extract_address_handles_ipv6_only(poller):
    """Thread devices advertise via mDNS with only IPv6 AAAA records."""
    info = MagicMock()
    info.addresses = []
    info.parsed_addresses.return_value = ["fd00::1234:5678"]
    assert poller._extract_address(info) == "fd00::1234:5678"


def test_extract_address_falls_back_to_packed_ipv4(poller):
    """When parsed_addresses isn't available, parse 4-byte packed IPv4."""
    info = MagicMock()
    info.addresses = [b"\x0a\x00\x00\x05"]  # 10.0.0.5
    info.parsed_addresses.side_effect = AttributeError()
    assert poller._extract_address(info) == "10.0.0.5"


def test_extract_address_falls_back_to_packed_ipv6(poller):
    """When parsed_addresses isn't available, parse 16-byte packed IPv6."""
    info = MagicMock()
    # ::1 (loopback) packed = 16 bytes, last byte = 1
    info.addresses = [b"\x00" * 15 + b"\x01"]
    info.parsed_addresses.side_effect = AttributeError()
    assert poller._extract_address(info) == "::1"


def test_extract_address_returns_none_for_empty(poller):
    info = MagicMock()
    info.addresses = []
    info.parsed_addresses.return_value = []
    assert poller._extract_address(info) is None


def test_find_existing_device_key_exact_match(poller):
    poller._devices["my-device"] = Device(name="my-device", ip_address="")
    assert poller._find_existing_device_key("my-device") == "my-device"


def test_find_existing_device_key_normalized_match(poller):
    """mDNS-discovered name (underscores) matches the YAML row (hyphens)."""
    poller._devices["my-device"] = Device(name="my-device", ip_address="")
    # mDNS would deliver "my_device" — should match the existing hyphen row
    assert poller._find_existing_device_key("my_device") == "my-device"


def test_find_existing_device_key_no_match(poller):
    poller._devices["my-device"] = Device(name="my-device", ip_address="")
    assert poller._find_existing_device_key("other-device") is None


def test_update_compile_targets_creates_proactive_row_for_thread_target(poller):
    """A Thread-only target with no wifi block now gets a proactive Device row,
    so an mDNS-discovered entry merges into it instead of duplicating (#179)."""
    poller.update_compile_targets(
        ["thread-dev.yaml"],
        name_to_target={"thread-dev": "thread-dev.yaml", "thread-dev.yaml": "thread-dev.yaml"},
        address_overrides={"thread-dev": "thread-dev.local"},
    )
    assert "thread-dev" in poller._devices
    dev = poller._devices["thread-dev"]
    assert dev.compile_target == "thread-dev.yaml"
    assert dev.online is False  # not yet seen via mDNS


def test_update_compile_targets_does_not_duplicate_when_yaml_and_mdns_both_present(poller):
    """If a YAML row already exists and mDNS rediscovery happens for the
    underscore-normalized variant, _find_existing_device_key keeps it as one row."""
    # Simulate the proactive YAML-side row
    poller.update_compile_targets(
        ["my-thread.yaml"],
        name_to_target={"my-thread": "my-thread.yaml", "my-thread.yaml": "my-thread.yaml"},
        address_overrides={"my-thread": "my-thread.local"},
    )
    assert "my-thread" in poller._devices

    # Now simulate mDNS arriving with the underscore variant
    existing = poller._find_existing_device_key("my_thread")
    assert existing == "my-thread"
    # Only one row total
    assert len([k for k in poller._devices if k in ("my-thread", "my_thread")]) == 1


# ---------------------------------------------------------------------------
# bug #187 — cached devices missing address_source
# ---------------------------------------------------------------------------

def test_update_compile_targets_fills_missing_address_source_on_existing_device(poller):
    """A device loaded from cache before address_source existed has IP but no
    source. update_compile_targets should backfill the source from the YAML
    side, even though the IP is already populated."""
    # Simulate a device loaded from a pre-LIB.0 cache: IP set, no source
    poller._devices["my-device"] = Device(
        name="my-device",
        ip_address="192.168.1.42",  # already set, e.g. from cache
        address_source=None,  # missing — this is the bug
    )

    poller.update_compile_targets(
        ["my-device.yaml"],
        name_to_target={"my-device": "my-device.yaml", "my-device.yaml": "my-device.yaml"},
        address_overrides={"my-device": "192.168.1.42"},
        address_sources={"my-device": "wifi_use_address"},
    )

    dev = poller._devices["my-device"]
    # IP is unchanged (already set)
    assert dev.ip_address == "192.168.1.42"
    # Source is now backfilled from the YAML
    assert dev.address_source == "wifi_use_address"


def test_update_compile_targets_does_not_overwrite_existing_address_source(poller):
    """If a device already has an address_source (e.g. from mDNS), don't
    clobber it with the YAML default. Explicit user choices stay authoritative
    in the other direction (mDNS handler), and pre-existing values stay too."""
    poller._devices["my-device"] = Device(
        name="my-device",
        ip_address="192.168.1.42",
        address_source="mdns",  # already set
    )

    poller.update_compile_targets(
        ["my-device.yaml"],
        name_to_target={"my-device": "my-device.yaml", "my-device.yaml": "my-device.yaml"},
        address_overrides={"my-device": "my-device.local"},
        address_sources={"my-device": "mdns_default"},
    )

    # The pre-existing "mdns" source should be preserved
    assert poller._devices["my-device"].address_source == "mdns"


def test_cache_does_not_persist_ip_or_address_source(tmp_path, monkeypatch):
    """Cache must not persist ip_address or address_source — DHCP IPs go stale
    between restarts. Only running_version, compilation_time, and mac_address
    are stable enough to cache (#187)."""
    import device_poller as dp
    cache_file = tmp_path / "device_cache.json"
    monkeypatch.setattr(dp, "DEVICE_CACHE_FILE", cache_file)

    p = DevicePoller(poll_interval=60)
    p._devices["dev1"] = Device(
        name="dev1",
        ip_address="192.168.1.42",  # would go stale on DHCP renewal
        running_version="2026.3.2",
        compilation_time="Mar 29 2026, 17:00:00",
        mac_address="AA:BB:CC:DD:EE:FF",
        address_source="mdns",  # also tied to a specific IP
    )
    p._save_cache()

    saved = json.loads(cache_file.read_text())
    assert "dev1" in saved
    assert saved["dev1"].get("ip_address") is None  # NOT persisted
    assert saved["dev1"].get("address_source") is None  # NOT persisted
    # But the stable bits ARE persisted
    assert saved["dev1"]["running_version"] == "2026.3.2"
    assert saved["dev1"]["mac_address"] == "AA:BB:CC:DD:EE:FF"


def test_cache_load_does_not_restore_ip_or_address_source(tmp_path, monkeypatch):
    """Loading cached devices must leave ip_address blank and address_source
    None — both will be repopulated by update_compile_targets and mDNS (#187)."""
    import device_poller as dp
    cache_file = tmp_path / "device_cache.json"
    # Simulate an OLD cache that had IP and address_source persisted
    cache_file.write_text(json.dumps({
        "dev1": {
            "ip_address": "192.168.1.42",  # might be stale
            "address_source": "mdns",
            "running_version": "2026.3.2",
            "compilation_time": "Mar 29 2026, 17:00:00",
            "mac_address": "AA:BB:CC:DD:EE:FF",
        }
    }))
    monkeypatch.setattr(dp, "DEVICE_CACHE_FILE", cache_file)

    p = DevicePoller(poll_interval=60)
    # Load explicitly (constructor already called once on the empty path)
    p._load_cache()

    dev = p._devices["dev1"]
    # IP and source NOT restored — start fresh, get repopulated by YAML/mDNS
    assert dev.ip_address == ""
    assert dev.address_source is None
    # Stable bits ARE restored
    assert dev.running_version == "2026.3.2"
    assert dev.mac_address == "AA:BB:CC:DD:EE:FF"
