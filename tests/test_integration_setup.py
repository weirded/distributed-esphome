"""IT.2 — first real-HA integration test using pytest-homeassistant-custom-component.

Complements the mock-based ``test_integration_*_logic.py`` suite (which
tests helper functions in isolation) with a true-lifecycle test that
exercises ``async_setup_entry`` + ``async_unload_entry`` through a
real ``hass`` fixture.

Why this matters: the ``_logic`` tests happily pass even when
``async_setup_entry`` leaks listeners, sets up platforms twice, or
forgets to register cleanup in ``async_on_unload`` — the CR.12 class
of bugs that shipped in 1.5 despite full unit-test coverage. Running
the lifecycle against a real hass instance catches those.

Requires: ``pytest-homeassistant-custom-component`` in the ``.ha-testenv``
venv (pinned in ``.github/workflows/ci.yml``'s install step). PY-10
invariant enforces the plugin import so this file's filename without
``_logic`` suffix stays honest.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# pytest-homeassistant-custom-component provides hass fixture + MockConfigEntry.
# Imported at module top so PY-10's invariant check passes.
import pytest_homeassistant_custom_component  # noqa: F401

from pytest_homeassistant_custom_component.common import MockConfigEntry


# Make the custom integration importable the same way HA would.
# pytest-homeassistant-custom-component expects the integration on the
# import path as a top-level ``esphome_fleet`` module — the package is
# at ``ha-addon/custom_integration/esphome_fleet``.
_INT_ROOT = Path(__file__).parent.parent / "ha-addon" / "custom_integration"
if str(_INT_ROOT) not in sys.path:
    sys.path.insert(0, str(_INT_ROOT))


# Fixture enabling custom components for pytest-homeassistant-custom-component.
# Applied to every test in this module via autouse=True so we don't need to
# remember to parametrise each one.
@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):  # noqa: F811
    yield


# A minimal coordinator snapshot shape — only the keys the platforms
# read during setup. If platforms start reading new fields at setup
# time, expand this fixture; it's intentionally hand-rolled so the
# test pins what setup touches.
_MOCK_COORDINATOR_DATA: dict[str, Any] = {
    "info": {
        "addon_version": "1.6.0-test",
        "min_image_version": "5",
    },
    "targets": [],
    "devices": [],
    "workers": [],
    "queue": [],
    "versions": {"selected": "2026.4.0", "detected": "2026.4.0", "available": ["2026.4.0"]},
}


async def test_async_setup_entry_happy_path(hass):
    """Integration sets up cleanly against a real hass + tears down cleanly.

    Pins that:
      - ``hass.data[DOMAIN]`` ends up populated on setup.
      - ``async_unload_entry`` returns True, signaling clean teardown.
      - No leftover listeners after unload (HA complains loudly if there are).
    """
    from esphome_fleet.const import DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"base_url": "http://test-addon.local:8765", "token": "test-token"},
        title="Fleet — lifecycle test",
    )
    entry.add_to_hass(hass)

    # Intercept the one network-touching call so setup doesn't try to
    # hit a real addon. Everything else in async_setup_entry is local.
    with patch(
        "esphome_fleet.coordinator.EsphomeFleetCoordinator._async_update_data",
        new_callable=AsyncMock,
        return_value=_MOCK_COORDINATOR_DATA,
    ):
        ok = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert ok is True
    assert DOMAIN in hass.data
    assert entry.entry_id in hass.data[DOMAIN]

    # Unload — must also return True + leave hass.data[DOMAIN] empty
    # of this entry so a second setup (reauth, reload) can succeed.
    unloaded = await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert unloaded is True
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_async_setup_then_reload(hass):
    """Reload cycle: setup → unload → setup again on the same entry.

    Catches the class of bugs where async_setup_entry forgets to clean
    up a module-level service / listener on unload, so the second setup
    fires "already registered" errors. CR.12 was exactly this shape
    for the service registration path.
    """
    from esphome_fleet.const import DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"base_url": "http://test-addon.local:8765", "token": "test-token"},
        title="Fleet — reload test",
    )
    entry.add_to_hass(hass)

    with patch(
        "esphome_fleet.coordinator.EsphomeFleetCoordinator._async_update_data",
        new_callable=AsyncMock,
        return_value=_MOCK_COORDINATOR_DATA,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        # Second setup must succeed — if cleanup was incomplete the
        # coordinator / service registration / listener would complain.
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        # And the second unload must be just as clean as the first.
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
