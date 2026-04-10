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


# ---------------------------------------------------------------------------
# _fetch_ha_esphome_version – add-on slug discovery (bug #4)
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status: int, payload: dict | None = None) -> None:
        self.status = status
        self._payload = payload or {}

    async def json(self) -> dict:
        return self._payload

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeSession:
    """Minimal aiohttp.ClientSession stand-in that replays scripted responses."""

    def __init__(self, routes: dict[str, _FakeResponse]) -> None:
        self._routes = routes
        self.calls: list[str] = []

    def get(self, url: str, headers=None, timeout=None):  # type: ignore[no-untyped-def]
        self.calls.append(url)
        if url in self._routes:
            return self._routes[url]
        return _FakeResponse(404)


async def test_fetch_ha_esphome_version_finds_hashed_slug(monkeypatch):
    """A user-hashed slug like ``a0d7b954_esphome`` must be discovered via
    /addons listing (regression for bug #4 — previously hardcoded to three
    well-known slugs and silently failed for custom installs)."""
    from main import _fetch_ha_esphome_version

    monkeypatch.setenv("SUPERVISOR_TOKEN", "fake-token")
    routes = {
        "http://supervisor/addons": _FakeResponse(200, {
            "data": {
                "addons": [
                    {"slug": "core_configurator", "name": "File editor", "version": "5.6.0"},
                    {"slug": "a0d7b954_esphome", "name": "ESPHome Device Builder", "version": "2026.3.3"},
                    {"slug": "core_mosquitto", "name": "Mosquitto broker", "version": "6.4.1"},
                ],
            },
        }),
    }
    session = _FakeSession(routes)

    version = await _fetch_ha_esphome_version(session)  # type: ignore[arg-type]
    assert version == "2026.3.3"
    # The listing alone was enough — no per-slug /info round-trip needed.
    assert session.calls == ["http://supervisor/addons"]


async def test_fetch_ha_esphome_version_returns_none_when_not_installed(monkeypatch):
    """ESPHome add-on not installed — returns None cleanly, no guessing."""
    from main import _fetch_ha_esphome_version

    monkeypatch.setenv("SUPERVISOR_TOKEN", "fake-token")
    routes = {
        "http://supervisor/addons": _FakeResponse(200, {
            "data": {
                "addons": [
                    {"slug": "core_mosquitto", "name": "Mosquitto broker", "version": "6.4.1"},
                ],
            },
        }),
    }
    session = _FakeSession(routes)

    version = await _fetch_ha_esphome_version(session)  # type: ignore[arg-type]
    assert version is None


async def test_fetch_ha_esphome_version_falls_back_to_info_probe_on_listing_403(monkeypatch):
    """When /addons returns 403 (the common case — we don't have
    hassio_role: manager), the per-slug /info probe over the known slug list
    must take over silently. Regression for bug introduced after the
    initial bug #4 fix: probing /addons-only spammed 403 every 30s and
    never recovered.
    """
    from main import _fetch_ha_esphome_version

    monkeypatch.setenv("SUPERVISOR_TOKEN", "fake-token")
    routes = {
        "http://supervisor/addons": _FakeResponse(403),
        "http://supervisor/addons/a0d7b954_esphome/info": _FakeResponse(
            200, {"data": {"version": "2026.4.0"}},
        ),
    }
    session = _FakeSession(routes)

    version = await _fetch_ha_esphome_version(session)  # type: ignore[arg-type]
    assert version == "2026.4.0"
    assert "http://supervisor/addons/a0d7b954_esphome/info" in session.calls


async def test_fetch_ha_esphome_version_probes_core_slug(monkeypatch):
    """Built-in core_esphome installs (no listing access) still resolve."""
    from main import _fetch_ha_esphome_version

    monkeypatch.setenv("SUPERVISOR_TOKEN", "fake-token")
    routes = {
        "http://supervisor/addons": _FakeResponse(403),
        "http://supervisor/addons/core_esphome/info": _FakeResponse(
            200, {"data": {"version": "2026.3.3"}},
        ),
    }
    session = _FakeSession(routes)
    version = await _fetch_ha_esphome_version(session)  # type: ignore[arg-type]
    assert version == "2026.3.3"


# ---------------------------------------------------------------------------
# ha_entity_poller – repeated-warning suppression (bug #5)
# ---------------------------------------------------------------------------

async def test_ha_entity_poller_demotes_repeated_warnings_to_debug(monkeypatch, caplog):
    """After the second identical failure in a row, the warning must drop to
    DEBUG so a persistent outage doesn't drown the log (bug #5).

    The first two failures log at WARNING (with a one-time "above warning is
    repeating" notice on the second), the third+ log at DEBUG, and a
    successful poll resets the suppression counter.
    """
    import logging
    from main import ha_entity_poller

    monkeypatch.setenv("SUPERVISOR_TOKEN", "fake-token")

    # Swap asyncio.sleep for a fake that lets us run exactly N iterations.
    iteration_count = {"n": 0}

    async def fake_sleep(_seconds: float) -> None:
        iteration_count["n"] += 1
        if iteration_count["n"] >= 5:
            raise asyncio.CancelledError()

    # Force every poll to fail identically by making aiohttp.ClientSession()
    # return a context manager whose get() always raises.
    class _AlwaysFailSession:
        async def __aenter__(self) -> "_AlwaysFailSession":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        def get(self, *a, **k):  # type: ignore[no-untyped-def]
            raise RuntimeError("simulated HA down")

        def post(self, *a, **k):  # type: ignore[no-untyped-def]
            raise RuntimeError("simulated HA down")

    app = {"ha_entity_status": {}, "ha_mac_set": set()}

    with patch("asyncio.sleep", side_effect=fake_sleep), \
         patch("aiohttp.ClientSession", return_value=_AlwaysFailSession()), \
         caplog.at_level(logging.DEBUG, logger="main"):
        try:
            await ha_entity_poller(app)  # type: ignore[arg-type]
        except asyncio.CancelledError:
            pass

    # Collect ha_entity_poller records by level
    main_records = [r for r in caplog.records if r.name == "main"]
    warnings = [r for r in main_records if r.levelno == logging.WARNING]
    debugs = [r for r in main_records if r.levelno == logging.DEBUG]

    # Each iteration emits two distinct fingerprints (``template_exception``
    # from the inner try and ``poll_exception`` from the outer except). Each
    # fingerprint is tracked independently: occurrences 1 and 2 log at
    # WARNING (with a one-time "repeating" notice on the second), and
    # occurrences 3+ drop to DEBUG.
    #
    # Over 5 iterations: 2 fingerprints × (2 warnings + 1 notice) = 6
    # warning records, and 2 × 3 = 6 suppressed-to-DEBUG records.
    warning_messages = [r.getMessage() for r in warnings]
    assert len(warnings) == 6, (
        f"expected 6 warning records, got {len(warnings)}: {warning_messages}"
    )
    repeating_notices = [m for m in warning_messages if "repeating" in m]
    assert len(repeating_notices) == 2, (
        f"expected 2 'repeating' notices (one per fingerprint), got: {repeating_notices}"
    )
    debug_messages = [r.getMessage() for r in debugs]
    assert any("Error polling" in m or "Template API" in m for m in debug_messages), (
        f"expected suppressed DEBUG records for the repeating failures, got: {debug_messages}"
    )
