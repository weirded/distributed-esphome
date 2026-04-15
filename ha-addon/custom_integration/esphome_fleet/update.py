"""Update entities (HI.3) — one per managed ESPHome target.

`installed_version` = device's currently-reported running firmware version.
`latest_version`    = the ESPHome version the next compile would use
                      (pinned_version if set, else the add-on's global
                      selected version).

When HA's Update card shows "Install", `async_install()` calls the
add-on's /ui/api/compile — same path as clicking Upgrade in the UI.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EsphomeFleetCoordinator
from .device import target_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add one UpdateEntity per managed target, refreshing on each poll."""
    coordinator: EsphomeFleetCoordinator = hass.data[DOMAIN][entry.entry_id]

    seen: set[str] = set()

    def _discover() -> None:
        targets = coordinator.data.get("targets") if coordinator.data else []
        new_entities: list[TargetFirmwareUpdate] = []
        for t in targets or []:
            filename = t.get("target")
            if not filename or filename in seen:
                continue
            seen.add(filename)
            new_entities.append(TargetFirmwareUpdate(coordinator, entry.entry_id, filename))
        if new_entities:
            async_add_entities(new_entities)

    _discover()
    entry.async_on_unload(coordinator.async_add_listener(_discover))


class TargetFirmwareUpdate(CoordinatorEntity[EsphomeFleetCoordinator], UpdateEntity):
    """Update entity for a single managed ESPHome target."""

    _attr_has_entity_name = True
    _attr_name = "Firmware"
    _attr_supported_features = UpdateEntityFeature.INSTALL
    _attr_title = "ESPHome Firmware"

    def __init__(
        self,
        coordinator: EsphomeFleetCoordinator,
        entry_id: str,
        target_filename: str,
    ) -> None:
        super().__init__(coordinator)
        self._target_filename = target_filename
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_target_{target_filename}_update"

    @property
    def _target(self) -> dict[str, Any] | None:
        for t in (self.coordinator.data or {}).get("targets") or []:
            if t.get("target") == self._target_filename:
                return t
        return None

    @property
    def available(self) -> bool:
        return super().available and self._target is not None

    @property
    def device_info(self):
        t = self._target or {"target": self._target_filename}
        return target_device_info(t, self._entry_id)

    @property
    def installed_version(self) -> str | None:
        t = self._target or {}
        return t.get("running_version") or None

    @property
    def latest_version(self) -> str | None:
        t = self._target or {}
        # pinned wins over the server's currently-selected version
        if t.get("pinned_version"):
            return t["pinned_version"]
        versions = (self.coordinator.data or {}).get("esphome_versions") or {}
        return versions.get("selected") or t.get("server_version") or None

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Enqueue a compile for this target via the add-on API."""
        payload: dict[str, Any] = {"targets": [self._target_filename]}
        if version:
            payload["esphome_version"] = version
        await self.coordinator.async_post_json("/ui/api/compile", payload)
        # Ask the coordinator to refresh so the queue_depth sensor etc.
        # reflect the new pending job within a second or two.
        await self.coordinator.async_request_refresh()
