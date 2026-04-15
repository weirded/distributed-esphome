"""ESPHome Fleet HA services (HI.2).

Three services, all thin wrappers over the add-on's `/ui/api/*` JSON API:

  esphome_fleet.compile    — enqueue a compile for one or more targets
                             (or "all" / "outdated"). Optional worker
                             pin and ESPHome version override.
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
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_COMPILE = "compile"
SERVICE_CANCEL = "cancel"
SERVICE_VALIDATE = "validate"

# `targets`: explicit list, or the string "all" / "outdated".
_TARGETS_SCHEMA = vol.Any(
    vol.All(cv.ensure_list, [cv.string]),
    vol.In(["all", "outdated"]),
)

COMPILE_SCHEMA = vol.Schema(
    {
        vol.Required("targets"): _TARGETS_SCHEMA,
        vol.Optional("esphome_version"): cv.string,
        vol.Optional("worker_id"): cv.string,
    }
)

CANCEL_SCHEMA = vol.Schema(
    {
        vol.Required("job_ids"): vol.All(cv.ensure_list, [cv.string]),
    }
)

VALIDATE_SCHEMA = vol.Schema(
    {
        vol.Required("target"): cv.string,
    }
)


def _first_coordinator(hass: HomeAssistant):
    """Return the first configured coordinator (services are global).

    Most users will have exactly one add-on instance. If there are
    multiple config entries and the caller didn't target one, we hit
    the first — good enough for 1.4.1. Later we can add a
    `config_entry` service param if anyone asks.
    """
    coordinators = list(hass.data.get(DOMAIN, {}).values())
    if not coordinators:
        raise HomeAssistantError(
            "No ESPHome Fleet config entry configured — "
            "add the integration first via Settings → Devices & Services"
        )
    return coordinators[0]


async def _handle_compile(call: ServiceCall) -> None:
    coord = _first_coordinator(call.hass)
    targets = call.data["targets"]
    payload: dict[str, Any] = {"targets": targets}
    if (version := call.data.get("esphome_version")):
        payload["esphome_version"] = version
    if (worker := call.data.get("worker_id")):
        payload["pinned_client_id"] = worker
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
    target = call.data["target"]
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
        # Another entry is still active — keep services registered.
        return
    for service in (SERVICE_COMPILE, SERVICE_CANCEL, SERVICE_VALIDATE):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
