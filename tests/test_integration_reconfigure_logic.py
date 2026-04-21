"""QS.5 (1.6.1) — logic tests for the reconfigure config flow.

Reconfigure lets users edit the add-on URL + token from the
integration card's Configure button instead of removing and re-adding
the integration. Pre-QS.5 the only way to rotate either value was
delete → re-add, which loses the integration's device/entity
registry entries and wipes any HA automations that referenced them.

Mocks HA's config-entries API at the boundary (no real hass fixture
needed) so the test pins the step's decisions: URL validation, token
required, cannot_connect on probe failure, successful commit path.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


_REPO_ROOT = Path(__file__).parent.parent
_INT_SRC = _REPO_ROOT / "ha-addon" / "custom_integration" / "esphome_fleet"
_INT_PARENT = _INT_SRC.parent
if str(_INT_PARENT) not in sys.path:
    sys.path.insert(0, str(_INT_PARENT))


def _make_flow(existing_url: str = "http://old.local:8765", existing_token: str = "old-token"):
    """Build an EsphomeFleetConfigFlow with just enough wiring to
    exercise the reconfigure step without a real HomeAssistant."""
    from esphome_fleet.config_flow import EsphomeFleetConfigFlow
    from esphome_fleet.const import CONF_BASE_URL, CONF_TOKEN

    flow = EsphomeFleetConfigFlow.__new__(EsphomeFleetConfigFlow)
    entry = SimpleNamespace(
        entry_id="entry-abc",
        data={CONF_BASE_URL: existing_url, CONF_TOKEN: existing_token},
    )
    flow._reconfigure_entry = entry

    # Mock hass.config_entries for the update+reload dance.
    hass = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_reload = AsyncMock()
    flow.hass = hass
    flow.context = {"entry_id": "entry-abc"}

    # Mimic HA's async_abort/async_show_form return shapes so the test
    # can inspect decisions without loading homeassistant.data_entry_flow.
    flow.async_abort = lambda *, reason: {"type": "abort", "reason": reason}
    flow.async_show_form = lambda **kw: {"type": "form", **kw}
    # HA 2024.11+ helper — return a sentinel the test can inspect.
    flow.async_update_reload_and_abort = AsyncMock(
        return_value={"type": "abort", "reason": "reconfigure_successful"},
    )
    return flow, entry, hass


async def test_reconfigure_rejects_invalid_url() -> None:
    from esphome_fleet.const import CONF_BASE_URL, CONF_TOKEN

    flow, _entry, _hass = _make_flow()
    result = await flow.async_step_reconfigure_confirm(
        {CONF_BASE_URL: "not-a-url", CONF_TOKEN: "new-token"},
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_url"


async def test_reconfigure_rejects_empty_token() -> None:
    from esphome_fleet.const import CONF_BASE_URL, CONF_TOKEN

    flow, _entry, _hass = _make_flow()
    result = await flow.async_step_reconfigure_confirm(
        {CONF_BASE_URL: "http://new.local:8765", CONF_TOKEN: "   "},
    )
    assert result["type"] == "form"
    assert result["errors"][CONF_TOKEN] == "token_required"


async def test_reconfigure_rejects_unreachable_server() -> None:
    from esphome_fleet.const import CONF_BASE_URL, CONF_TOKEN

    flow, _entry, _hass = _make_flow()
    with patch(
        "esphome_fleet.config_flow._probe_server",
        new=AsyncMock(return_value=False),
    ):
        result = await flow.async_step_reconfigure_confirm(
            {CONF_BASE_URL: "http://new.local:8765", CONF_TOKEN: "new-token"},
        )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "cannot_connect"


async def test_reconfigure_commits_and_reloads_on_success() -> None:
    """Happy path via the HA 2024.11+ helper."""
    from esphome_fleet.const import CONF_BASE_URL, CONF_TOKEN

    flow, entry, _hass = _make_flow()
    with patch(
        "esphome_fleet.config_flow._probe_server",
        new=AsyncMock(return_value=True),
    ):
        result = await flow.async_step_reconfigure_confirm(
            {CONF_BASE_URL: "http://new.local:8765", CONF_TOKEN: "new-token"},
        )
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    # Helper was called with the merged data dict.
    flow.async_update_reload_and_abort.assert_awaited_once()
    _, kwargs = flow.async_update_reload_and_abort.call_args
    assert kwargs["data"][CONF_BASE_URL] == "http://new.local:8765"
    assert kwargs["data"][CONF_TOKEN] == "new-token"


async def test_reconfigure_aborts_on_missing_entry() -> None:
    """PR #80 review: defensive abort when the flow reaches
    ``async_step_reconfigure_confirm`` without a cached entry (e.g.
    HA dispatches ``reconfigure_confirm`` directly without going
    through ``async_step_reconfigure`` first). Previously this raised
    ``AssertionError``; now it returns a clean abort keyed
    ``reconfigure_unknown_entry`` so HA renders the translated error.
    """
    from esphome_fleet.config_flow import EsphomeFleetConfigFlow

    flow = EsphomeFleetConfigFlow.__new__(EsphomeFleetConfigFlow)
    flow._reconfigure_entry = None
    flow.async_abort = lambda *, reason: {"type": "abort", "reason": reason}

    result = await flow.async_step_reconfigure_confirm(None)
    assert result == {"type": "abort", "reason": "reconfigure_unknown_entry"}


async def test_reconfigure_initial_render_shows_existing_url() -> None:
    """First paint (no user_input) renders the form with the current
    URL pre-filled so the user doesn't have to retype it for a
    token-only edit."""
    flow, _entry, _hass = _make_flow(existing_url="http://current.local:8765")
    result = await flow.async_step_reconfigure_confirm(None)
    assert result["type"] == "form"
    assert result["description_placeholders"]["url"] == "http://current.local:8765"
