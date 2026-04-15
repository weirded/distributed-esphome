"""Binary sensor entities (HI.5) — worker connectivity.

One `BinarySensor` per build worker. `is_on` maps to `worker.online` (as
reported by the server's registry heartbeat check) and uses HA's
`connectivity` device class so the UI picks up the right icon + label.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EsphomeFleetCoordinator
from .device import worker_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EsphomeFleetCoordinator = hass.data[DOMAIN][entry.entry_id]

    seen: set[str] = set()

    def _discover() -> None:
        new: list[WorkerOnlineBinarySensor] = []
        for w in (coordinator.data or {}).get("workers") or []:
            client_id = w.get("client_id")
            if client_id and client_id not in seen:
                seen.add(client_id)
                new.append(WorkerOnlineBinarySensor(coordinator, entry.entry_id, client_id))
        if new:
            async_add_entities(new)

    _discover()
    entry.async_on_unload(coordinator.async_add_listener(_discover))


class WorkerOnlineBinarySensor(
    CoordinatorEntity[EsphomeFleetCoordinator], BinarySensorEntity
):
    _attr_has_entity_name = True
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: EsphomeFleetCoordinator, entry_id: str, client_id: str
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._client_id = client_id
        self._attr_unique_id = f"{entry_id}_worker_{client_id}_online"

    @property
    def _worker(self) -> dict[str, Any] | None:
        for w in (self.coordinator.data or {}).get("workers") or []:
            if w.get("client_id") == self._client_id:
                return w
        return None

    @property
    def available(self) -> bool:
        return super().available and self._worker is not None

    @property
    def device_info(self):
        w = self._worker or {"client_id": self._client_id}
        return worker_device_info(w, self._entry_id)

    @property
    def is_on(self) -> bool:
        w = self._worker or {}
        return bool(w.get("online"))
