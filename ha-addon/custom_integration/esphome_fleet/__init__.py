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

from .const import CONF_BASE_URL, CONF_TOKEN, DOMAIN
from .coordinator import EsphomeFleetCoordinator
from .device import hub_device_info, target_device_info, worker_device_info
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.UPDATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration from YAML (not used — config flow only)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ESPHome Fleet from a config entry."""
    base_url = entry.data[CONF_BASE_URL]
    # AU.7: token is optional only for entries created before AU.7
    # shipped — new entries always carry it, and the add-on now requires
    # a Bearer on every /ui/api/* call. Legacy entries keep working
    # until the user reauths (the coordinator falls back to sending no
    # Authorization header when the token is missing).
    token = entry.data.get(CONF_TOKEN)

    coordinator = EsphomeFleetCoordinator(hass, base_url, token=token, entry=entry)
    # Block setup until the first poll succeeds so entities + services
    # have real data (and a real UpdateFailed bubbles up to HA as a
    # setup error).
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # HI.11: pre-register devices so they appear in HA's device registry
    # on the first poll even if their entities have no state yet. Keeps
    # HI.3/4/5 entities from creating orphan device rows later.
    # CR.14: diff-skip the coordinator listener. `live_identifiers` rarely
    # changes on the 30 s poll cadence (targets come + go; workers flap
    # offline/online but that doesn't change the set). Tracking the
    # last-seen identifier set and short-circuiting when it's unchanged
    # keeps `async_get_or_create` + `async_entries_for_config_entry` off
    # the hot path on idle systems.
    last_live_ids: set[tuple[str, str]] = set()

    def _on_coordinator_update() -> None:
        nonlocal last_live_ids
        live = _compute_live_identifiers(entry, coordinator)
        if live == last_live_ids:
            return
        last_live_ids = live
        _register_devices(hass, entry, coordinator, live_identifiers=live)

    # Seed with a full registration on setup so the hub device + every
    # current target/worker appear immediately.
    last_live_ids = _compute_live_identifiers(entry, coordinator)
    _register_devices(hass, entry, coordinator, live_identifiers=last_live_ids)
    entry.async_on_unload(
        coordinator.async_add_listener(_on_coordinator_update)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_services(hass)

    # #41: real-time event stream. Triggers coordinator refresh on every
    # server-side state change so HA entities update within milliseconds
    # instead of waiting on the 30 s polling interval.
    # CR.12: `async_on_unload` accepts a coroutine function directly; HA
    # awaits it as part of unload. The earlier `hass.async_create_task`
    # wrapper decoupled unload completion from WS teardown, leaking on
    # rapid reloads.
    from .ws_client import EventStreamClient  # noqa: PLC0415
    event_stream = EventStreamClient(hass, coordinator)
    event_stream.start()
    entry.async_on_unload(event_stream.stop)

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


def _compute_live_identifiers(
    entry: ConfigEntry,
    coordinator: EsphomeFleetCoordinator,
) -> set[tuple[str, str]]:
    """Return the identifier set the registry SHOULD contain right now.

    Extracted from ``_register_devices`` so callers (CR.14 diff-skip)
    can compare two snapshots cheaply without running the full register
    + prune pass.
    """
    live: set[tuple[str, str]] = {(DOMAIN, f"hub:{entry.entry_id}")}
    for t in (coordinator.data or {}).get("targets") or []:
        if t.get("target"):
            live.add((DOMAIN, f"target:{t['target']}"))
    for w in (coordinator.data or {}).get("workers") or []:
        if w.get("client_id"):
            live.add((DOMAIN, f"worker:{w['client_id']}"))
    return live


def _register_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: EsphomeFleetCoordinator,
    *,
    live_identifiers: set[tuple[str, str]] | None = None,
) -> None:
    """Register/refresh the hub + per-target + per-worker HA devices.

    Idempotent — HA's device_registry.async_get_or_create deduplicates
    by identifiers. Called on setup and (via the CR.14 diff-skip gate)
    on coordinator ticks where the identifier set actually changed, so
    newly-added targets/workers show up without an HA restart.

    #39: also removes stale devices for targets/workers that vanished
    from the add-on (YAML deleted, worker decommissioned). For merged
    devices (#27) we only detach our config_entry — the device row
    survives as long as another integration (e.g. native ESPHome) still
    references it.
    """
    registry = dr.async_get(hass)

    # Hub
    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        **hub_device_info(entry.entry_id, coordinator.base_url),
    )

    if live_identifiers is None:
        live_identifiers = {(DOMAIN, f"hub:{entry.entry_id}")}

    # Per-target
    for t in (coordinator.data or {}).get("targets") or []:
        if t.get("target"):
            live_identifiers.add((DOMAIN, f"target:{t['target']}"))
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                **target_device_info(t, entry.entry_id),
            )

    # Per-worker
    for w in (coordinator.data or {}).get("workers") or []:
        if w.get("client_id"):
            live_identifiers.add((DOMAIN, f"worker:{w['client_id']}"))
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                **worker_device_info(w, entry.entry_id),
            )

    # #39: prune devices that belong to this config entry but are no
    # longer in the coordinator snapshot.
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        # Keep the device if any of its identifiers are still live.
        if device.identifiers & live_identifiers:
            continue
        # Only consider devices that have at least one Fleet identifier
        # (avoid touching devices we were merged into purely by MAC
        # connection without an identifier match).
        has_fleet_ident = any(d == DOMAIN for d, _ in device.identifiers)
        if not has_fleet_ident:
            continue
        if len(device.config_entries) > 1:
            # Merged with another integration (#27) — just detach us.
            _LOGGER.info(
                "Detaching stale Fleet device %s (%s) — still owned by "
                "other integrations",
                device.name, device.id,
            )
            registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )
        else:
            _LOGGER.info(
                "Removing stale Fleet device %s (%s)",
                device.name, device.id,
            )
            registry.async_remove_device(device.id)
