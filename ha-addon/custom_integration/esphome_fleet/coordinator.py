"""DataUpdateCoordinator for ESPHome Fleet (HI.10).

Polls the add-on's /ui/api/* endpoints and exposes a merged snapshot to
entities, services, and automations. Keeping the coordinator thin: one
HTTP call per endpoint per tick, no derived state — entities compute
whatever they need from `data`.

HI.6: also tracks per-job state so we can fire
`esphome_fleet_compile_complete` HA events when a job transitions to a
terminal state. Events are fired on the HA bus so automations can
trigger off "compile failed" etc.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_POLL_INTERVAL_SECONDS, DOMAIN

_LOGGER = logging.getLogger(__name__)

EVENT_COMPILE_COMPLETE = f"{DOMAIN}_compile_complete"

_TERMINAL_JOB_STATES = {"success", "failed", "timed_out", "cancelled"}


class EsphomeFleetCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the add-on and caches the result for entities/services."""

    def __init__(
        self,
        hass: HomeAssistant,
        base_url: str,
        token: str | None = None,
        entry: ConfigEntry | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL_SECONDS),
        )
        # #73: hold the config entry so we can trigger
        # `async_start_reauth` from the coordinator when the add-on
        # rejects us with 401 (e.g. the user rotated `token` in the
        # add-on options, or the entry pre-dates AU.7 and has no token).
        self._entry = entry
        self._base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession = async_get_clientsession(hass)
        # AU.7: server accepts this as a system Bearer for /ui/api/*
        # calls since 1.5.0, so we stop relying on the add-on having
        # `require_ha_auth=false`. Falls back to no Authorization header
        # when the config entry pre-dates AU.7 (entry migration path).
        self._token = token
        # HI.6: per-job last-seen state, for terminal-transition detection.
        self._last_job_states: dict[str, str] = {}

    @property
    def base_url(self) -> str:
        return self._base_url

    def _auth_headers(self) -> dict[str, str]:
        """AU.7: Authorization header for every call when we have a token."""
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the latest snapshot from the add-on.

        CR.13: the six GETs are independent, so `asyncio.gather` them —
        cuts wall time on each tick to roughly 1× RTT (instead of 6×)
        and halves the server-side handler pressure. Add-on runs on
        localhost, so the win is small in absolute terms, but it's a
        trivial change with no downside.
        """
        try:
            info, targets, devices, workers, queue, versions = await asyncio.gather(
                self._get_json("/ui/api/server-info"),
                self._get_json("/ui/api/targets"),
                self._get_json("/ui/api/devices"),
                self._get_json("/ui/api/workers"),
                self._get_json("/ui/api/queue"),
                self._get_json("/ui/api/esphome-versions"),
            )
        except aiohttp.ClientResponseError as err:
            if err.status == 401:
                # #73: bubble a ConfigEntryAuthFailed so HA prompts the
                # user to re-enter the token via the reauth flow. Common
                # causes: entry pre-dates AU.7 (no CONF_TOKEN), or the
                # user rotated the add-on token.
                raise ConfigEntryAuthFailed(
                    "Add-on rejected the request with 401 — re-enter the "
                    "token from the add-on's Configuration tab"
                ) from err
            raise UpdateFailed(
                f"Add-on returned HTTP {err.status} at {self._base_url}: {err.message}"
            ) from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Couldn't reach add-on at {self._base_url}: {err}") from err

        data = {
            "server_info": info,
            "targets": targets or [],
            "devices": devices or [],
            "workers": workers or [],
            "queue": queue or [],
            "esphome_versions": versions or {"selected": None, "available": []},
        }
        # HI.6: fire events for any job that crossed into a terminal
        # state since the last poll.
        self._fire_terminal_events(data["queue"])
        return data

    def _fire_terminal_events(self, queue: list[dict[str, Any]]) -> None:
        """Compare queue against last-poll state, fire events on transitions."""
        current_ids: set[str] = set()
        for job in queue:
            job_id = job.get("id")
            state = job.get("state")
            if not job_id or not state:
                continue
            current_ids.add(job_id)

            previous = self._last_job_states.get(job_id)
            self._last_job_states[job_id] = state

            if previous is None:
                # First time we've seen this job — don't fire an event
                # even if it's already terminal (could be a startup
                # snapshot showing last night's failed compiles).
                continue
            if previous == state:
                continue
            if state not in _TERMINAL_JOB_STATES:
                continue
            if previous in _TERMINAL_JOB_STATES:
                # Already terminal; ignore subsequent metadata-only
                # changes (e.g. log field appearing after finish).
                continue

            event_data = {
                "job_id": job_id,
                "target": job.get("target"),
                "state": state,
                "duration_seconds": job.get("duration_seconds"),
                "esphome_version": job.get("esphome_version"),
                "worker_hostname": job.get("assigned_hostname"),
                "worker_id": job.get("assigned_client_id"),
                "scheduled": bool(job.get("scheduled")),
                "schedule_kind": job.get("schedule_kind"),
            }
            self.hass.bus.async_fire(EVENT_COMPILE_COMPLETE, event_data)
            _LOGGER.debug(
                "Fired %s event for job %s: %s → %s",
                EVENT_COMPILE_COMPLETE, job_id, previous, state,
            )

        # Drop tracking for jobs that disappeared from the queue so the
        # dict doesn't grow unbounded across long uptimes.
        for stale_id in set(self._last_job_states) - current_ids:
            self._last_job_states.pop(stale_id, None)

    async def _get_json(self, path: str) -> Any:
        url = f"{self._base_url}{path}"
        async with self._session.get(
            url,
            headers=self._auth_headers(),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def async_post_json(self, path: str, payload: dict[str, Any]) -> Any:
        """POST helper used by services (HI.2)."""
        url = f"{self._base_url}{path}"
        async with self._session.post(
            url,
            json=payload,
            headers=self._auth_headers(),
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()
            if resp.content_type == "application/json":
                return await resp.json()
            return None
