"""Regression tests for main.py background tasks and startup behaviour.

Issue #25: UI didn't load on HAOS with 1.3.0 because:
  1. ha_entity_poller never set first_poll=False on error, causing an
     immediate tight-retry loop instead of sleeping 30 s between attempts.
  2. on_startup blocked on the HA Supervisor API (up to 15 s of timeouts),
     delaying the web server from accepting connections.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# ha_entity_poller – tight-retry regression
# ---------------------------------------------------------------------------

async def test_ha_entity_poller_sleeps_after_first_failure():
    """ha_entity_poller must sleep 30 s between retries even when the first
    poll fails with an exception (regression for issue #25)."""
    from main import ha_entity_poller

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        # Stop the loop after the first sleep so the test terminates quickly.
        raise asyncio.CancelledError

    app: dict = {"ha_entity_status": {}, "ha_mac_set": set()}

    with (
        patch("os.environ.get", return_value="fake-token"),
        patch("aiohttp.ClientSession") as mock_session_cls,
        patch("asyncio.sleep", side_effect=fake_sleep),
    ):
        # Make the ClientSession raise an exception to simulate a failed poll.
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_session

        with pytest.raises(asyncio.CancelledError):
            await ha_entity_poller(app)  # type: ignore[arg-type]

    # The key assertion: asyncio.sleep(30) MUST have been called after the
    # first failed attempt.  Before the fix, first_poll stayed True so the
    # sleep was skipped and the poller spun in a tight loop.
    assert sleep_calls, "asyncio.sleep was never called — poller is in a tight retry loop"
    assert sleep_calls[0] == 30, f"Expected sleep(30) after failure, got sleep({sleep_calls[0]})"


async def test_ha_entity_poller_sleeps_after_continue_on_non200():
    """ha_entity_poller must sleep 30 s even when a non-200 status causes the
    inner loop to `continue` (another path that previously kept first_poll=True)."""
    from main import ha_entity_poller

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise asyncio.CancelledError

    # Simulate: template API works, states API returns 403 → triggers `continue`
    async def fake_get(*args, **kwargs):
        resp = AsyncMock()
        resp.status = 403
        resp.text = AsyncMock(return_value="Forbidden")
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        return resp

    async def fake_post(*args, **kwargs):
        resp = AsyncMock()
        resp.status = 200
        resp.text = AsyncMock(return_value="[]")
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        return resp

    app: dict = {"ha_entity_status": {}, "ha_mac_set": set()}

    with (
        patch("os.environ.get", return_value="fake-token"),
        patch("asyncio.sleep", side_effect=fake_sleep),
    ):
        mock_session = MagicMock()
        mock_session.get = fake_get
        mock_session.post = fake_post
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(asyncio.CancelledError):
                await ha_entity_poller(app)  # type: ignore[arg-type]

    assert sleep_calls, "asyncio.sleep was never called after non-200 states response"
    assert sleep_calls[0] == 30


# ---------------------------------------------------------------------------
# pypi_version_refresher – runs immediately on first iteration
# ---------------------------------------------------------------------------

async def test_pypi_version_refresher_does_not_sleep_on_first_run():
    """pypi_version_refresher must NOT sleep before its first iteration so that
    version detection happens promptly after startup (the Supervisor API check
    was moved out of on_startup in the same fix)."""
    from main import pypi_version_refresher

    sleep_calls: list[float] = []
    session_created = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        # Terminate after first sleep so the test is quick.
        raise asyncio.CancelledError

    app: dict = {
        "esphome_detected_version": None,
        "esphome_available_versions": [],
        "esphome_versions_fetched_at": 0.0,
    }

    with (
        patch("main._fetch_ha_esphome_version", new_callable=AsyncMock, return_value=None),
        patch("main._fetch_pypi_versions", new_callable=AsyncMock, return_value=[]),
        patch("aiohttp.ClientSession") as mock_session_cls,
        patch("asyncio.sleep", side_effect=fake_sleep),
    ):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.side_effect = lambda: (session_created.append(True), mock_session)[1]

        with pytest.raises(asyncio.CancelledError):
            await pypi_version_refresher(app)  # type: ignore[arg-type]

    # The session must have been created BEFORE any sleep (first run is immediate).
    assert session_created, "version refresher never called the Supervisor API on first run"
    # The first sleep should come AFTER the first run, not before.
    assert sleep_calls, "version refresher never slept — subsequent runs would spin"
    assert sleep_calls[0] == 30


# ---------------------------------------------------------------------------
# on_startup – does not call _fetch_ha_esphome_version synchronously
# ---------------------------------------------------------------------------

async def test_on_startup_does_not_block_on_supervisor_api(tmp_path):
    """on_startup must not call _fetch_ha_esphome_version (regression for issue
    #25 where the blocking Supervisor API calls prevented the server from
    accepting connections for up to 15 s after restart)."""
    import main as main_module
    from main import create_app

    supervisor_api_calls: list[str] = []

    async def tracking_fetch_ha_version(session):  # noqa: ANN001
        supervisor_api_calls.append("called")
        return None

    config_dir = tmp_path / "esphome"
    config_dir.mkdir()

    with (
        patch.dict(
            "os.environ",
            {"ESPHOME_CONFIG_DIR": str(config_dir), "PORT": "18765", "SERVER_TOKEN": "test"},
        ),
        patch.object(main_module, "_fetch_ha_esphome_version", tracking_fetch_ha_version),
        patch.object(main_module, "_fetch_pypi_versions", new_callable=AsyncMock, return_value=[]),
        # Prevent real background tasks from running
        patch("asyncio.create_task", return_value=MagicMock()),
        patch("main.DevicePoller") as mock_poller_cls,
    ):
        mock_poller = AsyncMock()
        mock_poller.start = AsyncMock()
        mock_poller.update_compile_targets = MagicMock()
        mock_poller_cls.return_value = mock_poller

        app = create_app()
        # Manually fire on_startup (simulates aiohttp's startup sequence)
        for hook in app.on_startup:
            await hook(app)

    assert not supervisor_api_calls, (
        "on_startup called _fetch_ha_esphome_version — this blocks startup for "
        "up to 15 s when the HA Supervisor API is slow or unreachable"
    )
