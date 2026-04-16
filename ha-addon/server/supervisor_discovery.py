"""Register the add-on with Supervisor's /discovery endpoint (#26).

When the add-on starts under Supervisor, POSTing our hostname + port to
`http://supervisor/discovery` triggers Home Assistant's hassio discovery
flow, which our custom integration handles in its `async_step_hassio`.

The user never has to type a URL — they get a "Discovered" flow in the
HA notification tray that can be accepted with one click.

All failures are logged and swallowed: this is a nice-to-have that must
not prevent the add-on from starting. The manual + zeroconf config flow
paths remain as fallbacks.
"""

from __future__ import annotations

import logging
import os
import socket

import aiohttp

logger = logging.getLogger(__name__)

# The service name the integration registers for — must match
# `HassioServiceInfo.name` expected by `async_step_hassio`.
DISCOVERY_SERVICE = "esphome_fleet"
SUPERVISOR_URL = "http://supervisor"


async def register_discovery(port: int) -> str | None:
    """POST a discovery record to Supervisor. Returns the UUID on success.

    Returns None if we couldn't register (no token, Supervisor
    unreachable, non-2xx response). Never raises.
    """
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        logger.debug("No SUPERVISOR_TOKEN — skipping Supervisor discovery (#26)")
        return None

    # Supervisor routes to this host by its internal Docker name,
    # which matches the container hostname inside the add-on.
    host = socket.gethostname()
    payload = {
        "service": DISCOVERY_SERVICE,
        "config": {"host": host, "port": port, "ssl": False},
    }
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{SUPERVISOR_URL}/discovery",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    logger.info(
                        "Supervisor /discovery returned %s: %s — add-on "
                        "will still work, users can add the integration "
                        "manually",
                        resp.status, body[:200],
                    )
                    return None
                data = await resp.json()
                uuid = (data.get("data") or {}).get("uuid") or data.get("uuid")
                logger.info(
                    "Registered Supervisor discovery for %s on %s:%d (uuid=%s)",
                    DISCOVERY_SERVICE, host, port, uuid,
                )
                return uuid
    except Exception:
        logger.debug("Supervisor discovery registration failed", exc_info=True)
        return None


async def unregister_discovery(uuid: str) -> None:
    """Best-effort DELETE of a previously-registered discovery record."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token or not uuid:
        return
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(
                f"{SUPERVISOR_URL}/discovery/{uuid}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status >= 400:
                    logger.debug(
                        "Supervisor /discovery/%s DELETE returned %s",
                        uuid, resp.status,
                    )
    except Exception:
        logger.debug("Supervisor discovery unregister failed", exc_info=True)
