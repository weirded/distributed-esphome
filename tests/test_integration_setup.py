"""Real-HA integration tests — exercises `async_setup_entry` + `async_unload_entry`
through a true ``hass`` fixture.

Complements the mock-based ``test_integration_*_logic.py`` suite (which
tests helper functions in isolation). The `_logic` tests happily pass
even when ``async_setup_entry`` leaks listeners, sets up platforms
twice, or forgets to register cleanup in ``async_on_unload`` — the
CR.12 class of bugs that shipped in 1.5 despite full unit-test
coverage. Running the lifecycle against a real hass instance catches
those.

Requires ``pytest-homeassistant-custom-component`` — installed into the
isolated ``.ha-testenv`` venv (pinned in ``.github/workflows/ci.yml``;
kept out of the main env because its autouse ``pytest_socket`` +
``verify_cleanup`` fixtures break every server/client test that opens a
loopback listener). PY-10 invariant enforces the plugin import so the
filename without ``_logic`` suffix stays honest.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

# pytest-homeassistant-custom-component provides hass fixture + MockConfigEntry.
# Imported at module top so PY-10's invariant check passes.
import pytest_homeassistant_custom_component  # noqa: F401

from pytest_homeassistant_custom_component.common import MockConfigEntry

# Shared fixtures for every real-hass integration test file.
# ``_warm_pycares_shutdown_thread`` + ``_install_integration_in_hass_config``
# are both autouse — importing them here is enough for pytest to pick them up.
from _integration_test_fixtures import (  # noqa: F401
    _install_integration_in_hass_config,
    _warm_pycares_shutdown_thread,
    mock_network,
)


async def test_async_setup_entry_happy_path(hass):
    """Integration sets up cleanly against a real hass + tears down cleanly.

    Pins that:
      - ``hass.data[DOMAIN]`` ends up populated on setup.
      - ``async_unload_entry`` returns True, signaling clean teardown.
      - No leftover listeners after unload (HA complains loudly if there are).
    """
    from custom_components.esphome_fleet.const import DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"base_url": "http://test-addon.local:8765", "token": "test-token"},
        title="Fleet — lifecycle test",
    )
    entry.add_to_hass(hass)

    with mock_network():
        ok = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert ok is True
        assert DOMAIN in hass.data
        assert entry.entry_id in hass.data[DOMAIN]

        unloaded = await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert unloaded is True
        assert entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_async_setup_recovers_after_first_poll_failure(hass):
    """Coordinator's first poll fails → entry lands in SETUP_RETRY → recovers.

    HT.1 invariant: ``async_setup_entry`` does not crash on first-poll
    failure and the config entry transitions cleanly back to LOADED
    when the next attempt succeeds.

    Shape of the failure we care about: ``_async_update_data`` raises
    ``UpdateFailed`` (the poll-layer exception the real coordinator
    raises when the add-on is unreachable or returns a transport
    error), which ``DataUpdateCoordinator.async_config_entry_first_refresh``
    translates into ``ConfigEntryNotReady``. HA marks the entry
    SETUP_RETRY and schedules a retry.
    """
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers.update_coordinator import UpdateFailed

    from custom_components.esphome_fleet.const import DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"base_url": "http://test-addon.local:8765", "token": "test-token"},
        title="Fleet — retry test",
    )
    entry.add_to_hass(hass)

    # First attempt: poll raises UpdateFailed → setup bails with
    # ConfigEntryNotReady; HA returns False from async_setup.
    with patch(
        "custom_components.esphome_fleet.coordinator.EsphomeFleetCoordinator._async_update_data",
        new_callable=AsyncMock,
        side_effect=UpdateFailed("simulated add-on unreachable"),
    ), patch(
        "custom_components.esphome_fleet.ws_client.EventStreamClient._run",
        new_callable=AsyncMock,
    ):
        ok = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert ok is False
        assert entry.state is ConfigEntryState.SETUP_RETRY

    # Recovery: on the next attempt the poll returns clean data.
    # Reload the entry directly — equivalent to HA's internal retry
    # firing on its backoff schedule; we're testing the recovery path,
    # not HA's scheduler.
    with mock_network():
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.entry_id in hass.data.get(DOMAIN, {})

    with mock_network():
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_async_setup_then_reload(hass):
    """Reload cycle: setup → unload → setup again on the same entry.

    Catches the class of bugs where ``async_setup_entry`` forgets to
    clean up a module-level service / listener on unload, so the
    second setup fires "already registered" errors. CR.12 was exactly
    this shape for the service registration path.
    """
    from custom_components.esphome_fleet.const import DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"base_url": "http://test-addon.local:8765", "token": "test-token"},
        title="Fleet — reload test",
    )
    entry.add_to_hass(hass)

    with mock_network():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        # Second setup must succeed — if cleanup was incomplete the
        # coordinator / service registration / listener would complain.
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
