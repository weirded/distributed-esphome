"""HI.12 — service-handler tests (HI.2)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from esphome_fleet.const import DOMAIN
from esphome_fleet.services import (
    _first_coordinator,
    _handle_cancel,
    _handle_compile,
    _handle_validate,
)


class _FakeCall:
    """Minimal ServiceCall stand-in: just `hass` + `data`."""

    def __init__(self, hass, data: dict) -> None:
        self.hass = hass
        self.data = data


def _hass_with_coordinator() -> tuple[SimpleNamespace, AsyncMock]:
    post = AsyncMock(return_value={"enqueued": 1, "cancelled": 1, "job_id": "j"})
    coordinator = SimpleNamespace(async_post_json=post)
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    return hass, post


async def test_compile_service_posts_minimal_payload() -> None:
    hass, post = _hass_with_coordinator()
    await _handle_compile(_FakeCall(hass, {"targets": ["living-room.yaml"]}))
    post.assert_awaited_once()
    path, payload = post.call_args.args
    assert path == "/ui/api/compile"
    assert payload == {"targets": ["living-room.yaml"]}


async def test_compile_service_includes_version_and_worker_when_set() -> None:
    hass, post = _hass_with_coordinator()
    await _handle_compile(
        _FakeCall(
            hass,
            {
                "targets": ["a.yaml", "b.yaml"],
                "esphome_version": "2026.3.2",
                "worker_id": "worker-abc",
            },
        )
    )
    _, payload = post.call_args.args
    assert payload == {
        "targets": ["a.yaml", "b.yaml"],
        "esphome_version": "2026.3.2",
        "pinned_client_id": "worker-abc",
    }


async def test_compile_service_accepts_string_all_targets() -> None:
    hass, post = _hass_with_coordinator()
    await _handle_compile(_FakeCall(hass, {"targets": "all"}))
    _, payload = post.call_args.args
    # "all" should pass through untouched — server's bulk endpoint
    # understands the sentinel.
    assert payload == {"targets": "all"}


async def test_cancel_service_posts_job_ids() -> None:
    hass, post = _hass_with_coordinator()
    await _handle_cancel(_FakeCall(hass, {"job_ids": ["j1", "j2"]}))
    path, payload = post.call_args.args
    assert path == "/ui/api/cancel"
    assert payload == {"job_ids": ["j1", "j2"]}


async def test_validate_service_posts_single_target() -> None:
    hass, post = _hass_with_coordinator()
    await _handle_validate(_FakeCall(hass, {"target": "x.yaml"}))
    path, payload = post.call_args.args
    assert path == "/ui/api/validate"
    assert payload == {"target": "x.yaml"}


def test_first_coordinator_raises_when_no_entries() -> None:
    from homeassistant.exceptions import HomeAssistantError

    hass = SimpleNamespace(data={DOMAIN: {}})
    with pytest.raises(HomeAssistantError):
        _first_coordinator(hass)


def test_first_coordinator_raises_when_domain_missing() -> None:
    from homeassistant.exceptions import HomeAssistantError

    hass = SimpleNamespace(data={})
    with pytest.raises(HomeAssistantError):
        _first_coordinator(hass)
