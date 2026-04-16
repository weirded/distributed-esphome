"""HI.12 — service-handler tests (HI.2)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from esphome_fleet.const import DOMAIN
from esphome_fleet.services import (
    _first_coordinator,
    _handle_cancel,
    _handle_compile,
    _handle_validate,
    _resolve_device_ids_to_targets,
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


async def test_compile_resolves_device_ids_to_targets() -> None:
    """#37 — device-targeted compile resolves IDs to YAML filenames."""
    hass, post = _hass_with_coordinator()

    # Mock the device registry
    fake_device = SimpleNamespace(
        identifiers={(DOMAIN, "target:living-room.yaml")},
    )
    fake_registry = SimpleNamespace(
        async_get=lambda did: fake_device if did == "dev-123" else None,
    )

    with patch("esphome_fleet.services.dr.async_get", return_value=fake_registry):
        await _handle_compile(
            _FakeCall(hass, {"device_id": ["dev-123"]})
        )

    _, payload = post.call_args.args
    assert payload == {"targets": ["living-room.yaml"]}


async def test_compile_rejects_unknown_fleet_device_identifier() -> None:
    """#37/#63 — picking a device that's known to HA but doesn't carry
    a `target:` or `worker:` Fleet identifier (e.g. the hub) raises.
    """
    from homeassistant.exceptions import HomeAssistantError

    hass, _ = _hass_with_coordinator()

    fake_device = SimpleNamespace(
        identifiers={(DOMAIN, "hub:entry-xyz")},  # not target/worker
    )
    fake_registry = SimpleNamespace(
        async_get=lambda did: fake_device,
    )

    with patch("esphome_fleet.services.dr.async_get", return_value=fake_registry):
        with pytest.raises(HomeAssistantError, match="targets or workers"):
            await _handle_compile(
                _FakeCall(hass, {"device_id": ["dev-456"]})
            )


async def test_compile_raises_when_no_targets_and_no_devices() -> None:
    """#38 — calling compile with empty data gives a clear error."""
    from homeassistant.exceptions import HomeAssistantError

    hass, _ = _hass_with_coordinator()
    with pytest.raises(HomeAssistantError, match="Select at least one device"):
        await _handle_compile(_FakeCall(hass, {}))


async def test_validate_resolves_device_id() -> None:
    """#37 — device-targeted validate."""
    hass, post = _hass_with_coordinator()

    fake_device = SimpleNamespace(
        identifiers={(DOMAIN, "target:garage-door.yaml")},
    )
    fake_registry = SimpleNamespace(
        async_get=lambda did: fake_device if did == "dev-789" else None,
    )

    with patch("esphome_fleet.services.dr.async_get", return_value=fake_registry):
        await _handle_validate(
            _FakeCall(hass, {"device_id": "dev-789"})
        )

    _, payload = post.call_args.args
    assert payload == {"target": "garage-door.yaml"}


def test_resolve_device_ids_extracts_target_filename() -> None:
    """Unit test for the device-id → filename resolver."""
    fake_device = SimpleNamespace(
        identifiers={(DOMAIN, "target:foo.yaml")},
    )
    fake_registry = SimpleNamespace(
        async_get=lambda did: fake_device if did == "d1" else None,
    )

    with patch("esphome_fleet.services.dr.async_get", return_value=fake_registry):
        hass = SimpleNamespace()
        result = _resolve_device_ids_to_targets(hass, ["d1", "d-unknown"])
    assert result == ["foo.yaml"]


async def test_compile_picks_worker_device_as_pin() -> None:
    """#63 — picking a worker device in the target selector pins the
    compile to that worker's client_id, falls back to 'all' targets.
    """
    hass, post = _hass_with_coordinator()

    worker_dev = SimpleNamespace(
        identifiers={(DOMAIN, "worker:abc-client")},
    )
    target_dev = SimpleNamespace(
        identifiers={(DOMAIN, "target:living-room.yaml")},
    )
    fake_registry = SimpleNamespace(
        async_get=lambda did: {"w1": worker_dev, "t1": target_dev}.get(did),
    )

    with patch("esphome_fleet.services.dr.async_get", return_value=fake_registry):
        # Target + worker picked together — targets from the target,
        # pin from the worker.
        await _handle_compile(
            _FakeCall(hass, {"device_id": ["t1", "w1"]})
        )
    _, payload = post.call_args.args
    assert payload["targets"] == ["living-room.yaml"]
    assert payload["pinned_client_id"] == "abc-client"


async def test_compile_worker_only_defaults_to_all_targets() -> None:
    """#63 — picking ONLY worker devices falls back to `targets: all`
    with the worker as pin. Lets users say "rebuild everything on
    this worker" with one picker action.
    """
    hass, post = _hass_with_coordinator()
    worker_dev = SimpleNamespace(
        identifiers={(DOMAIN, "worker:abc-client")},
    )
    fake_registry = SimpleNamespace(
        async_get=lambda did: worker_dev if did == "w1" else None,
    )

    with patch("esphome_fleet.services.dr.async_get", return_value=fake_registry):
        await _handle_compile(_FakeCall(hass, {"device_id": ["w1"]}))
    _, payload = post.call_args.args
    assert payload["targets"] == "all"
    assert payload["pinned_client_id"] == "abc-client"
