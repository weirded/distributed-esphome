"""HT.7 — real-flow test for ``async_step_reconfigure``.

Exercises ``config_flow.async_step_reconfigure`` +
``async_step_reconfigure_confirm`` through
``hass.config_entries.flow.async_init`` with a real ``hass`` fixture.

Why a real-flow test (beyond ``test_integration_reconfigure_logic.py``):
the logic-only tests drive the step methods directly against
``SimpleNamespace``-shaped stand-ins for ``self.hass`` / ``self.context``,
so the three bugs TR.3 closed (dead fallback branch, ``KeyError`` on
missing ``entry_id``, ``AssertionError`` on missing entry) were all
invisible to them. A real flow asserts the step responds correctly to
the exact shapes HA dispatches in prod: ``FlowResultType.FORM``,
``FlowResultType.ABORT`` with the right reason, and ``CREATE_ENTRY``
(for the legacy path, n/a here since reconfigure aborts with data
update via ``async_update_reload_and_abort``).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

# pytest-homeassistant-custom-component provides hass fixture +
# MockConfigEntry; imported at module top so PY-10's invariant check
# passes (the filename lacks ``_logic`` suffix so the plugin import is
# required).
import pytest_homeassistant_custom_component  # noqa: F401

from pytest_homeassistant_custom_component.common import MockConfigEntry

from _integration_test_fixtures import (  # noqa: F401
    _install_integration_in_hass_config,
    _warm_pycares_shutdown_thread,
    mock_network,
)


async def _add_loaded_entry(hass) -> MockConfigEntry:
    """Register a fully-loaded config entry so reconfigure has a target.

    Reconfigure aborts if the entry can't be found, and
    ``async_update_reload_and_abort`` reloads the entry — so we need
    the entry actually set up, not just registered. Uses
    ``mock_network`` to keep the setup from touching HTTP.
    """
    from custom_components.esphome_fleet.const import DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"base_url": "http://test-addon.local:8765", "token": "original-token"},
        title="Fleet — reconfigure test",
        unique_id="http://test-addon.local:8765",
    )
    entry.add_to_hass(hass)
    with mock_network():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_reconfigure_form_shows_current_url(hass):
    """Opening Reconfigure on an existing entry renders the form with the
    current URL pre-filled — not an empty form."""
    from homeassistant.data_entry_flow import FlowResultType

    from custom_components.esphome_fleet.const import DOMAIN

    entry = await _add_loaded_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure_confirm"
    # Description placeholders include the current URL so the form copy
    # can say "currently pointing at {url}".
    assert result["description_placeholders"]["url"] == "http://test-addon.local:8765"


async def test_reconfigure_valid_input_updates_entry(hass):
    """Submitting a new valid URL + token + reachable server aborts with
    ``reconfigure_successful`` and updates the entry's data.

    ``_probe_server`` is patched to True because we don't want the test
    to depend on the new URL actually being reachable; the production
    code path (network probe before entry update) is already covered by
    ``test_integration_reconfigure_logic.py``.
    """
    from homeassistant.data_entry_flow import FlowResultType

    from custom_components.esphome_fleet.const import DOMAIN

    entry = await _add_loaded_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    with patch(
        "custom_components.esphome_fleet.config_flow._probe_server",
        new_callable=AsyncMock,
        return_value=True,
    ), mock_network():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"base_url": "http://new-addon.local:8765", "token": "new-token"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["base_url"] == "http://new-addon.local:8765"
    assert entry.data["token"] == "new-token"


async def test_reconfigure_invalid_url_returns_form_error(hass):
    """Submitting a malformed URL keeps the user on the form with a
    base-level ``invalid_url`` error; entry data is untouched."""
    from homeassistant.data_entry_flow import FlowResultType

    from custom_components.esphome_fleet.const import DOMAIN

    entry = await _add_loaded_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"base_url": "not-a-url", "token": "new-token"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure_confirm"
    assert result["errors"] == {"base": "invalid_url"}
    # Original data remains.
    assert entry.data["base_url"] == "http://test-addon.local:8765"


async def test_reconfigure_unknown_entry_id_aborts_cleanly(hass):
    """TR.3 closure: ``entry_id`` in context refers to an entry that
    doesn't exist (stale dispatch, entry deleted mid-flow) → clean
    abort, not ``AssertionError``.

    The assert at ``async_step_reconfigure_confirm`` line 124 would
    have thrown before TR.3 landed. Guard against re-introduction.
    """
    from homeassistant.data_entry_flow import FlowResultType

    from custom_components.esphome_fleet.const import DOMAIN

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": "does-not-exist"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_unknown_entry"


# Note — TR.3.2 (``self.context.get("entry_id", "")`` instead of
# bracket access) is a belt-and-suspenders guard. HA 2025.1+'s
# ``flow.async_init`` itself rejects reconfigure-source dispatches
# without ``entry_id`` via ``report_usage`` — the step never runs.
# We can't simulate the "missing entry_id" path through the public
# flow machinery, so this case doesn't get a dedicated test. The
# defensive ``.get()`` stays in the code for future-HA robustness.
