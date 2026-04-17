"""HA user authentication middleware (AU.2, extended by AU.7 in 1.5.0).

Resolves the requesting Home Assistant user for every protected UI path
via one of four paths (checked in order). Protected UI paths are
``/ui/api/*`` (the JSON API) **and the static UI shell** (``/``,
``/index.html``, ``/assets/*``, ``/static/*``) — see ``_is_protected_ui_path``.
Gating the API alone (bug #82) left the React SPA HTML + JS bundle
publicly readable on the direct port even with ``require_ha_auth=true``,
which let an LAN attacker version-fingerprint the add-on and enumerate
the API surface without a token, violating AU.7's "mandatory direct-port
auth" contract. Browser access via HA Ingress still works because it
arrives from the Supervisor peer IP (path 1).

  1. **Supervisor peer trust.** When the request arrives from
     172.30.32.2 (Supervisor's internal Ingress proxy), trust it — HA
     already authenticated the user before forwarding. The Supervisor
     forwards the HA user name + id via ``X-Remote-User-Name`` /
     ``X-Remote-User-Id`` headers, which we attach to the request for
     downstream handlers.

  2. **System Bearer (AU.7).** When the request carries ``Authorization:
     Bearer <x>`` and ``x`` equals the add-on's shared worker token
     (``cfg.token``), treat the caller as a trusted system. Used by the
     native ESPHome Fleet HA integration's coordinator so it can poll
     ``/ui/api/*`` without the user having to mint a long-lived access
     token. The add-on plumbs the same token into the Supervisor
     discovery payload so the config flow captures it automatically.

  3. **HA user Bearer.** When the request carries ``Authorization: Bearer
     <HA long-lived access token>``, validate it against Supervisor's
     ``/auth`` endpoint (which exists because the add-on has
     ``auth_api: true`` — AU.1). If Supervisor returns 200, the token
     is valid; the response body carries the user metadata.

  4. **Neither.** Respond with 401 + ``WWW-Authenticate: Bearer
     realm="ESPHome Fleet"``. Since AU.7 (1.5.0) the add-on option
     ``require_ha_auth`` defaults to ``true``, so this path always
     rejects. The option still exists as an escape hatch for test
     harnesses and for a user who deliberately wants pre-1.4.1 behavior.

The middleware attaches ``request["ha_user"]`` on any successful
authentication — ``{"name": ..., "id": ..., "is_admin": ...}`` — or
leaves it absent when auth was bypassed. Handlers use it to attribute
mutations to the HA user who initiated them (AU.4).

Kept separate from the worker-tier ``auth_middleware`` in ``main.py``
(which gates ``/api/v1/*`` on a shared bearer token) so the two auth
contracts don't get tangled. Both middlewares run; ours no-ops for
``/api/v1/*`` paths.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp
from aiohttp import web

from app_config import AppConfig
from constants import HA_SUPERVISOR_IP

logger = logging.getLogger(__name__)

SUPERVISOR_URL = "http://supervisor"
_WWW_AUTHENTICATE = 'Bearer realm="ESPHome Fleet"'


def _is_protected_ui_path(path: str) -> bool:
    """Paths that ``ha_auth_middleware`` protects.

    The React SPA is a 2-tier surface: ``/ui/api/*`` carries the JSON
    data, and ``/`` / ``/index.html`` / ``/assets/*`` / ``/static/*``
    serve the HTML shell + bundled JS/CSS that talks to it. Both tiers
    need the same HA user auth when ``require_ha_auth`` is on — gating
    only the API left the shell publicly readable (bug #82). Ingress
    browser access still works via the Supervisor peer-IP path.
    ``/api/v1/*`` is worker-tier and is separately bearer-gated by
    ``auth_middleware`` in ``main.py``; we deliberately don't touch it
    here.
    """
    if path.startswith("/ui/api/"):
        return True
    if path in ("/", "/index.html"):
        return True
    return path.startswith("/assets/") or path.startswith("/static/")


def _normalize_peer_ip(raw: str) -> str:
    """Duplicate of main._normalize_peer_ip — importing from main causes a
    circular import, and this is the only bit of main we need.
    """
    if not raw:
        return ""
    raw = raw.split("%", 1)[0]
    try:
        import ipaddress  # noqa: PLC0415
        addr = ipaddress.ip_address(raw)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return str(addr)
    except (ValueError, ImportError):
        return raw


def _peer_ip(request: web.Request) -> str:
    """Canonical peer IP string, or ``""`` when we can't determine it."""
    try:
        peer = request.transport.get_extra_info("peername") if request.transport else None
    except Exception:
        return ""
    if not peer:
        return ""
    raw = peer[0] if isinstance(peer, tuple) else str(peer)
    return _normalize_peer_ip(raw)


async def _validate_bearer_with_supervisor(token: str) -> dict[str, Any] | None:
    """POST the token to Supervisor's /auth endpoint for validation.

    Supervisor is reachable at ``http://supervisor`` inside the add-on
    container when ``auth_api: true`` is set in ``config.yaml``. The
    SUPERVISOR_TOKEN env var carries our own Supervisor credential; the
    *user's* token is what we're validating on their behalf.

    Returns the parsed user dict on 200, ``None`` on any non-200 or
    network error. Never raises — callers treat None as "invalid".
    """
    supervisor_token = os.environ.get("SUPERVISOR_TOKEN")
    if not supervisor_token:
        logger.debug("No SUPERVISOR_TOKEN — cannot validate Bearer (AU.2)")
        return None
    headers = {
        "Authorization": f"Bearer {supervisor_token}",
        "Content-Type": "application/json",
    }
    payload = {"token": token}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{SUPERVISOR_URL}/auth",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    return None
                try:
                    data = await resp.json()
                except Exception:
                    # CR.8: fail auth instead of attaching a ghost-user
                    # dict ({"name": None, ...}). Six months later the
                    # only thing worse than no audit trail is an audit
                    # trail full of "action by None".
                    logger.warning(
                        "Supervisor /auth returned HTTP 200 with unparseable body — failing auth"
                    )
                    return None
                return {
                    "name": data.get("name") or data.get("user_name"),
                    "id": data.get("id") or data.get("user_id"),
                    "is_admin": bool(data.get("is_admin", False)),
                }
    except Exception:
        logger.debug("Supervisor /auth validation failed", exc_info=True)
        return None


@web.middleware
async def ha_auth_middleware(request: web.Request, handler):
    """Attach ``request["ha_user"]`` for protected UI paths, optionally reject."""
    path = request.path
    if not _is_protected_ui_path(path):
        return await handler(request)

    cfg: AppConfig = request.app["config"]

    # Path 1: Supervisor peer trust. Requests arriving from
    # 172.30.32.2 are proxied by Supervisor's Ingress; HA already
    # authenticated the user, and Supervisor adds user identity headers.
    peer_ip = _peer_ip(request)
    if peer_ip and peer_ip == _normalize_peer_ip(HA_SUPERVISOR_IP):
        # Headers are best-effort — not every Supervisor version sets
        # X-Remote-User-*; fall through to a None-user entry in that
        # case rather than 401'ing a trusted request.
        name = request.headers.get("X-Remote-User-Name")
        user_id = request.headers.get("X-Remote-User-Id")
        if name or user_id:
            request["ha_user"] = {"name": name, "id": user_id, "is_admin": None}
        return await handler(request)

    auth_header = request.headers.get("Authorization", "")
    bearer = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""

    # Path 2 (AU.7): system-token Bearer. The add-on's shared worker
    # token doubles as the integration's coordinator credential so the
    # user doesn't have to mint an LLAT just to run the integration.
    # `cfg.token` is the same token the Connect Worker modal shows;
    # anyone who already has it is already authenticated to `/api/v1/*`,
    # so granting system access to `/ui/api/*` doesn't widen the blast
    # radius. `ha_user.name` = "esphome_fleet_integration" so mutation
    # audit lines can distinguish system vs user actions (AU.4).
    if bearer and cfg.token and bearer == cfg.token:
        request["ha_user"] = {
            "name": "esphome_fleet_integration",
            "id": None,
            "is_admin": False,
        }
        return await handler(request)

    # Path 3: HA user Bearer — validate against Supervisor's /auth.
    if bearer:
        user = await _validate_bearer_with_supervisor(bearer)
        if user is not None:
            request["ha_user"] = user
            return await handler(request)

    # Path 4: no (valid) auth — gated by require_ha_auth.
    if cfg.require_ha_auth:
        logger.info(
            "401 on %s: require_ha_auth=true and no valid HA auth "
            "(peer_ip=%s, has_bearer=%s)",
            path, peer_ip or "<unknown>", bool(auth_header),
        )
        return web.json_response(
            {"error": "Unauthorized — valid HA Bearer token required"},
            status=401,
            headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
        )

    # Pre-1.4.1 compatibility: unauthenticated direct-port access is allowed
    # when require_ha_auth is off. AU.7 flipped the default to on, so this
    # branch only matters for test harnesses / deliberate opt-out.
    return await handler(request)
