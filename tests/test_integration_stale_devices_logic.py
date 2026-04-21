"""QS.6 — logic test for the stale-device cleanup in the coordinator.

``_prune_stale_devices`` runs off every coordinator tick and removes
HA device-registry entries for targets/workers that have disappeared
from the server's snapshot. The hub device is always kept, and we
only remove devices the integration owns — identifiers merged in by
the native ESPHome integration (via MAC) are left alone.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


_REPO_ROOT = Path(__file__).parent.parent
_INT_SRC = _REPO_ROOT / "ha-addon" / "custom_integration" / "esphome_fleet"
_INT_PARENT = _INT_SRC.parent
if str(_INT_PARENT) not in sys.path:
    sys.path.insert(0, str(_INT_PARENT))


def _make_device(
    id_: str,
    identifiers: set,
    config_entries: set[str] | None = None,
) -> MagicMock:
    dev = MagicMock()
    dev.id = id_
    dev.identifiers = identifiers
    # Default to the single-owner case. Tests that need the shared-device
    # path set this to >1 entries explicitly.
    dev.config_entries = config_entries if config_entries is not None else {"entry-42"}
    return dev


def _build_coordinator(entry_id: str = "entry-42"):
    """Instantiate just enough of the coordinator to exercise
    _prune_stale_devices without hitting the real HA fixture."""
    from esphome_fleet.coordinator import EsphomeFleetCoordinator

    coord = EsphomeFleetCoordinator.__new__(EsphomeFleetCoordinator)
    # logger — pulled from base class via _LOGGER at module level.
    coord.logger = logging.getLogger("esphome_fleet")  # type: ignore[attr-defined]
    coord.hass = SimpleNamespace()
    coord._entry = SimpleNamespace(entry_id=entry_id)
    return coord


def test_prune_removes_gone_target() -> None:
    """Target removed from the server → its device-registry row goes."""
    from esphome_fleet.const import DOMAIN

    coord = _build_coordinator("entry-42")

    # Registry has three devices: the hub, one target that's still in
    # the snapshot, and one that's been removed.
    reg = MagicMock()
    hub = _make_device("hub-row", {(DOMAIN, "hub:entry-42")})
    live = _make_device("live-row", {(DOMAIN, "target:alive.yaml")})
    gone = _make_device("gone-row", {(DOMAIN, "target:gone.yaml")})
    with (
        patch("homeassistant.helpers.device_registry.async_get", return_value=reg),
        patch(
            "homeassistant.helpers.device_registry.async_entries_for_config_entry",
            return_value=[hub, live, gone],
        ),
    ):
        coord._prune_stale_devices(
            targets=[{"target": "alive.yaml"}],
            workers=[],
        )

    reg.async_remove_device.assert_called_once_with("gone-row")


def test_prune_keeps_merged_devices() -> None:
    """When another integration merged its own identifier onto one of
    our target rows, we must detach via ``remove_config_entry_id`` —
    calling ``async_remove_device`` would yank the shared row out from
    under the other integration's entities. Matches the setup-time
    prune behavior in ``__init__.py``."""
    from esphome_fleet.const import DOMAIN

    coord = _build_coordinator("entry-42")

    # A device owned by us (stale target) but also carrying the native
    # ESPHome integration's config entry. In practice this shape comes
    # from our ``connections={CONNECTION_NETWORK_MAC,…}`` on target
    # DeviceInfo — if HA has merged by MAC, the native ESPHome entry
    # attaches its config_entry_id here too.
    reg = MagicMock()
    merged = _make_device(
        "merged-row",
        {
            (DOMAIN, "target:gone.yaml"),
            ("esphome", "aabbccddeeff"),
        },
        config_entries={"entry-42", "native-esphome-entry"},
    )
    with (
        patch("homeassistant.helpers.device_registry.async_get", return_value=reg),
        patch(
            "homeassistant.helpers.device_registry.async_entries_for_config_entry",
            return_value=[merged],
        ),
    ):
        coord._prune_stale_devices(targets=[], workers=[])

    # Must NOT remove the whole device row — that would take the native
    # ESPHome integration's entities with it. Detach our config entry
    # instead so the row survives with just the non-Fleet owner.
    reg.async_remove_device.assert_not_called()
    reg.async_update_device.assert_called_once_with(
        "merged-row", remove_config_entry_id="entry-42",
    )


def test_prune_keeps_live_workers() -> None:
    """Workers that are still registered must survive the prune."""
    from esphome_fleet.const import DOMAIN

    coord = _build_coordinator("entry-42")
    reg = MagicMock()
    hub = _make_device("hub-row", {(DOMAIN, "hub:entry-42")})
    worker_live = _make_device("w-live", {(DOMAIN, "worker:client-1")})
    worker_gone = _make_device("w-gone", {(DOMAIN, "worker:client-old")})

    with (
        patch("homeassistant.helpers.device_registry.async_get", return_value=reg),
        patch(
            "homeassistant.helpers.device_registry.async_entries_for_config_entry",
            return_value=[hub, worker_live, worker_gone],
        ),
    ):
        coord._prune_stale_devices(
            targets=[],
            workers=[{"client_id": "client-1"}],
        )

    reg.async_remove_device.assert_called_once_with("w-gone")


def test_prune_no_op_without_entry() -> None:
    """Coordinator set up without an entry (test harness) → no-op; must not crash."""
    coord = _build_coordinator()
    coord._entry = None
    # No patches needed — the early-return before any device-registry
    # lookup is the invariant we're pinning.
    coord._prune_stale_devices(targets=[], workers=[])
