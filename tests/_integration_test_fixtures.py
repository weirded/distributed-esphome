"""Shared fixtures + helpers for real-hass integration tests.

All non-``_logic`` ``test_integration_*.py`` files use these to boot a
pytest-homeassistant-custom-component ``hass`` fixture with
``esphome_fleet`` available as a custom integration. Pulled out of
``test_integration_setup.py`` so HT.7 (reconfigure flow), HT.11 (reauth
flow), and any future real-flow file can share the same plumbing
without copy-paste.

Only imported by files that transitively load ``homeassistant`` and
``pytest_homeassistant_custom_component`` — i.e. tests that the main
``pytest tests/`` run excludes via ``--ignore-glob='tests/test_integration_*.py'``
(see pytest.ini's comment on why the plugin's autouse fixtures can't
share an env with the server/client suite).
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


_REPO_ROOT = Path(__file__).parent.parent
_INT_SRC = _REPO_ROOT / "ha-addon" / "custom_integration" / "esphome_fleet"


# Minimal coordinator snapshot — just enough for `async_setup_entry`
# and the platforms to finish without poking real data. Expand as new
# setup-time reads surface.
MOCK_COORDINATOR_DATA: dict[str, Any] = {
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


@pytest.fixture(scope="session", autouse=True)
def _warm_pycares_shutdown_thread():
    """Prime pycares' singleton shutdown thread before any test runs.

    ``aiohttp``'s default ``AsyncResolver`` is backed by ``aiodns`` →
    ``pycares``. Whenever aiohttp closes a session that used the
    async resolver, the underlying pycares ``Channel`` is destroyed,
    and pycares spawns a **process-singleton** daemon thread named
    ``_run_safe_shutdown_loop`` the first time that happens. That
    thread is then alive for the lifetime of the interpreter.

    ``pytest-homeassistant-custom-component``'s ``verify_cleanup``
    fixture captures ``threading.enumerate()`` before each test and
    fails if a non-``_DummyThread`` / non-``waitpid-*`` thread appears
    after. Without warming, the pycares thread appears *during* the
    first test that exercises HA's shared aiohttp session → the test
    fails in teardown even though nothing is actually leaking.

    Warming once at session scope puts the thread in every test's
    ``threads_before`` baseline, so ``threads_after - threads_before``
    stays empty.
    """
    try:
        import aiodns  # noqa: PLC0415
    except ImportError:
        return
    resolver = aiodns.DNSResolver()
    # Destroying the channel is what kicks the shutdown-thread start;
    # pycares processes this via `_ChannelDestroyer.destroy_channel`,
    # which calls `self.start()` the first time through.
    del resolver


@pytest.fixture(autouse=True)
def _install_integration_in_hass_config(hass, enable_custom_integrations):  # noqa: F811
    """Expose ``esphome_fleet`` to HA's loader under the hass config dir.

    HA's custom-integration scanner searches ``hass.config.config_dir +
    /custom_components``; the ``hass`` fixture builds that dir per-test
    as a tmpdir. Our package lives at
    ``ha-addon/custom_integration/esphome_fleet`` so the add-on's
    Dockerfile can copy it to ``/config/custom_components/`` at
    runtime — we can't restructure without breaking prod. Instead:

    1. Symlink the package into the per-test config dir's
       ``custom_components/``.
    2. Clear the cached discovery (``DATA_CUSTOM_COMPONENTS``) so HA's
       loader re-scans and finds the freshly-linked integration.
    """
    from homeassistant.loader import DATA_CUSTOM_COMPONENTS

    cc_dir = Path(hass.config.config_dir) / "custom_components"
    cc_dir.mkdir(exist_ok=True)
    link = cc_dir / "esphome_fleet"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(_INT_SRC, target_is_directory=True)

    hass.data.pop(DATA_CUSTOM_COMPONENTS, None)
    yield


@contextlib.contextmanager
def mock_network():
    """Replace every network-touching call made during setup.

    - ``EsphomeFleetCoordinator._async_update_data`` — the poll loop.
      Patched to return a canned snapshot so no HTTP fires.
    - ``EventStreamClient._run`` — the WebSocket reconnect loop.
      Patched to a no-op so ``hass.async_create_background_task`` wraps
      a coroutine that completes immediately. Otherwise aiohttp resolves
      the configured host, spins up a pycares daemon thread, and the
      ``verify_cleanup`` fixture fails the test on a lingering thread.
    """
    with patch(
        "custom_components.esphome_fleet.coordinator.EsphomeFleetCoordinator._async_update_data",
        new_callable=AsyncMock,
        return_value=MOCK_COORDINATOR_DATA,
    ), patch(
        "custom_components.esphome_fleet.ws_client.EventStreamClient._run",
        new_callable=AsyncMock,
    ):
        yield
