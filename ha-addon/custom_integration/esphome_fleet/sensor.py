"""Sensor entities (HI.4).

Device-scoped sensors, grouped by what user-facing question they answer:

Global (hub device):
    QueueDepthSensor             — count of pending + working jobs.

Per managed target:
    TargetScheduleSensor         — human-readable cron/one-shot schedule
                                    (#28). Replaces the old firmware
                                    version sensor — firmware version is
                                    already surfaced by HA's native
                                    ESPHome integration, so duplicating
                                    it here was confusing.
    TargetPinnedVersionSensor    — ESPHome version the next compile
                                    will use for this target, or
                                    "Auto (server default)" when no pin.

Per build worker:
    WorkerActiveJobsSensor       — count of WORKING queue entries
                                    assigned to this worker.
    WorkerDiskUsageSensor        — disk utilization % (#29).
    WorkerCpuUsageSensor         — CPU utilization % (#29).
    WorkerDiskFreeSensor         — free disk space, pre-formatted (#29).
    WorkerCpuCoresSensor         — CPU core count (#29).
    WorkerMemorySensor           — total memory, pre-formatted (#29).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE
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
    async_add_entities(
        [QueueDepthSensor(coordinator, entry.entry_id, coordinator.base_url)]
    )

    seen_targets: set[str] = set()
    seen_workers: set[str] = set()

    def _discover() -> None:
        new: list[SensorEntity] = []

        for t in (coordinator.data or {}).get("targets") or []:
            filename = t.get("target")
            if filename and filename not in seen_targets:
                seen_targets.add(filename)
                new.append(
                    TargetScheduleSensor(coordinator, entry.entry_id, filename)
                )
                new.append(
                    TargetPinnedVersionSensor(coordinator, entry.entry_id, filename)
                )

        for w in (coordinator.data or {}).get("workers") or []:
            client_id = w.get("client_id")
            if client_id and client_id not in seen_workers:
                seen_workers.add(client_id)
                new.append(
                    WorkerActiveJobsSensor(coordinator, entry.entry_id, client_id)
                )
                new.append(
                    WorkerDiskUsageSensor(coordinator, entry.entry_id, client_id)
                )
                new.append(
                    WorkerCpuUsageSensor(coordinator, entry.entry_id, client_id)
                )
                new.append(
                    WorkerDiskFreeSensor(coordinator, entry.entry_id, client_id)
                )
                new.append(
                    WorkerCpuCoresSensor(coordinator, entry.entry_id, client_id)
                )
                new.append(
                    WorkerMemorySensor(coordinator, entry.entry_id, client_id)
                )

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

    def __init__(
        self, coordinator: EsphomeFleetCoordinator, entry_id: str, base_url: str
    ) -> None:
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


class _TargetSensorBase(CoordinatorEntity[EsphomeFleetCoordinator], SensorEntity):
    """Shared target-scoping boilerplate."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: EsphomeFleetCoordinator,
        entry_id: str,
        target_filename: str,
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._target_filename = target_filename
        self._attr_unique_id = f"{entry_id}_target_{target_filename}_{unique_suffix}"

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


class TargetScheduleSensor(_TargetSensorBase):
    """Human-readable schedule for the next automatic compile (#28)."""

    _attr_name = "Schedule"
    _attr_icon = "mdi:calendar-clock"

    def __init__(
        self, coordinator: EsphomeFleetCoordinator, entry_id: str, target_filename: str
    ) -> None:
        super().__init__(coordinator, entry_id, target_filename, "schedule")

    @property
    def native_value(self) -> str | None:
        t = self._target or {}
        once = t.get("schedule_once")
        if once:
            return f"Once: {once}"
        cron = t.get("schedule")
        enabled = t.get("schedule_enabled")
        if cron and enabled:
            tz = t.get("schedule_tz")
            return f"{cron} ({tz})" if tz else str(cron)
        if cron and not enabled:
            return "Paused"
        return "No schedule"


class TargetPinnedVersionSensor(_TargetSensorBase):
    """ESPHome version pin for this target (#28).

    Reports the pinned version string, or "Auto" when no pin is set.
    Useful for dashboards that want to flag targets stuck on old
    releases.
    """

    _attr_name = "Pinned ESPHome version"
    _attr_icon = "mdi:pin"

    def __init__(
        self, coordinator: EsphomeFleetCoordinator, entry_id: str, target_filename: str
    ) -> None:
        super().__init__(coordinator, entry_id, target_filename, "pinned_version")

    @property
    def native_value(self) -> str:
        t = self._target or {}
        return str(t.get("pinned_version") or "Auto")


class _WorkerSensorBase(CoordinatorEntity[EsphomeFleetCoordinator], SensorEntity):
    """Shared worker-scoping boilerplate."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: EsphomeFleetCoordinator,
        entry_id: str,
        client_id: str,
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._client_id = client_id
        self._attr_unique_id = f"{entry_id}_worker_{client_id}_{unique_suffix}"

    @property
    def _worker(self) -> dict[str, Any] | None:
        for w in (self.coordinator.data or {}).get("workers") or []:
            if w.get("client_id") == self._client_id:
                return w
        return None

    @property
    def _system_info(self) -> dict[str, Any]:
        return (self._worker or {}).get("system_info") or {}

    @property
    def available(self) -> bool:
        return super().available and self._worker is not None

    @property
    def device_info(self):
        w = self._worker or {"client_id": self._client_id}
        return worker_device_info(w, self._entry_id)


class WorkerActiveJobsSensor(_WorkerSensorBase):
    """Count of WORKING jobs assigned to the worker."""

    _attr_name = "Active jobs"
    _attr_icon = "mdi:wrench-cog"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "jobs"

    def __init__(
        self, coordinator: EsphomeFleetCoordinator, entry_id: str, client_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, client_id, "active_jobs")

    @property
    def native_value(self) -> int:
        queue = (self.coordinator.data or {}).get("queue") or []
        return sum(
            1
            for j in queue
            if j.get("state") == "working"
            and j.get("assigned_client_id") == self._client_id
        )


class WorkerDiskUsageSensor(_WorkerSensorBase):
    """Disk utilization % reported by the worker (#29)."""

    _attr_name = "Disk usage"
    _attr_icon = "mdi:harddisk"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0

    def __init__(
        self, coordinator: EsphomeFleetCoordinator, entry_id: str, client_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, client_id, "disk_usage")

    @property
    def native_value(self) -> float | None:
        pct = self._system_info.get("disk_used_pct")
        try:
            return float(pct) if pct is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None


class WorkerCpuCoresSensor(_WorkerSensorBase):
    """CPU core count reported by the worker (#29)."""

    _attr_name = "CPU cores"
    _attr_icon = "mdi:cpu-64-bit"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "cores"

    def __init__(
        self, coordinator: EsphomeFleetCoordinator, entry_id: str, client_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, client_id, "cpu_cores")

    @property
    def native_value(self) -> int | None:
        cores = self._system_info.get("cpu_cores")
        try:
            return int(cores) if cores is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None


class WorkerCpuUsageSensor(_WorkerSensorBase):
    """CPU utilization % reported by the worker (#29)."""

    _attr_name = "CPU usage"
    _attr_icon = "mdi:gauge"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0

    def __init__(
        self, coordinator: EsphomeFleetCoordinator, entry_id: str, client_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, client_id, "cpu_usage")

    @property
    def native_value(self) -> float | None:
        pct = self._system_info.get("cpu_usage")
        try:
            return float(pct) if pct is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None


class WorkerDiskFreeSensor(_WorkerSensorBase):
    """Free disk space on the worker's build volume (#29).

    The client ships this as a pre-formatted string (e.g. ``"350 GB"``),
    so we expose it as a plain text sensor — no unit, no state class.
    Matches what the UI's Workers tab shows.
    """

    _attr_name = "Disk free"
    _attr_icon = "mdi:harddisk-plus"

    def __init__(
        self, coordinator: EsphomeFleetCoordinator, entry_id: str, client_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, client_id, "disk_free")

    @property
    def native_value(self) -> str | None:
        value = self._system_info.get("disk_free")
        return str(value) if value else None

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None


class WorkerMemorySensor(_WorkerSensorBase):
    """Total memory reported by the worker (#29).

    Pre-formatted string sensor — see :class:`WorkerDiskFreeSensor`.
    """

    _attr_name = "Memory"
    _attr_icon = "mdi:memory"

    def __init__(
        self, coordinator: EsphomeFleetCoordinator, entry_id: str, client_id: str
    ) -> None:
        super().__init__(coordinator, entry_id, client_id, "memory")

    @property
    def native_value(self) -> str | None:
        value = self._system_info.get("total_memory")
        return str(value) if value else None

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None
