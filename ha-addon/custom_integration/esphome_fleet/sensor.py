"""Sensor entities (HI.4).

Three flavors:

  QueueDepthSensor              — global, hangs off the hub device.
                                   State = count of pending + working jobs.
  TargetFirmwareVersionSensor   — one per managed target. State =
                                   running_version as reported by the
                                   device poller.
  WorkerActiveJobsSensor        — one per worker. State = number of
                                   WORKING queue entries whose
                                   assigned_client_id matches.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EsphomeFleetCoordinator
from .device import hub_device_info, target_device_info, worker_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EsphomeFleetCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Queue depth is a single always-present entity.
    async_add_entities([QueueDepthSensor(coordinator, entry.entry_id, coordinator.base_url)])

    seen_targets: set[str] = set()
    seen_workers: set[str] = set()

    def _discover() -> None:
        new: list[SensorEntity] = []

        for t in (coordinator.data or {}).get("targets") or []:
            filename = t.get("target")
            if filename and filename not in seen_targets:
                seen_targets.add(filename)
                new.append(TargetFirmwareVersionSensor(coordinator, entry.entry_id, filename))

        for w in (coordinator.data or {}).get("workers") or []:
            client_id = w.get("client_id")
            if client_id and client_id not in seen_workers:
                seen_workers.add(client_id)
                new.append(WorkerActiveJobsSensor(coordinator, entry.entry_id, client_id))

        if new:
            async_add_entities(new)

    _discover()
    entry.async_on_unload(coordinator.async_add_listener(_discover))


class QueueDepthSensor(CoordinatorEntity[EsphomeFleetCoordinator], SensorEntity):
    """Count of non-terminal (pending + working) jobs."""

    _attr_has_entity_name = True
    _attr_name = "Queue depth"
    _attr_icon = "mdi:tray-full"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "jobs"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: EsphomeFleetCoordinator, entry_id: str, base_url: str) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._base_url = base_url
        self._attr_unique_id = f"{entry_id}_queue_depth"

    @property
    def device_info(self):
        return hub_device_info(self._entry_id, self._base_url)

    @property
    def native_value(self) -> int:
        queue = (self.coordinator.data or {}).get("queue") or []
        return sum(1 for j in queue if j.get("state") in ("pending", "working"))


class TargetFirmwareVersionSensor(CoordinatorEntity[EsphomeFleetCoordinator], SensorEntity):
    """Per-target firmware version sensor."""

    _attr_has_entity_name = True
    _attr_name = "Firmware version"
    _attr_icon = "mdi:chip"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: EsphomeFleetCoordinator, entry_id: str, target_filename: str
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._target_filename = target_filename
        self._attr_unique_id = f"{entry_id}_target_{target_filename}_firmware_version"

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
    def native_value(self) -> str | None:
        t = self._target or {}
        return t.get("running_version") or None


class WorkerActiveJobsSensor(CoordinatorEntity[EsphomeFleetCoordinator], SensorEntity):
    """Per-worker active-jobs sensor — count of WORKING jobs on the worker."""

    _attr_has_entity_name = True
    _attr_name = "Active jobs"
    _attr_icon = "mdi:wrench-cog"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "jobs"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: EsphomeFleetCoordinator, entry_id: str, client_id: str
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._client_id = client_id
        self._attr_unique_id = f"{entry_id}_worker_{client_id}_active_jobs"

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
    def native_value(self) -> int:
        queue = (self.coordinator.data or {}).get("queue") or []
        return sum(
            1
            for j in queue
            if j.get("state") == "working" and j.get("assigned_client_id") == self._client_id
        )
