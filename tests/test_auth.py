"""Tests for auth_middleware in main.py.

Uses aiohttp.test_utils.TestClient/TestServer directly (no pytest-aiohttp required).
"""

from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app_config import AppConfig
from main import auth_middleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(token: str = "secret-token") -> web.Application:
    """Minimal aiohttp app with the real auth middleware and a few dummy routes."""
    cfg = AppConfig()
    # SP.8: server token lives in Settings; the sync test helper pokes
    # it onto the singleton directly.
    import settings as _s
    _s._reset_for_tests()
    _s._set_for_tests(server_token=token)

    async def worker_route(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def ui_route(request: web.Request) -> web.Response:
        return web.json_response({"ui": True})

    async def other_route(request: web.Request) -> web.Response:
        return web.json_response({"other": True})

    app = web.Application(middlewares=[auth_middleware])
    app["config"] = cfg

    app.router.add_get("/api/v1/status", worker_route)
    app.router.add_get("/ui/api/targets", ui_route)
    app.router.add_get("/", ui_route)
    app.router.add_get("/index.html", ui_route)
    app.router.add_get("/healthz", other_route)

    return app


async def _make_client(token: str = "secret-token") -> TestClient:
    app = _make_app(token=token)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


# ---------------------------------------------------------------------------
# /api/v1/* — Bearer token auth
# ---------------------------------------------------------------------------

async def test_api_v1_valid_token_returns_200():
    client = await _make_client("secret-token")
    try:
        resp = await client.get("/api/v1/status", headers={"Authorization": "Bearer secret-token"})
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
    finally:
        await client.close()


async def test_api_v1_invalid_token_returns_401():
    client = await _make_client("secret-token")
    try:
        resp = await client.get("/api/v1/status", headers={"Authorization": "Bearer wrong-token"})
        assert resp.status == 401
        data = await resp.json()
        assert data["error"] == "Unauthorized"
    finally:
        await client.close()


async def test_api_v1_no_auth_header_returns_401():
    client = await _make_client("secret-token")
    try:
        resp = await client.get("/api/v1/status")
        assert resp.status == 401
        data = await resp.json()
        assert data["error"] == "Unauthorized"
    finally:
        await client.close()


async def test_api_v1_malformed_bearer_returns_401():
    """Token present but without 'Bearer ' prefix is rejected."""
    client = await _make_client("secret-token")
    try:
        resp = await client.get("/api/v1/status", headers={"Authorization": "secret-token"})
        assert resp.status == 401
    finally:
        await client.close()


async def test_api_v1_empty_bearer_value_returns_401():
    client = await _make_client("secret-token")
    try:
        resp = await client.get("/api/v1/status", headers={"Authorization": "Bearer "})
        assert resp.status == 401
    finally:
        await client.close()


async def test_api_v1_no_token_configured_allows_all():
    """When no token is configured the server allows unauthenticated worker requests."""
    client = await _make_client(token="")
    try:
        resp = await client.get("/api/v1/status")
        assert resp.status == 200
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# /ui/api/* — Ingress trust (no auth required)
# ---------------------------------------------------------------------------

async def test_ui_api_no_auth_returns_200():
    """UI routes do not require any authentication."""
    client = await _make_client("secret-token")
    try:
        resp = await client.get("/ui/api/targets")
        assert resp.status == 200
        data = await resp.json()
        assert data["ui"] is True
    finally:
        await client.close()


async def test_ui_api_also_works_with_valid_token():
    """Auth header on UI routes is irrelevant but must not block the request."""
    client = await _make_client("secret-token")
    try:
        resp = await client.get(
            "/ui/api/targets",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert resp.status == 200
    finally:
        await client.close()


async def test_root_path_no_auth_required():
    """/ is served without auth (Ingress trust path)."""
    client = await _make_client("secret-token")
    try:
        resp = await client.get("/")
        assert resp.status == 200
    finally:
        await client.close()


async def test_index_html_no_auth_required():
    """/index.html is served without auth."""
    client = await _make_client("secret-token")
    try:
        resp = await client.get("/index.html")
        assert resp.status == 200
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# X-Ingress-Path header injection
# ---------------------------------------------------------------------------

async def test_ingress_path_header_is_forwarded_to_handler():
    """The middleware passes X-Ingress-Path untouched to the handler."""
    received_headers: dict = {}

    async def ui_route(request: web.Request) -> web.Response:
        received_headers["x-ingress-path"] = request.headers.get("X-Ingress-Path", "")
        return web.json_response({"ok": True})

    import settings as _s
    _s._reset_for_tests()
    _s._set_for_tests(server_token="tok")
    cfg = AppConfig()
    app = web.Application(middlewares=[auth_middleware])
    app["config"] = cfg
    app.router.add_get("/ui/api/check", ui_route)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get(
            "/ui/api/check",
            headers={"X-Ingress-Path": "/api/hassio_ingress/abc123"},
        )
        assert resp.status == 200
        assert received_headers["x-ingress-path"] == "/api/hassio_ingress/abc123"
    finally:
        await client.close()


async def test_ingress_path_absent_means_header_missing():
    """If no X-Ingress-Path is sent, the header is simply absent in the request."""
    received_headers: dict = {}

    async def ui_route(request: web.Request) -> web.Response:
        received_headers["x-ingress-path"] = request.headers.get("X-Ingress-Path", "MISSING")
        return web.json_response({"ok": True})

    import settings as _s
    _s._reset_for_tests()
    _s._set_for_tests(server_token="tok")
    cfg = AppConfig()
    app = web.Application(middlewares=[auth_middleware])
    app["config"] = cfg
    app.router.add_get("/ui/api/check", ui_route)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/ui/api/check")
        assert resp.status == 200
        assert received_headers["x-ingress-path"] == "MISSING"
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Paths outside /api/v1/* and /ui/api/* — pass-through
# ---------------------------------------------------------------------------

async def test_unknown_path_passes_through_middleware():
    """Routes outside the two protected namespaces are forwarded without auth checks."""
    client = await _make_client("tok")
    try:
        resp = await client.get("/healthz")
        assert resp.status == 200
        data = await resp.json()
        assert data["other"] is True
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# B.2 — Edge cases: logging reasons, peername=None, spoofed peer IP, header variants
# ---------------------------------------------------------------------------

async def test_api_v1_401_logs_structured_reason_for_missing_header(caplog):
    """Bug #3: a 401 from missing auth header must emit a structured WARNING
    naming the reason and the peer IP. Operators rely on this to distinguish
    token vs peer-IP vs missing-header rejections without enabling DEBUG."""
    import logging

    client = await _make_client("secret-token")
    try:
        with caplog.at_level(logging.WARNING, logger="main"):
            resp = await client.get("/api/v1/status")
            assert resp.status == 401
    finally:
        await client.close()

    main_warnings = [r for r in caplog.records if r.name == "main" and r.levelno == logging.WARNING]
    matching = [r for r in main_warnings if "401" in r.getMessage() and "missing_authorization_header" in r.getMessage()]
    assert matching, (
        "expected a structured 401 warning with reason=missing_authorization_header; "
        f"got: {[r.getMessage() for r in main_warnings]}"
    )


async def test_api_v1_401_logs_bearer_token_mismatch_reason(caplog):
    import logging

    client = await _make_client("secret-token")
    try:
        with caplog.at_level(logging.WARNING, logger="main"):
            resp = await client.get(
                "/api/v1/status",
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert resp.status == 401
    finally:
        await client.close()

    main_warnings = [r for r in caplog.records if r.name == "main" and r.levelno == logging.WARNING]
    assert any("bearer_token_mismatch" in r.getMessage() for r in main_warnings), (
        f"expected bearer_token_mismatch warning; got: {[r.getMessage() for r in main_warnings]}"
    )


async def test_api_v1_401_logs_not_bearer_scheme_reason(caplog):
    import logging

    client = await _make_client("secret-token")
    try:
        with caplog.at_level(logging.WARNING, logger="main"):
            resp = await client.get(
                "/api/v1/status",
                headers={"Authorization": "Basic dXNlcjpwYXNz"},
            )
            assert resp.status == 401
    finally:
        await client.close()

    main_warnings = [r for r in caplog.records if r.name == "main" and r.levelno == logging.WARNING]
    assert any("authorization_not_bearer_scheme" in r.getMessage() for r in main_warnings), (
        f"expected authorization_not_bearer_scheme warning; got: {[r.getMessage() for r in main_warnings]}"
    )


async def test_api_v1_plausible_supervisor_spoof_is_rejected():
    """Peer IP adjacent to the real Supervisor IP must NOT be trusted.

    172.30.32.3 looks plausible but is not the Supervisor address; the
    middleware must fall through to token auth.
    """
    from unittest.mock import MagicMock, patch

    app = _make_app(token="secret-token")

    # Build a fake request whose transport reports the spoofed IP.
    request = MagicMock(spec=web.Request)
    request.path = "/api/v1/status"
    request.transport = MagicMock()
    request.transport.get_extra_info.return_value = ("172.30.32.3", 54321)
    request.headers = {}  # no Authorization
    request.app = app

    called = {"handler": False}

    async def handler(_req):
        called["handler"] = True
        return web.json_response({"ok": True})

    resp = await auth_middleware(request, handler)
    assert resp.status == 401
    assert called["handler"] is False


async def test_api_v1_real_supervisor_ip_bypasses_auth():
    """The hardcoded Supervisor IP (172.30.32.2) must still bypass auth —
    regression guard against an accidental rename of HA_SUPERVISOR_IP."""
    from unittest.mock import MagicMock

    from constants import HA_SUPERVISOR_IP

    app = _make_app(token="secret-token")
    request = MagicMock(spec=web.Request)
    request.path = "/api/v1/status"
    request.transport = MagicMock()
    request.transport.get_extra_info.return_value = (HA_SUPERVISOR_IP, 42000)
    request.headers = {}
    request.app = app

    called = {"handler": False}

    async def handler(_req):
        called["handler"] = True
        return web.json_response({"ok": True})

    resp = await auth_middleware(request, handler)
    assert called["handler"] is True
    assert resp.status == 200


async def test_api_v1_peername_none_falls_through_to_token_auth():
    """``transport.get_extra_info("peername")`` returning None must not crash
    and must fall through to the token-auth branch.

    Regression guard for the C.2 edge case: if `peername` is missing, the
    middleware must still process the Bearer token rather than 500-ing.
    """
    from unittest.mock import MagicMock

    app = _make_app(token="secret-token")
    request = MagicMock(spec=web.Request)
    request.path = "/api/v1/status"
    request.transport = MagicMock()
    request.transport.get_extra_info.return_value = None  # no peer info
    request.headers = {"Authorization": "Bearer secret-token"}
    request.app = app

    async def handler(_req):
        return web.json_response({"ok": True})

    resp = await auth_middleware(request, handler)
    assert resp.status == 200


async def test_api_v1_peername_none_still_rejects_bad_token():
    from unittest.mock import MagicMock

    app = _make_app(token="secret-token")
    request = MagicMock(spec=web.Request)
    request.path = "/api/v1/status"
    request.transport = MagicMock()
    request.transport.get_extra_info.return_value = None
    request.headers = {"Authorization": "Bearer WRONG"}
    request.app = app

    async def handler(_req):
        return web.json_response({"ok": True})

    resp = await auth_middleware(request, handler)
    assert resp.status == 401
