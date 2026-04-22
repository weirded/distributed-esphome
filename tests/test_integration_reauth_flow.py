"""HT.11 — real-flow test for ``async_step_reauth``.

Exercises ``config_flow.async_step_reauth`` +
``async_step_reauth_confirm`` through a real ``hass`` fixture.
Sibling to ``test_integration_reconfigure_flow.py`` — same rationale
(the logic-only tests against ``SimpleNamespace`` stand-ins can't catch
the ``AssertionError`` / ``KeyError`` shapes TR.6 is closing).

Specifically pins the TR.6 closure:
  - ``self.context["entry_id"]`` → ``.get()`` + clean abort on missing.
  - ``assert self._reauth_entry is not None`` → ``async_abort(reason=
    "reauth_unknown_entry")`` with a translated string.
"""

from __future__ import annotations

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
    """Register a fully-loaded config entry so reauth has a target."""
    from custom_components.esphome_fleet.const import DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"base_url": "http://test-addon.local:8765", "token": "stale-token"},
        title="Fleet — reauth test",
        unique_id="http://test-addon.local:8765",
    )
    entry.add_to_hass(hass)
    with mock_network():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_reauth_form_shows_current_url(hass):
    """Opening the reauth flow on an existing entry renders the form
    with the URL the user is re-authenticating against."""
    from homeassistant.data_entry_flow import FlowResultType

    from custom_components.esphome_fleet.const import DOMAIN

    entry = await _add_loaded_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    # Description placeholders surface the URL so the user can confirm
    # they're re-authenticating the right entry.
    assert result["description_placeholders"]["url"] == "http://test-addon.local:8765"


async def test_reauth_valid_token_updates_entry(hass):
    """Submitting a fresh token aborts with ``reauth_successful`` and
    writes the new token to the entry's data."""
    from homeassistant.data_entry_flow import FlowResultType

    from custom_components.esphome_fleet.const import DOMAIN

    entry = await _add_loaded_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
    )
    with mock_network():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"token": "fresh-token"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["token"] == "fresh-token"
    # URL stays untouched — reauth is token-only.
    assert entry.data["base_url"] == "http://test-addon.local:8765"


async def test_reauth_empty_token_returns_form_error(hass):
    """Submitting an empty token keeps the user on the form with a
    ``token_required`` error; entry data is untouched."""
    from homeassistant.data_entry_flow import FlowResultType

    from custom_components.esphome_fleet.const import DOMAIN

    entry = await _add_loaded_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"token": "   "},  # whitespace-only → normalises to empty
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"token": "token_required"}
    assert entry.data["token"] == "stale-token"


async def test_reauth_unknown_entry_id_aborts_cleanly(hass):
    """TR.6 closure: ``entry_id`` in context refers to an entry that
    doesn't exist (stale dispatch, entry deleted mid-flow) → clean
    abort with ``reauth_unknown_entry``, not ``AssertionError``.

    Before TR.6, ``assert self._reauth_entry is not None`` at
    config_flow.py:124 would fire as ``AssertionError`` and surface
    to the user as a nasty "Unexpected error" in the flow panel.
    """
    from homeassistant.data_entry_flow import FlowResultType

    from custom_components.esphome_fleet.const import DOMAIN

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": "does-not-exist"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_unknown_entry"


# Note — TR.6 also swaps bracket access ``self.context["entry_id"]``
# for ``.get()``. Same belt-and-suspenders shape as TR.3.2 for
# reconfigure; HA 2025.1+ enforces ``entry_id`` presence on reauth
# dispatches via its own machinery, so the missing-entry-id path
# isn't reachable through ``flow.async_init`` and doesn't get its own
# test. The defensive ``.get()`` stays in the code for future-HA
# robustness.
