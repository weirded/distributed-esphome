"""Shared DeviceInfo helpers for HA device registry (HI.11).

Three kinds of HA devices in the registry for ESPHome Fleet:

  1. A single "hub" device representing the add-on instance itself.
     Queue-depth sensor hangs off this one. Uniquely keyed by the
     config entry id so multiple add-on instances don't collide.

  2. One device per managed target (ESPHome config YAML). Keyed by
     `("esphome_fleet", f"target:{filename}")` so the identifier is
     stable even if the friendly name changes.

  3. One device per build worker. Keyed by
     `("esphome_fleet", f"worker:{client_id}")`.

Entities attach via the `device_info` attribute. HA groups them into
device rows automatically.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo

from .const import DOMAIN


def _normalize_mac(value: str | None) -> str | None:
    """Canonicalize a MAC to HA's lower-case, colon-separated form.

    The device poller may surface MACs as ``"AA:BB:CC:DD:EE:FF"`` or the
    ESPHome native-API ``"aabbccddeeff"`` form. HA's device registry keys
    off the colon-separated lower-case shape, so an un-normalized value
    silently fails to merge.
    """
    if not value:
        return None
    cleaned = value.strip().lower().replace("-", "").replace(":", "")
    if len(cleaned) != 12 or not all(c in "0123456789abcdef" for c in cleaned):
        return None
    return ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))


def hub_device_info(entry_id: str, base_url: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"hub:{entry_id}")},
        name="ESPHome Fleet",
        manufacturer="ESPHome Fleet",
        model="Add-on server",
        configuration_url=base_url,
        entry_type=None,  # a real hub, not a service
    )


def target_device_info(target: dict[str, Any], hub_entry_id: str) -> DeviceInfo:
    """Build DeviceInfo for a managed ESPHome YAML target.

    Name falls back through friendly_name → device_name → filename stem
    so we never end up with a blank device row.
    """
    filename = target["target"]
    stem = filename.removesuffix(".yaml").removesuffix(".yml")
    display = (
        target.get("friendly_name")
        or target.get("device_name")
        or stem
    )
    # Model = platform + board if both are known (e.g. "esp32 · esp32dev").
    # Metadata keys match the server's `scanner.get_device_metadata` shape.
    platform = target.get("platform")
    board = target.get("board")
    if platform and board:
        model = f"{platform} · {board}"
    elif platform:
        model = str(platform)
    elif board:
        model = str(board)
    else:
        model = "ESPHome device"

    info = DeviceInfo(
        identifiers={(DOMAIN, f"target:{filename}")},
        name=display,
        manufacturer="ESPHome",
        model=model,
        sw_version=target.get("running_version") or None,
        via_device=(DOMAIN, f"hub:{hub_entry_id}"),
    )
    # #27: when the MAC is known, attach it as a connection so HA's
    # device registry merges this device row with the one that the
    # native ESPHome integration already registered for the same chip.
    # Our entities (Schedule, Pinned version, Firmware Update) then
    # appear on the same card as ESPHome's entities — no duplicate
    # device rows per managed target.
    if (mac := _normalize_mac(target.get("mac_address"))):
        info["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
    if (area := target.get("area")):
        info["suggested_area"] = area
    return info


def worker_device_info(worker: dict[str, Any], hub_entry_id: str) -> DeviceInfo:
    """Build DeviceInfo for a build worker."""
    client_id = worker["client_id"]
    hostname = worker.get("hostname") or client_id[:8]
    system = worker.get("system_info") or {}
    # CPU model + OS is the most useful one-line model string.
    cpu = system.get("cpu_model")
    os_info = system.get("os_version")
    if cpu and os_info:
        model = f"{cpu} · {os_info}"
    elif cpu:
        model = str(cpu)
    elif os_info:
        model = str(os_info)
    else:
        model = "Build worker"
    return DeviceInfo(
        identifiers={(DOMAIN, f"worker:{client_id}")},
        name=f"{hostname} (worker)",
        # #66: a distinct manufacturer string lets the compile service
        # filter the "worker" device selector to only show workers
        # (and the target selector to only show devices via a
        # `manufacturer: "ESPHome"` filter). Hub keeps "ESPHome Fleet".
        manufacturer="ESPHome Fleet Worker",
        model=model,
        sw_version=worker.get("client_version") or None,
        via_device=(DOMAIN, f"hub:{hub_entry_id}"),
    )
