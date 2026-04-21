"""QS.1 — logic test for the custom-integration diagnostics dumper.

Exercises ``async_get_config_entry_diagnostics`` against a mock
ConfigEntry + coordinator so the redaction contract is pinned without
standing up a full ``hass`` fixture. The "no_logic" integration tests
(test_integration_setup.py) cover the lifecycle; this one covers the
narrow "what lands in the JSON dump" invariant that a user hitting
*Download diagnostics* on a support thread depends on.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


_REPO_ROOT = Path(__file__).parent.parent
_INT_SRC = _REPO_ROOT / "ha-addon" / "custom_integration" / "esphome_fleet"
_INT_PARENT = _INT_SRC.parent
if str(_INT_PARENT) not in sys.path:
    sys.path.insert(0, str(_INT_PARENT))


@pytest.fixture
def _mock_hass():
    """Minimal hass stand-in: just a ``data`` dict the diagnostics
    function uses to locate the coordinator."""
    return SimpleNamespace(data={})


@pytest.fixture
def _mock_entry():
    """ConfigEntry stub carrying the two CONF_* fields the integration
    stores: base URL + bearer token."""
    from esphome_fleet.const import CONF_BASE_URL, CONF_TOKEN

    return SimpleNamespace(
        entry_id="test-entry-1",
        data={
            CONF_BASE_URL: "http://supervisor/addons/local_esphome_dist_server/api",
            CONF_TOKEN: "super-secret-token-abc123",
        },
    )


async def test_diagnostics_redacts_token(_mock_hass, _mock_entry) -> None:
    """The bearer token must never appear in the diagnostics output."""
    from esphome_fleet.const import DOMAIN
    from esphome_fleet.diagnostics import async_get_config_entry_diagnostics

    _mock_hass.data[DOMAIN] = {}
    diag = await async_get_config_entry_diagnostics(_mock_hass, _mock_entry)

    flat = repr(diag)
    assert "super-secret-token-abc123" not in flat
    assert "REDACTED" in flat or "**REDACTED**" in flat


async def test_diagnostics_redacts_target_macs_and_worker_ids(_mock_hass, _mock_entry) -> None:
    """MAC addresses + client IDs get scrubbed — they fingerprint the
    user's network and show up in every coordinator snapshot."""
    from esphome_fleet.const import DOMAIN
    from esphome_fleet.diagnostics import async_get_config_entry_diagnostics

    coordinator = SimpleNamespace(
        data={
            "targets": [
                {"target": "bedroom.yaml", "mac_address": "aa:bb:cc:dd:ee:ff", "ha_device_id": "device-42"},
            ],
            "workers": [
                {"hostname": "build-pi", "client_id": "abc-xyz-123"},
            ],
            "queue": [],
        },
        last_update_success=True,
        update_interval=SimpleNamespace(total_seconds=lambda: 30.0),
    )
    _mock_hass.data[DOMAIN] = {_mock_entry.entry_id: coordinator}

    diag = await async_get_config_entry_diagnostics(_mock_hass, _mock_entry)
    flat = repr(diag)

    assert "aa:bb:cc:dd:ee:ff" not in flat
    assert "abc-xyz-123" not in flat
    assert "device-42" not in flat
    # Non-sensitive fields survive.
    assert "bedroom.yaml" in flat
    assert "build-pi" in flat


async def test_diagnostics_surfaces_coordinator_absent(_mock_hass, _mock_entry) -> None:
    """Setup failure or mid-unload: the coordinator isn't in ``hass.data``,
    but the diagnostics call must still return a shape the support
    reader can use."""
    from esphome_fleet.diagnostics import async_get_config_entry_diagnostics

    diag = await async_get_config_entry_diagnostics(_mock_hass, _mock_entry)

    assert diag["coordinator_data"] is None
    assert diag["last_update_success"] is False
    assert diag["update_interval_seconds"] is None


async def test_diagnostics_reports_update_interval_seconds(_mock_hass, _mock_entry) -> None:
    """Coordinator interval is surfaced so a support reader can tell
    whether the user tuned it away from the default."""
    from esphome_fleet.const import DOMAIN
    from esphome_fleet.diagnostics import async_get_config_entry_diagnostics

    coordinator = SimpleNamespace(
        data={"targets": [], "workers": [], "queue": []},
        last_update_success=True,
        update_interval=SimpleNamespace(total_seconds=lambda: 60.0),
    )
    _mock_hass.data[DOMAIN] = {_mock_entry.entry_id: coordinator}

    diag = await async_get_config_entry_diagnostics(_mock_hass, _mock_entry)

    assert diag["update_interval_seconds"] == 60.0
    assert diag["last_update_success"] is True
