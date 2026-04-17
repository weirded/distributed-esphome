"""#74 — coordinator auth tests (AU.7 / #73).

Would have caught #73 pre-ship: the HA integration's coordinator
must (a) send `Authorization: Bearer <token>` on every GET, and
(b) convert a 401 from the add-on into `ConfigEntryAuthFailed` so
HA's reauth flow kicks in (as opposed to letting it silently turn
into `UpdateFailed`, which is the "degraded" state users saw in
the bug report).

These run without the HA test harness — we instantiate the
coordinator via `__new__` (same pattern as
`test_integration_coordinator_events.py`) and inject a fake
`aiohttp` session so the HTTP layer is deterministic.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from esphome_fleet.coordinator import EsphomeFleetCoordinator


def _make_coord(token: str | None) -> EsphomeFleetCoordinator:
    """Build a coordinator without triggering HA init."""
    coord = EsphomeFleetCoordinator.__new__(EsphomeFleetCoordinator)
    coord._base_url = "http://addon:8765"  # type: ignore[attr-defined]
    coord._token = token  # type: ignore[attr-defined]
    coord._session = MagicMock()  # type: ignore[attr-defined]
    coord._last_job_states = {}  # type: ignore[attr-defined]
    coord._entry = None  # type: ignore[attr-defined]
    import logging
    coord.logger = logging.getLogger("test-coord")  # type: ignore[assignment]
    return coord


class _FakeResponse:
    """Minimal `aiohttp.ClientResponse` replica for the GET path."""

    def __init__(self, status: int, body: Any = None) -> None:
        self._status = status
        self._body = body if body is not None else {}

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False

    def raise_for_status(self) -> None:
        if self._status >= 400:
            request_info = MagicMock()
            request_info.real_url = "http://addon:8765/ui/api/server-info"
            raise aiohttp.ClientResponseError(
                request_info=request_info,
                history=(),
                status=self._status,
                message=f"HTTP {self._status}",
            )

    async def json(self) -> Any:
        return self._body


def _install_get(coord: EsphomeFleetCoordinator, resp: _FakeResponse) -> MagicMock:
    """Wire a fake `session.get` that returns *resp* once and records args."""
    getter = MagicMock(return_value=resp)
    coord._session.get = getter  # type: ignore[attr-defined]
    return getter


async def test_get_json_sends_authorization_bearer_when_token_set() -> None:
    """AU.7 / #74: every GET must carry the Bearer header."""
    coord = _make_coord(token="secret-token-abc")
    resp = _FakeResponse(200, {"hello": "world"})
    getter = _install_get(coord, resp)

    result = await coord._get_json("/ui/api/server-info")

    assert result == {"hello": "world"}
    getter.assert_called_once()
    kwargs = getter.call_args.kwargs
    assert kwargs["headers"] == {"Authorization": "Bearer secret-token-abc"}


async def test_get_json_omits_authorization_when_token_absent() -> None:
    """Legacy entries with no CONF_TOKEN fall back to no header — the
    server's Supervisor-peer trust path catches those on Ingress, and
    the reauth flow catches them on direct-port."""
    coord = _make_coord(token=None)
    resp = _FakeResponse(200, {})
    getter = _install_get(coord, resp)

    await coord._get_json("/ui/api/server-info")

    kwargs = getter.call_args.kwargs
    assert kwargs["headers"] == {}


async def test_coordinator_401_raises_config_entry_auth_failed() -> None:
    """#73 regression guard: add-on 401 → ConfigEntryAuthFailed (triggers
    HA's reauth flow), NOT UpdateFailed (which silently degrades)."""
    coord = _make_coord(token="stale-token")
    resp = _FakeResponse(401)

    # Any one of the 6 gather()'d GETs raising is enough; use a side_effect
    # that returns the 401 response on every invocation.
    coord._session.get = MagicMock(return_value=resp)  # type: ignore[attr-defined]

    with pytest.raises(ConfigEntryAuthFailed):
        await coord._async_update_data()


async def test_coordinator_500_stays_update_failed() -> None:
    """A legitimate 500 (add-on bug, not an auth problem) stays as
    UpdateFailed so we don't spam the user with reauth prompts."""
    coord = _make_coord(token="fresh-token")
    resp = _FakeResponse(500)
    coord._session.get = MagicMock(return_value=resp)  # type: ignore[attr-defined]

    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_coordinator_network_error_stays_update_failed() -> None:
    """ClientError (DNS, connection refused, etc.) is transient → UpdateFailed."""
    coord = _make_coord(token="fresh-token")

    class _Raising:
        async def __aenter__(self) -> "_Raising":
            raise aiohttp.ClientConnectorError(
                connection_key=MagicMock(),
                os_error=OSError("connection refused"),
            )

        async def __aexit__(self, *a: Any) -> bool:  # pragma: no cover
            return False

    coord._session.get = MagicMock(return_value=_Raising())  # type: ignore[attr-defined]

    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_post_json_sends_authorization_bearer() -> None:
    """Services path: async_post_json also carries the Bearer."""
    coord = _make_coord(token="t")

    class _Post:
        def __init__(self) -> None:
            self.called_with: dict[str, Any] = {}

        async def __aenter__(self) -> "_Post":
            return self

        async def __aexit__(self, *a: Any) -> bool:
            return False

        def raise_for_status(self) -> None:
            return None

        @property
        def content_type(self) -> str:
            return "application/json"

        async def json(self) -> dict[str, Any]:
            return {"enqueued": 1}

    fake_post = _Post()
    poster = MagicMock(return_value=fake_post)
    coord._session.post = poster  # type: ignore[attr-defined]
    await coord.async_post_json("/ui/api/compile", {"targets": ["a.yaml"]})

    poster.assert_called_once()
    assert poster.call_args.kwargs["headers"] == {"Authorization": "Bearer t"}
