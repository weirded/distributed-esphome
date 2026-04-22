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
     realm="ESPHome Fleet"``. Gated by the add-on option
     ``require_ha_auth``. AU.7 (1.5.0) flipped the default to ``true``;
     bug #83 (1.6.2) flipped it back to ``false`` because the true
     default hard-broke the standalone ``docker-compose`` path where
     there is no Supervisor to validate against. Ingress-wrapped
     access is unaffected in both directions — path 1 short-circuits.
     Users on untrusted networks opt in via the Settings drawer. When
     the request is a browser (``Accept: text/html``) we serve a styled
     HTML remediation page instead of the bare JSON, so the user can
     actually see how to provide a token or disable the flag.

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

from constants import HA_SUPERVISOR_IP

logger = logging.getLogger(__name__)

SUPERVISOR_URL = "http://supervisor"
_WWW_AUTHENTICATE = 'Bearer realm="ESPHome Fleet"'


def _prefers_html(accept: str) -> bool:
    """True when the ``Accept`` header indicates a browser client.

    Browsers send ``text/html,application/xhtml+xml,...`` as the top
    preference; API clients (workers, the HA integration, curl with
    explicit ``-H "Accept: application/json"``) send
    ``application/json`` or omit the header / send ``*/*``. Treat the
    first two as "wants HTML" and everything else (including empty and
    ``*/*``) as "wants JSON" to keep the machine-readable 401 contract
    that workers and the integration rely on.
    """
    if not accept:
        return False
    for part in accept.split(","):
        media = part.split(";", 1)[0].strip().lower()
        if media in ("text/html", "application/xhtml+xml"):
            return True
        if media == "application/json":
            return False
    return False


_HTML_401_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ESPHome Fleet — authentication required</title>
  <style>
    :root { color-scheme: dark light; }
    html, body { height: 100%; margin: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 2rem;
    }
    main {
      max-width: 640px;
      width: 100%;
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 12px;
      padding: 2rem 2.25rem;
      box-shadow: 0 20px 50px rgba(0,0,0,0.35);
    }
    h1 { margin: 0 0 0.5rem; font-size: 1.5rem; letter-spacing: -0.01em; }
    p { margin: 0.5rem 0 1rem; line-height: 1.55; color: #cbd5e1; }
    h2 { margin: 1.5rem 0 0.5rem; font-size: 1rem; color: #f8fafc; }
    code, kbd, pre {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.9em;
      background: #0f172a;
      border: 1px solid #334155;
      border-radius: 6px;
      padding: 0.1rem 0.35rem;
      color: #e2e8f0;
    }
    pre { padding: 0.75rem 1rem; overflow-x: auto; white-space: pre-wrap; word-break: break-word; }
    ol { padding-left: 1.25rem; margin: 0.5rem 0; }
    li { margin: 0.4rem 0; line-height: 1.5; }
    hr { border: 0; border-top: 1px solid #334155; margin: 1.5rem 0; }
    .muted { color: #94a3b8; font-size: 0.9rem; }
    @media (prefers-color-scheme: light) {
      body { background: #f8fafc; color: #0f172a; }
      main { background: #ffffff; border-color: #e2e8f0; }
      p { color: #334155; }
      h2 { color: #0f172a; }
      code, kbd, pre { background: #f1f5f9; border-color: #cbd5e1; color: #0f172a; }
      .muted { color: #64748b; }
    }
  </style>
</head>
<body>
<main>
  <h1>Authentication required</h1>
  <p>
    You&rsquo;re reaching ESPHome Fleet on its direct port
    (<code>:8765</code>). This install has the <code>require_ha_auth</code>
    setting turned on, so every request from outside Home Assistant&rsquo;s
    Ingress proxy needs to carry a bearer token.
  </p>
  <p>You have two ways forward:</p>

  <h2>1. Provide a token</h2>
  <p>
    Send your request with an <code>Authorization: Bearer &lt;token&gt;</code>
    header. The token is the add-on&rsquo;s shared server token &mdash;
    either the value of <code>server_token</code> in
    <code>/data/settings.json</code> inside the add-on, or the value a
    logged-in Home Assistant user&rsquo;s long-lived access token.
  </p>
  <pre>curl -H &quot;Authorization: Bearer &lt;your-token&gt;&quot; http://&lt;host&gt;:8765/ui/api/server-info</pre>

  <h2>2. Turn off direct-port authentication</h2>
  <p>
    If this server is only reachable on a trusted LAN and you&rsquo;d
    rather not deal with bearer tokens, open the web UI via Home
    Assistant (Settings &rarr; Add-ons &rarr; ESPHome Fleet &rarr; Open Web UI,
    which arrives through Ingress and is always allowed), open the
    Settings drawer, and turn off <strong>Require HA authentication on
    direct port</strong>.
  </p>
  <p class="muted">
    Running the standalone <code>docker-compose</code> image without a
    Supervisor? Set the <code>REQUIRE_HA_AUTH</code> environment
    variable to <code>false</code> on the container, or edit
    <code>/data/settings.json</code> in the volume to
    <code>"require_ha_auth": false</code> and restart.
  </p>

  <hr>
  <p class="muted">
    HTTP 401 &middot; <code>WWW-Authenticate: Bearer realm=&quot;ESPHome Fleet&quot;</code>
  </p>
</main>
</body>
</html>
"""


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

    # SP.8: token + require_ha_auth come from the Settings singleton
    # (live-read), so Settings drawer flips propagate to the next
    # request with no restart. AppConfig no longer carries these fields.
    from settings import get_settings  # noqa: PLC0415
    settings = get_settings()

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
    if bearer and settings.server_token and bearer == settings.server_token:
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
    if settings.require_ha_auth:
        logger.info(
            "401 on %s: require_ha_auth=true and no valid HA auth "
            "(peer_ip=%s, has_bearer=%s)",
            path, peer_ip or "<unknown>", bool(auth_header),
        )
        # #83: browser clients get a styled remediation page with
        # two paths forward (supply a token, or disable the flag via
        # Ingress); machine clients (workers, the integration, curl
        # with an explicit JSON Accept) keep the original JSON body.
        if _prefers_html(request.headers.get("Accept", "")):
            return web.Response(
                body=_HTML_401_PAGE,
                status=401,
                content_type="text/html",
                charset="utf-8",
                headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
            )
        return web.json_response(
            {"error": "Unauthorized — valid HA Bearer token required"},
            status=401,
            headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
        )

    # Default since bug #83 (1.6.2): unauthenticated direct-port access
    # is allowed when require_ha_auth is off. AU.7 had flipped the
    # default on; #83 flipped it back off to keep standalone docker
    # installs reachable without a bearer token. Ingress paths never
    # land here — path 1 short-circuits on the Supervisor peer IP.
    return await handler(request)
