"""QS.3 — logic test for the custom-integration System Health info.

Pins the shape of the System Health dict so the panel's rows stay
stable as the coordinator snapshot evolves — a renamed key in the
wire contract shouldn't silently break the card in HA's Settings.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


_REPO_ROOT = Path(__file__).parent.parent
_INT_SRC = _REPO_ROOT / "ha-addon" / "custom_integration" / "esphome_fleet"
_INT_PARENT = _INT_SRC.parent
if str(_INT_PARENT) not in sys.path:
    sys.path.insert(0, str(_INT_PARENT))


async def test_system_health_info_shape() -> None:
    """Standard coordinator snapshot → every expected row lands."""
    from esphome_fleet.const import CONF_BASE_URL, DOMAIN
    from esphome_fleet.system_health import _system_health_info

    coordinator = SimpleNamespace(
        data={
            "server_info": {"addon_version": "1.6.1-dev.13"},
            "workers": [
                {"client_id": "w1", "online": True},
                {"client_id": "w2", "online": True},
                {"client_id": "w3", "online": False},
            ],
            "queue": [
                {"id": "j1", "state": "working"},
                {"id": "j2", "state": "pending"},
            ],
            "esphome_versions": {"selected": "2026.4.0"},
        },
        last_update_success=True,
        _entry=SimpleNamespace(data={CONF_BASE_URL: "http://supervisor/local"}),
    )
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        config_entries=SimpleNamespace(async_entries=lambda _domain: []),
    )

    info = await _system_health_info(hass)

    assert info["last_update_success"] == "ok"
    assert info["esphome_version"] == "2026.4.0"
    assert info["add_on_version"] == "1.6.1-dev.13"
    assert info["workers"] == "2 online / 3 total"
    assert info["queue_depth"] == "2 (1 working)"


async def test_system_health_info_unconfigured() -> None:
    """Fresh HA with no entry configured → status row only."""
    from esphome_fleet.const import DOMAIN
    from esphome_fleet.system_health import _system_health_info

    hass = SimpleNamespace(data={DOMAIN: {}})
    info = await _system_health_info(hass)
    assert info == {"status": "integration not configured"}


async def test_system_health_info_last_update_failed() -> None:
    """Coordinator reporting a failure surfaces as 'failed' in the UI row."""
    from esphome_fleet.const import CONF_BASE_URL, DOMAIN
    from esphome_fleet.system_health import _system_health_info

    coordinator = SimpleNamespace(
        data={"server_info": {}, "workers": [], "queue": [], "esphome_versions": {}},
        last_update_success=False,
        _entry=SimpleNamespace(data={CONF_BASE_URL: "http://supervisor/local"}),
    )
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        config_entries=SimpleNamespace(async_entries=lambda _domain: []),
    )

    info = await _system_health_info(hass)
    assert info["last_update_success"] == "failed"
    assert info["workers"] == "0 online / 0 total"
    assert info["queue_depth"] == "0 (0 working)"
