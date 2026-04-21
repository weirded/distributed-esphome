"""QS.3 — System Health integration for ESPHome Fleet.

Surfaces add-on reachability, ESPHome version, worker count, and queue
depth on HA's *System Health* panel (Settings → System → Repairs &
Information → System Information → ESPHome Fleet).

Why this matters: when something's wrong with the fleet, users
typically go to the integration's device page first, not the add-on
log. A single glance at System Health tells the support channel
"coordinator OK, 2 workers online, 3 jobs queued" without needing to
walk the coordinator snapshot JSON.

Registration is via the standard HA hook (``async_register``) — the
integration's ``__init__.py`` already dispatches to platform modules
at setup, and HA calls this module's registration function at system-
health-init time independently.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .const import CONF_BASE_URL, DOMAIN


@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration,
) -> None:
    """Register ESPHome Fleet in the System Health panel."""
    register.async_register_info(_system_health_info)


async def _system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Return a compact dict of live fleet state for the panel.

    Shape — every value renders as a row in the Info card:

    ```
    Add-on URL:       http://...
    Connection:       ok / failed
    ESPHome version:  2026.4.0
    Workers online:   2 / 3
    Queue depth:      3 (1 working)
    Last poll:        30 seconds ago
    ```
    """
    coordinators = hass.data.get(DOMAIN, {})
    if not coordinators:
        return {"status": "integration not configured"}

    # Grab the first (and currently only) coordinator — the integration
    # is marked ``single_config_entry: true`` in manifest.json so this
    # is safe.
    coordinator = next(iter(coordinators.values()))

    data = coordinator.data or {}
    server_info = data.get("server_info") or data.get("info") or {}
    workers = data.get("workers") or []
    queue = data.get("queue") or []
    versions = data.get("esphome_versions") or data.get("versions") or {}

    online_workers = sum(1 for w in workers if w.get("online"))
    working_jobs = sum(1 for j in queue if j.get("state") == "working")

    # The coordinator holds the entry under ``_entry`` (set in
    # coordinator.py's __init__). Fall back to the config-entries
    # registry if that attribute is ever removed — same value, we
    # just don't have to reach into private state.
    entry = getattr(coordinator, "_entry", None)
    if entry is None:
        entries = hass.config_entries.async_entries(DOMAIN)
        entry = entries[0] if entries else None
    base_url = entry.data.get(CONF_BASE_URL) if entry is not None else None

    info: dict[str, Any] = {
        "add_on_url": system_health.async_check_can_reach_url(hass, base_url)
        if base_url else "unknown",
        "last_update_success": "ok" if coordinator.last_update_success else "failed",
        "esphome_version": versions.get("selected") or "unknown",
        "add_on_version": server_info.get("addon_version") or "unknown",
        "workers": f"{online_workers} online / {len(workers)} total",
        "queue_depth": f"{len(queue)} ({working_jobs} working)",
    }
    return info
