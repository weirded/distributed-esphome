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


async def register_discovery(port: int, token: str | None = None) -> str | None:
    """POST a discovery record to Supervisor. Returns the UUID on success.

    Returns None if we couldn't register (no Supervisor token, Supervisor
    unreachable, non-2xx response). Never raises.

    AU.7: the optional ``token`` argument is the add-on's shared worker
    token. When supplied, it's advertised in the discovery payload so
    the integration's config flow can hand it to the coordinator for
    `Authorization: Bearer …` on every `/ui/api/*` call. Orthogonal to
    the SUPERVISOR_TOKEN env var we use to talk to Supervisor itself.
    """
    supervisor_token = os.environ.get("SUPERVISOR_TOKEN")
    if not supervisor_token:
        # SI (WORKITEMS-1.6.2): INFO (not DEBUG) so standalone operators
        # see a single, grep-able line explaining why HA didn't auto-
        # discover the custom integration. Previously silent at DEBUG
        # and operators had to read source to figure out the dependency.
        logger.info(
            "Skipping Supervisor auto-discovery (standalone mode — no SUPERVISOR_TOKEN). "
            "The HA custom integration can still be added manually."
        )
        return None

    # Supervisor routes to this host by its internal Docker name,
    # which matches the container hostname inside the add-on.
    host = socket.gethostname()
    config: dict[str, object] = {"host": host, "port": port, "ssl": False}
    if token:
        config["token"] = token
    payload = {
        "service": DISCOVERY_SERVICE,
        "config": config,
    }
    headers = {"Authorization": f"Bearer {supervisor_token}"}

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
