"""ESPHome Fleet Home Assistant integration.

Wires up:
  - HI.1  a config entry per add-on base URL (see config_flow.py)
  - HI.10 a DataUpdateCoordinator polling /ui/api/* every 30s (coordinator.py)
  - HI.2  three HA services (compile / cancel / validate) (services.py)
  - HI.3  per-target UpdateEntity (update.py)
  - HI.4  queue-depth + per-target firmware-version + per-worker
          active-jobs sensors (sensor.py)
  - HI.5  per-worker connectivity BinarySensor (binary_sensor.py)
  - HI.11 hub + per-target + per-worker DeviceInfo (device.py)
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONF_BASE_URL, DOMAIN
from .coordinator import EsphomeFleetCoordinator
from .device import hub_device_info, target_device_info, worker_device_info
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.UPDATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration from YAML (not used — config flow only)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ESPHome Fleet from a config entry."""
    base_url = entry.data[CONF_BASE_URL]

    coordinator = EsphomeFleetCoordinator(hass, base_url)
    # Block setup until the first poll succeeds so entities + services
    # have real data (and a real UpdateFailed bubbles up to HA as a
    # setup error).
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # HI.11: pre-register devices so they appear in HA's device registry
    # on the first poll even if their entities have no state yet. Keeps
    # HI.3/4/5 entities from creating orphan device rows later.
    _register_devices(hass, entry, coordinator)
    entry.async_on_unload(
        coordinator.async_add_listener(
            lambda: _register_devices(hass, entry, coordinator)
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_services(hass)

    _LOGGER.info("ESPHome Fleet entry %s set up against %s", entry.entry_id, base_url)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an ESPHome Fleet config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    domain_data = hass.data.get(DOMAIN, {})
    domain_data.pop(entry.entry_id, None)
    if not domain_data:
        hass.data.pop(DOMAIN, None)
    async_unregister_services(hass)
    return True


def _register_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: EsphomeFleetCoordinator,
) -> None:
    """Register/refresh the hub + per-target + per-worker HA devices.

    Idempotent — HA's device_registry.async_get_or_create deduplicates
    by identifiers. Called on setup and on every coordinator update so
    newly-added targets/workers show up without an HA restart.
    """
    registry = dr.async_get(hass)

    # Hub
    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        **hub_device_info(entry.entry_id, coordinator.base_url),
    )

    # Per-target
    for t in (coordinator.data or {}).get("targets") or []:
        if t.get("target"):
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                **target_device_info(t, entry.entry_id),
            )

    # Per-worker
    for w in (coordinator.data or {}).get("workers") or []:
        if w.get("client_id"):
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                **worker_device_info(w, entry.entry_id),
            )
