"""Tests for the E.9 security headers middleware.

Asserts that the defence-in-depth headers (CSP, X-Content-Type-Options,
Referrer-Policy, Permissions-Policy, X-Frame-Options) are attached to every
UI-tier response and that ``/api/v1/*`` worker-tier responses are explicitly
exempt.
"""

from __future__ import annotations

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app_config import AppConfig
from main import auth_middleware, security_headers_middleware


_EXPECTED_HEADERS = {
    "Content-Security-Policy",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Permissions-Policy",
    "X-Frame-Options",
}


def _make_app() -> web.Application:
    cfg = AppConfig(token="t")

    async def ui_route(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def worker_route(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def index_route(_request: web.Request) -> web.Response:
        return web.Response(text="<html></html>", content_type="text/html")

    app = web.Application(middlewares=[security_headers_middleware, auth_middleware])
    app["config"] = cfg
    app.router.add_get("/ui/api/targets", ui_route)
    app.router.add_get("/api/v1/status", worker_route)
    app.router.add_get("/", index_route)
    app.router.add_get("/index.html", index_route)
    return app


async def _client() -> TestClient:
    c = TestClient(TestServer(_make_app()))
    await c.start_server()
    return c


async def test_ui_api_response_carries_all_security_headers():
    c = await _client()
    try:
        resp = await c.get("/ui/api/targets")
        assert resp.status == 200
        missing = _EXPECTED_HEADERS - set(resp.headers)
        assert not missing, f"missing headers: {missing}"
        # Sanity-check the CSP value contains the load-bearing directives.
        csp = resp.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'self'" in csp
        assert "https://schema.esphome.io" in csp
        assert "wss:" in csp
        # Common attribute checks
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["Referrer-Policy"] == "no-referrer"
        assert "camera=()" in resp.headers["Permissions-Policy"]
    finally:
        await c.close()


async def test_index_html_response_carries_security_headers():
    c = await _client()
    try:
        resp = await c.get("/")
        assert resp.status == 200
        for h in _EXPECTED_HEADERS:
            assert h in resp.headers, f"missing {h} on /"
    finally:
        await c.close()


async def test_worker_api_response_does_not_carry_security_headers():
    """Worker tier (/api/v1/*) is consumed programmatically and the headers
    add no value. Explicitly exempt — the middleware skips it. Documenting
    this with a test so a future "let's just apply them everywhere" change
    is caught."""
    c = await _client()
    try:
        resp = await c.get("/api/v1/status", headers={"Authorization": "Bearer t"})
        assert resp.status == 200
        present = _EXPECTED_HEADERS & set(resp.headers)
        assert not present, f"worker tier should not have security headers, got: {present}"
    finally:
        await c.close()


async def test_handler_set_header_is_not_clobbered():
    """If a downstream handler explicitly sets one of the security headers
    (e.g. a more restrictive CSP for a specific page), the middleware must
    leave it alone rather than overwriting."""
    cfg = AppConfig(token="t")

    async def custom_csp_route(_request: web.Request) -> web.Response:
        resp = web.json_response({"ok": True})
        resp.headers["Content-Security-Policy"] = "default-src 'none'"
        return resp

    app = web.Application(middlewares=[security_headers_middleware, auth_middleware])
    app["config"] = cfg
    app.router.add_get("/ui/api/locked", custom_csp_route)

    c = TestClient(TestServer(app))
    await c.start_server()
    try:
        resp = await c.get("/ui/api/locked")
        assert resp.headers["Content-Security-Policy"] == "default-src 'none'"
        # The other headers should still be added.
        assert "X-Content-Type-Options" in resp.headers
    finally:
        await c.close()
