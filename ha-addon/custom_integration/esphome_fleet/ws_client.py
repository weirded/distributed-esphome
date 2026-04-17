"""Real-time event WebSocket client (#41).

Opens a long-lived WebSocket to the add-on's ``/ui/api/ws/events``
endpoint and triggers ``coordinator.async_request_refresh()`` on every
incoming message. Reconnects with exponential backoff when the
connection drops (add-on restart, network blip, HA resume-from-sleep).

The 30 s coordinator poll stays enabled as a safety net — a missed
event just adds up to 30 s of latency on one update rather than
stalling state forever.
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .coordinator import EsphomeFleetCoordinator

_LOGGER = logging.getLogger(__name__)

# Reconnect backoff — doubles on each failure up to _MAX_BACKOFF.
_INITIAL_BACKOFF = 2.0
_MAX_BACKOFF = 60.0


class EventStreamClient:
    """Owns the event-stream WebSocket for one config entry."""

    def __init__(
        self, hass: HomeAssistant, coordinator: EsphomeFleetCoordinator
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._session: aiohttp.ClientSession = async_get_clientsession(hass)
        self._task: asyncio.Task | None = None
        self._stopped = False

    def start(self) -> None:
        """Spawn the background connect-loop task."""
        if self._task is not None:
            return
        self._task = self._hass.async_create_background_task(
            self._run(), name="esphome_fleet_event_stream"
        )

    async def stop(self) -> None:
        """Cancel the background task and close the WebSocket."""
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _run(self) -> None:
        """Reconnect loop. Runs until ``stop()`` is called."""
        backoff = _INITIAL_BACKOFF
        url = f"{self._coordinator.base_url.rstrip('/')}/ui/api/ws/events"
        # AU.7: carry the same Bearer the coordinator uses for HTTP polls
        # so `/ui/api/ws/events` survives `require_ha_auth=true`. The
        # coordinator exposes `_auth_headers()` for exactly this case.
        headers = self._coordinator._auth_headers() or None
        while not self._stopped:
            try:
                _LOGGER.debug("event stream: connecting to %s", url)
                async with self._session.ws_connect(
                    url,
                    heartbeat=30.0,
                    timeout=aiohttp.ClientWSTimeout(ws_close=10.0),
                    headers=headers,
                ) as ws:
                    _LOGGER.info("event stream: connected to %s", url)
                    backoff = _INITIAL_BACKOFF
                    # Refresh once on (re)connect so HA catches up on
                    # anything that changed while we were disconnected.
                    await self._coordinator.async_request_refresh()
                    async for msg in ws:
                        if self._stopped:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_message(msg.json())
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSING,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOGGER.debug(
                    "event stream: %s — reconnecting in %.0fs",
                    exc, backoff,
                )

            if self._stopped:
                return
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                raise
            backoff = min(backoff * 2, _MAX_BACKOFF)

    async def _handle_message(self, message: dict) -> None:
        """Trigger a coordinator refresh on any state-change event."""
        event_type = message.get("type")
        if event_type == "hello":
            return  # initial handshake, no action needed
        _LOGGER.debug("event stream: %s — triggering refresh", event_type)
        await self._coordinator.async_request_refresh()
