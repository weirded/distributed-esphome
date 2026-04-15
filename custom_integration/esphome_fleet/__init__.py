"""ESPHome Fleet Home Assistant integration.

Wires up:
  - HI.1  a config entry per add-on base URL (see config_flow.py)
  - HI.10 a DataUpdateCoordinator polling /ui/api/* every 30s (coordinator.py)
  - HI.2  three HA services (compile / cancel / validate) (services.py)

Entity platforms (HI.3/4/5) land in a follow-up turn — the coordinator
is already producing the data those entities will consume.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_BASE_URL, DOMAIN
from .coordinator import EsphomeFleetCoordinator
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration from YAML (not used — config flow only)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ESPHome Fleet from a config entry."""
    base_url = entry.data[CONF_BASE_URL]

    coordinator = EsphomeFleetCoordinator(hass, base_url)
    # Block setup until the first poll succeeds so services have real
    # data (and a real UpdateFailed bubbles up to HA as a setup error).
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    async_register_services(hass)
    _LOGGER.info("ESPHome Fleet entry %s set up against %s", entry.entry_id, base_url)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an ESPHome Fleet config entry."""
    domain_data = hass.data.get(DOMAIN, {})
    domain_data.pop(entry.entry_id, None)
    if not domain_data:
        hass.data.pop(DOMAIN, None)
    async_unregister_services(hass)
    return True
