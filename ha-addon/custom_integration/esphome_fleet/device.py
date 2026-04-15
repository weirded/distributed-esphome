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

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


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
        manufacturer="ESPHome Fleet",
        model=model,
        sw_version=worker.get("client_version") or None,
        via_device=(DOMAIN, f"hub:{hub_entry_id}"),
    )
