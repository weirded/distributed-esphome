"""HA user auth middleware tests (AU.6)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from app_config import AppConfig
from constants import HA_SUPERVISOR_IP
from ha_auth import (
    _is_protected_ui_path,
    _validate_bearer_with_supervisor,
    ha_auth_middleware,
)


def _make_app(require_ha_auth: bool = False, token: str = "") -> web.Application:
    app = web.Application()
    app["config"] = AppConfig(require_ha_auth=require_ha_auth, token=token)
    return app


async def _run_middleware(
    *,
    path: str = "/ui/api/targets",
    peer_ip: str | None = None,
    auth: str | None = None,
    user_headers: dict | None = None,
    require_ha_auth: bool = False,
    supervisor_valid: object = None,
    server_token: str = "",
) -> web.Response:
    """Execute the middleware against a constructed request.

    *supervisor_valid*: ``None`` = bearer path untouched; dict = validator
    returns that user; ``"invalid"`` = validator returns ``None``.
    """
    hdrs = {}
    if auth:
        hdrs["Authorization"] = auth
    if user_headers:
        hdrs.update(user_headers)

    class _T:
        def get_extra_info(self, k):
            if k == "peername" and peer_ip:
                return (peer_ip, 1)
            return None

    app = _make_app(require_ha_auth=require_ha_auth, token=server_token)
    request = make_mocked_request(
        "GET", path, headers=hdrs, transport=_T(), app=app,
    )

    async def handler(req):
        return web.json_response({"ha_user": req.get("ha_user")})

    if supervisor_valid is None:
        return await ha_auth_middleware(request, handler)
    mock = AsyncMock(
        return_value=None if supervisor_valid == "invalid" else supervisor_valid
    )
    with patch("ha_auth._validate_bearer_with_supervisor", mock):
        return await ha_auth_middleware(request, handler)


# --- ha_auth_middleware ---


async def test_supervisor_peer_trusted_without_auth_header() -> None:
    """Path 1: Supervisor IP peer trusted, user extracted from headers."""
    resp = await _run_middleware(
        peer_ip=HA_SUPERVISOR_IP,
        user_headers={"X-Remote-User-Name": "stefan", "X-Remote-User-Id": "abc"},
    )
    assert resp.status == 200
    body = resp.body.decode() if resp.body else ""
    assert '"stefan"' in body
    assert '"abc"' in body


async def test_supervisor_peer_without_user_headers_passes_through() -> None:
    """Path 1 fallback: trusted peer, no user headers → still allowed, no ha_user."""
    resp = await _run_middleware(peer_ip=HA_SUPERVISOR_IP)
    assert resp.status == 200
    # No user headers means request["ha_user"] wasn't set.
    body = resp.body.decode() if resp.body else ""
    assert '"ha_user": null' in body


async def test_bearer_token_validated_against_supervisor() -> None:
    """Path 2: valid Bearer → user attached from Supervisor response."""
    resp = await _run_middleware(
        peer_ip="10.0.0.5",
        auth="Bearer good-token",
        supervisor_valid={"name": "stefan", "id": "abc", "is_admin": True},
    )
    assert resp.status == 200
    body = resp.body.decode() if resp.body else ""
    assert '"stefan"' in body
    assert '"is_admin": true' in body


async def test_invalid_bearer_falls_through_without_require_ha_auth() -> None:
    """Path 3 with require_ha_auth=false: unauthenticated request allowed."""
    resp = await _run_middleware(
        peer_ip="10.0.0.5",
        auth="Bearer bad-token",
        supervisor_valid="invalid",
        require_ha_auth=False,
    )
    assert resp.status == 200
    body = resp.body.decode() if resp.body else ""
    assert '"ha_user": null' in body


async def test_no_auth_and_require_ha_auth_returns_401() -> None:
    """AU.3: with require_ha_auth=true, no auth → 401 + WWW-Authenticate."""
    resp = await _run_middleware(
        peer_ip="10.0.0.5",
        require_ha_auth=True,
    )
    assert resp.status == 401
    assert resp.headers.get("WWW-Authenticate", "").startswith("Bearer")


async def test_invalid_bearer_with_require_ha_auth_returns_401() -> None:
    """AU.3: invalid Bearer + require_ha_auth=true → 401."""
    resp = await _run_middleware(
        peer_ip="10.0.0.5",
        auth="Bearer bad",
        supervisor_valid="invalid",
        require_ha_auth=True,
    )
    assert resp.status == 401


async def test_non_ui_api_path_bypasses_middleware() -> None:
    """The middleware only gates protected UI paths — /api/v1/* is handled
    by the worker-tier auth_middleware in main.py."""
    resp = await _run_middleware(
        path="/api/v1/workers/heartbeat",
        require_ha_auth=True,
    )
    assert resp.status == 200


# --- #82: static UI shell gated under require_ha_auth ---


async def test_static_index_html_requires_auth_when_mandatory() -> None:
    """#82: direct-port `GET /` with no auth must 401 under require_ha_auth=true.
    Before the fix, the SPA shell was readable by anyone on the LAN."""
    resp = await _run_middleware(
        path="/",
        peer_ip="10.0.0.5",
        require_ha_auth=True,
    )
    assert resp.status == 401
    assert resp.headers.get("WWW-Authenticate", "").startswith("Bearer")


async def test_static_assets_require_auth_when_mandatory() -> None:
    """#82: Vite bundle at /assets/* must 401 — the JS bundle leaks the
    API surface to an unauthenticated attacker."""
    resp = await _run_middleware(
        path="/assets/index-abc123.js",
        peer_ip="10.0.0.5",
        require_ha_auth=True,
    )
    assert resp.status == 401


async def test_static_static_dir_requires_auth_when_mandatory() -> None:
    """#82: legacy /static/* assets (favicon, icons) also gated."""
    resp = await _run_middleware(
        path="/static/favicon.svg",
        peer_ip="10.0.0.5",
        require_ha_auth=True,
    )
    assert resp.status == 401


async def test_static_allowed_via_supervisor_peer_without_auth() -> None:
    """HA Ingress browser load of the SPA shell: Supervisor peer IP
    short-circuits path 1 of the 4-path auth logic, so no 401 even
    without a Bearer. This is the 99% case — browsers iframing the
    add-on via HA Supervisor must keep working."""
    resp = await _run_middleware(
        path="/",
        peer_ip=HA_SUPERVISOR_IP,
        require_ha_auth=True,
    )
    assert resp.status == 200


async def test_static_allowed_with_system_token_bearer() -> None:
    """Direct-port power-user access: curl -H 'Authorization: Bearer <system-token>'
    loads the HTML shell for scripting. AU.7 path 2."""
    resp = await _run_middleware(
        path="/",
        peer_ip="10.0.0.5",
        auth="Bearer the-add-on-shared-token",
        server_token="the-add-on-shared-token",
        require_ha_auth=True,
    )
    assert resp.status == 200


async def test_static_allowed_with_valid_ha_bearer() -> None:
    """Direct-port with HA long-lived access token (path 3). Supervisor
    validates and the user identity is attached — same as /ui/api/*."""
    resp = await _run_middleware(
        path="/index.html",
        peer_ip="10.0.0.5",
        auth="Bearer user-llat",
        supervisor_valid={"name": "stefan", "id": "abc", "is_admin": True},
        require_ha_auth=True,
    )
    assert resp.status == 200


async def test_non_ui_path_still_bypasses_ha_auth() -> None:
    """Defensive: paths outside the protected set (e.g. a stray /foo)
    still bypass ha_auth_middleware completely — this middleware only
    gates the UI tier, and we don't want it to accidentally swallow
    worker-tier or unrelated paths."""
    resp = await _run_middleware(
        path="/foo/bar",
        peer_ip="10.0.0.5",
        require_ha_auth=True,
    )
    assert resp.status == 200


def test_is_protected_ui_path_covers_ui_surface() -> None:
    """Whitebox check: the set of protected paths matches the routes
    registered in main.py (`/`, `/index.html`, `/assets/*`, `/static/*`,
    `/ui/api/*`)."""
    assert _is_protected_ui_path("/")
    assert _is_protected_ui_path("/index.html")
    assert _is_protected_ui_path("/assets/index-abc.js")
    assert _is_protected_ui_path("/static/favicon.svg")
    assert _is_protected_ui_path("/ui/api/targets")
    # /api/v1/* is worker-tier, handled elsewhere.
    assert not _is_protected_ui_path("/api/v1/workers/heartbeat")
    # Nothing else.
    assert not _is_protected_ui_path("/foo")
    assert not _is_protected_ui_path("")


async def test_supervisor_peer_takes_precedence_over_bearer() -> None:
    """When the request is from Supervisor, we don't hit the bearer path."""
    # supervisor_valid set to invalid would 401 the bearer path — but we
    # should short-circuit on the trusted peer IP check BEFORE it runs.
    resp = await _run_middleware(
        peer_ip=HA_SUPERVISOR_IP,
        auth="Bearer anything",
        supervisor_valid="invalid",
        require_ha_auth=True,
    )
    assert resp.status == 200


# --- _validate_bearer_with_supervisor ---


async def test_validate_bearer_returns_none_without_supervisor_token(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert await _validate_bearer_with_supervisor("user-token") is None


async def test_validate_bearer_parses_supervisor_response(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "super-token")

    class _Resp:
        status = 200
        async def json(self):
            return {"name": "stefan", "id": "abc", "is_admin": True}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False

    class _Session:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        def post(self, *args, **kwargs):
            return _Resp()

    with patch("ha_auth.aiohttp.ClientSession", return_value=_Session()):
        user = await _validate_bearer_with_supervisor("user-token")
    assert user == {"name": "stefan", "id": "abc", "is_admin": True}


async def test_validate_bearer_returns_none_on_non_200(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "super-token")

    class _Resp:
        status = 401
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False

    class _Session:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        def post(self, *args, **kwargs):
            return _Resp()

    with patch("ha_auth.aiohttp.ClientSession", return_value=_Session()):
        assert await _validate_bearer_with_supervisor("user-token") is None


# --- AU.7: system-token Bearer path ---


async def test_system_token_bearer_grants_access_without_supervisor() -> None:
    """AU.7 Path 2: Bearer equal to cfg.token authenticates as system caller."""
    resp = await _run_middleware(
        auth="Bearer the-add-on-shared-token",
        server_token="the-add-on-shared-token",
        # No supervisor_valid mock — the system-token path must short-circuit
        # BEFORE ha_auth ever reaches the Supervisor validator.
    )
    assert resp.status == 200
    body = resp.body.decode() if resp.body else ""
    assert "esphome_fleet_integration" in body


async def test_system_token_mismatch_falls_through_to_supervisor() -> None:
    """AU.7: a Bearer that isn't the add-on token falls through to the
    Supervisor /auth validator as before."""
    resp = await _run_middleware(
        auth="Bearer llat-from-a-user",
        server_token="the-add-on-shared-token",  # non-matching
        supervisor_valid={"name": "stefan", "id": "abc", "is_admin": True},
    )
    assert resp.status == 200
    body = resp.body.decode() if resp.body else ""
    assert '"stefan"' in body


async def test_empty_server_token_does_not_accept_empty_bearer() -> None:
    """AU.7 edge case: cfg.token == "" must not let `Bearer ` in.
    Defensive — an empty add-on token is an error state, not a shortcut."""
    resp = await _run_middleware(
        auth="Bearer ",  # empty bearer token
        server_token="",
        require_ha_auth=True,
    )
    assert resp.status == 401


async def test_require_ha_auth_default_is_true() -> None:
    """AU.7: mandatory in 1.5.0. AppConfig() with no overrides must set
    require_ha_auth=True so the middleware rejects unauthenticated calls."""
    cfg = AppConfig()
    assert cfg.require_ha_auth is True
