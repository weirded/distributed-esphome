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
    cfg = AppConfig(token=token)

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

    cfg = AppConfig(token="tok")
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

    cfg = AppConfig(token="tok")
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
