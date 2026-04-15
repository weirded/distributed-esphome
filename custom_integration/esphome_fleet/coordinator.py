"""DataUpdateCoordinator for ESPHome Fleet (HI.10).

Polls the add-on's /ui/api/* endpoints and exposes a merged snapshot to
entities, services, and automations. Keeping the coordinator thin: one
HTTP call per endpoint per tick, no derived state — entities compute
whatever they need from `data`.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_POLL_INTERVAL_SECONDS, DOMAIN

_LOGGER = logging.getLogger(__name__)


class EsphomeFleetCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the add-on and caches the result for entities/services."""

    def __init__(self, hass: HomeAssistant, base_url: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL_SECONDS),
        )
        self._base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession = async_get_clientsession(hass)

    @property
    def base_url(self) -> str:
        return self._base_url

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the latest snapshot from the add-on.

        Four independent GETs run sequentially — the UI does them in
        parallel via SWR, but HA's DataUpdateCoordinator is happy with
        anything under a second and the add-on runs on the same host.
        """
        try:
            info = await self._get_json("/ui/api/server-info")
            targets = await self._get_json("/ui/api/targets")
            devices = await self._get_json("/ui/api/devices")
            workers = await self._get_json("/ui/api/workers")
            queue = await self._get_json("/ui/api/queue")
            versions = await self._get_json("/ui/api/esphome-versions")
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Couldn't reach add-on at {self._base_url}: {err}") from err

        return {
            "server_info": info,
            "targets": targets or [],
            "devices": devices or [],
            "workers": workers or [],
            "queue": queue or [],
            "esphome_versions": versions or {"selected": None, "available": []},
        }

    async def _get_json(self, path: str) -> Any:
        url = f"{self._base_url}{path}"
        async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def async_post_json(self, path: str, payload: dict[str, Any]) -> Any:
        """POST helper used by services (HI.2)."""
        url = f"{self._base_url}{path}"
        async with self._session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            resp.raise_for_status()
            if resp.content_type == "application/json":
                return await resp.json()
            return None
