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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._discovery import entity_already_registered
from .const import DOMAIN
from .coordinator import EsphomeFleetCoordinator
from .device import worker_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EsphomeFleetCoordinator = hass.data[DOMAIN][entry.entry_id]

    def _discover() -> None:
        # #62: registry-backed check; see sensor.py::async_setup_entry.
        new: list[WorkerOnlineBinarySensor] = []
        for w in (coordinator.data or {}).get("workers") or []:
            client_id = w.get("client_id")
            if not client_id:
                continue
            ent = WorkerOnlineBinarySensor(coordinator, entry.entry_id, client_id)
            if not entity_already_registered(hass, "binary_sensor", ent.unique_id):
                new.append(ent)
        if new:
            async_add_entities(new)

    _discover()
    entry.async_on_unload(coordinator.async_add_listener(_discover))


class WorkerOnlineBinarySensor(
    CoordinatorEntity[EsphomeFleetCoordinator], BinarySensorEntity
):
    # CR.7: promote worker-online to a primary state sensor. Users
    # build automations like "when all build workers are offline, alert
    # me"; DIAGNOSTIC hid it from the default entity picker.
    _attr_has_entity_name = True
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

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
