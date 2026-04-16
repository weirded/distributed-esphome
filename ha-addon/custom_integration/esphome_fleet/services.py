"""ESPHome Fleet HA services (HI.2).

Three services, all thin wrappers over the add-on's `/ui/api/*` JSON API:

  esphome_fleet.compile    — enqueue a compile for one or more targets.
                             Supports HA device-targeting (#37) so users
                             can pick devices from the UI picker instead
                             of typing YAML filenames.
  esphome_fleet.cancel     — cancel a queued/working job by id.
  esphome_fleet.validate   — run esphome config validation on a target.

All three are registered globally per-hass (not per-entry) so the
automation editor picks them up immediately.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_COMPILE = "compile"
SERVICE_CANCEL = "cancel"
SERVICE_VALIDATE = "validate"

_TARGETS_SCHEMA = vol.Any(
    vol.All(cv.ensure_list, [cv.string]),
    vol.In(["all", "outdated"]),
)

# #53: HA injects the target-resolved ``device_id`` / ``entity_id`` /
# ``area_id`` keys (even as ``None`` when the user didn't use a target).
# voluptuous rejects them without explicit declarations, producing the
# user-visible "extra keys not allowed" error. Declare them as optional
# so the schema accepts both device-targeted and explicit-list calls.
_TARGET_KEYS = {
    vol.Optional("device_id"): vol.Any(None, cv.string, [cv.string]),
    vol.Optional("entity_id"): vol.Any(None, cv.string, [cv.string]),
    vol.Optional("area_id"): vol.Any(None, cv.string, [cv.string]),
    vol.Optional("floor_id"): vol.Any(None, cv.string, [cv.string]),
    vol.Optional("label_id"): vol.Any(None, cv.string, [cv.string]),
}

COMPILE_SCHEMA = vol.Schema(
    {
        vol.Optional("targets"): _TARGETS_SCHEMA,
        vol.Optional("esphome_version"): cv.string,
        vol.Optional("worker_id"): cv.string,
        **_TARGET_KEYS,
    }
)

CANCEL_SCHEMA = vol.Schema(
    {
        vol.Required("job_ids"): vol.All(cv.ensure_list, [cv.string]),
    }
)

VALIDATE_SCHEMA = vol.Schema(
    {
        vol.Optional("target"): cv.string,
        **_TARGET_KEYS,
    }
)


def _first_coordinator(hass: HomeAssistant):
    """Return the first configured coordinator (services are global)."""
    coordinators = list(hass.data.get(DOMAIN, {}).values())
    if not coordinators:
        raise HomeAssistantError(
            "No ESPHome Fleet config entry configured — "
            "add the integration first via Settings → Devices & Services"
        )
    return coordinators[0]


def _resolve_device_ids(
    hass: HomeAssistant, device_ids: list[str]
) -> tuple[list[str], list[str]]:
    """Split HA device-registry IDs into (targets, worker_client_ids).

    Each Fleet target device has an identifier of the form
    ``("esphome_fleet", "target:<filename>")``; worker devices use
    ``("esphome_fleet", "worker:<client_id>")``. #63: let users pick
    EITHER from the same device picker — targets go into the
    compile list, workers become the ``pinned_client_id``.
    """
    targets: list[str] = []
    workers: list[str] = []
    if not device_ids:
        return targets, workers
    registry = dr.async_get(hass)
    for did in device_ids:
        device = registry.async_get(did)
        if device is None:
            continue
        for domain, ident in device.identifiers:
            if domain != DOMAIN:
                continue
            if ident.startswith("target:"):
                targets.append(ident.removeprefix("target:"))
                break
            if ident.startswith("worker:"):
                workers.append(ident.removeprefix("worker:"))
                break
    return targets, workers


def _resolve_device_ids_to_targets(
    hass: HomeAssistant, device_ids: list[str]
) -> list[str]:
    """Back-compat wrapper for tests. Returns only the targets portion."""
    targets, _ = _resolve_device_ids(hass, device_ids)
    return targets


async def _handle_compile(call: ServiceCall) -> None:
    coord = _first_coordinator(call.hass)

    # #37/#63: resolve device-targeted calls. The user picks devices
    # from HA's device picker; target devices become the compile list,
    # worker devices become the pinned_client_id. Mixing both works.
    device_ids: list[str] = call.data.get("device_id", [])
    if isinstance(device_ids, str):
        device_ids = [device_ids]

    picked_targets, picked_workers = _resolve_device_ids(call.hass, device_ids)

    # Detect "picked device(s), but none are targets or workers"
    # (e.g. only the hub) BEFORE falling through to the no-device path.
    if device_ids and not picked_targets and not picked_workers:
        raise HomeAssistantError(
            "None of the selected devices are managed ESPHome Fleet "
            "targets or workers"
        )

    targets: Any
    if picked_targets:
        targets = picked_targets
    elif "targets" in call.data:
        targets = call.data["targets"]
    elif picked_workers:
        # #63: user picked ONLY worker devices — ambiguous without
        # targets. Fall through to "all" so the pin-to-worker intent
        # still works, and document it.
        targets = "all"
    else:
        raise HomeAssistantError(
            "Select at least one device or provide a 'targets' list"
        )

    payload: dict[str, Any] = {"targets": targets}
    if (version := call.data.get("esphome_version")):
        payload["esphome_version"] = version
    # Pin order: explicit worker_id > picked worker device(s, first wins).
    if (worker := call.data.get("worker_id")):
        payload["pinned_client_id"] = worker
    elif picked_workers:
        payload["pinned_client_id"] = picked_workers[0]
    result = await coord.async_post_json("/ui/api/compile", payload)
    enqueued = (result or {}).get("enqueued", 0)
    _LOGGER.info("esphome_fleet.compile enqueued %s job(s) for %r", enqueued, targets)


async def _handle_cancel(call: ServiceCall) -> None:
    coord = _first_coordinator(call.hass)
    job_ids = call.data["job_ids"]
    result = await coord.async_post_json("/ui/api/cancel", {"job_ids": job_ids})
    cancelled = (result or {}).get("cancelled", 0)
    _LOGGER.info("esphome_fleet.cancel cancelled %s of %s job(s)", cancelled, len(job_ids))


async def _handle_validate(call: ServiceCall) -> None:
    coord = _first_coordinator(call.hass)

    # #37: resolve device-targeted validate calls the same way.
    device_ids: list[str] = call.data.get("device_id", [])
    if isinstance(device_ids, str):
        device_ids = [device_ids]

    if device_ids:
        targets = _resolve_device_ids_to_targets(call.hass, device_ids)
        if not targets:
            raise HomeAssistantError(
                "None of the selected devices are managed ESPHome Fleet targets"
            )
        target = targets[0]
    elif "target" in call.data:
        target = call.data["target"]
    else:
        raise HomeAssistantError(
            "Select a device or provide a 'target' filename"
        )

    result = await coord.async_post_json("/ui/api/validate", {"target": target})
    job_id = (result or {}).get("job_id")
    _LOGGER.info("esphome_fleet.validate started for %s (job_id=%s)", target, job_id)


def async_register_services(hass: HomeAssistant) -> None:
    """Register services on first config-entry setup (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_COMPILE):
        return

    hass.services.async_register(DOMAIN, SERVICE_COMPILE, _handle_compile, schema=COMPILE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CANCEL, _handle_cancel, schema=CANCEL_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_VALIDATE, _handle_validate, schema=VALIDATE_SCHEMA)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister services when the last config entry is removed."""
    if hass.data.get(DOMAIN):
        return
    for service in (SERVICE_COMPILE, SERVICE_CANCEL, SERVICE_VALIDATE):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
