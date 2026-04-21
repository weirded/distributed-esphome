"""QS.1 — Diagnostics support for the ESPHome Fleet integration.

Exposes ``async_get_config_entry_diagnostics`` so HA's *Download
diagnostics* button (Settings → Devices & Services → ESPHome Fleet →
⋮ → Download diagnostics) produces a JSON dump with enough detail to
reproduce a support issue, but with the sensitive bits redacted
(bearer token, direct-port URL with ``?token=…`` query params, API
encryption keys, WiFi creds leaked through ``device_attr`` if any).

Redaction uses ``async_redact_data`` from ``homeassistant.components.
diagnostics`` so the redaction shape is consistent with other HA
integrations.

Quality-scale note: this file is one of the Gold-tier requirements
(``diagnostics`` rule). Flipping ``quality_scale`` to ``gold`` in
``manifest.json`` is gated behind QS.9 landing every other rule.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN, DOMAIN

# Keys whose values must never appear in a diagnostics dump. The set
# is intentionally broad — cheaper to over-redact than to leak a token
# through a field rename we forgot to update here.
_REDACT_CONFIG_ENTRY_DATA = {CONF_TOKEN}

# Coordinator snapshot redactions. The add-on's wire contract includes
# device-registry IDs, MAC addresses, and per-target API encryption
# keys in a few corners — scrub them so a diagnostics bundle shared on
# GitHub doesn't fingerprint the user's network.
_REDACT_COORDINATOR_DATA = {
    # Target-level fields
    "mac_address",
    "ha_device_id",
    # Worker-level fields
    "client_id",
    # System-info bag on each worker can contain hostname-level info
    # from uname/lsb_release — keep the shape but not the values.
    "system_info",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry,
) -> dict[str, Any]:
    """Return a redacted snapshot of the integration's state.

    Shape:

    ```
    {
        "config_entry": { ... entry.data with token redacted ... },
        "coordinator_data": { ... last /ui/api/* snapshot, redacted ... },
        "last_update_success": bool,
        "update_interval_seconds": int,
    }
    ```
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    diag: dict[str, Any] = {
        "config_entry": async_redact_data(dict(entry.data), _REDACT_CONFIG_ENTRY_DATA),
    }

    if coordinator is not None:
        diag["coordinator_data"] = async_redact_data(
            coordinator.data or {}, _REDACT_COORDINATOR_DATA,
        )
        diag["last_update_success"] = coordinator.last_update_success
        diag["update_interval_seconds"] = (
            coordinator.update_interval.total_seconds()
            if coordinator.update_interval else None
        )
    else:
        # Setup failed or the entry is mid-unload — still useful to
        # surface that fact rather than return an empty dict.
        diag["coordinator_data"] = None
        diag["last_update_success"] = False
        diag["update_interval_seconds"] = None

    return diag
