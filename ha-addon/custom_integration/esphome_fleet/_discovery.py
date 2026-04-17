"""Shared helper: determine whether an entity already exists in HA's registry.

Why this matters (#62): each platform's ``async_setup_entry`` used to
keep an in-memory ``seen_workers`` / ``seen_targets`` set to avoid
double-adding entities on coordinator updates. That worked fine on
first setup, but broke whenever the stale-device cleanup (#39) removed
a worker or target that had briefly vanished from the coordinator
snapshot — the closure's ``seen_*`` set still contained that
``client_id`` / filename, so ``_discover`` saw it on the next refresh
and skipped recreation. Result: device re-appeared in HA's registry
but with zero entities (visible in #62 on hass-4 where 6 of 7 worker
devices had no entities after the SE workstream restart churn).

Fix: replace the closure set with a registry-backed check. If the
unique_id is already registered in HA, skip; if not (either truly new
or previously removed), add. Idempotent across add/remove cycles.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN


def entity_already_registered(
    hass: HomeAssistant, platform: str, unique_id: str
) -> bool:
    """Return True if HA has an entity with *unique_id* for this integration."""
    registry = er.async_get(hass)
    return registry.async_get_entity_id(platform, DOMAIN, unique_id) is not None
