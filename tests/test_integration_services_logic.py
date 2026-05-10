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


def _hass_with_coordinator(
    targets_snapshot: list[dict] | None = None,
) -> tuple[SimpleNamespace, AsyncMock]:
    post = AsyncMock(return_value={"enqueued": 1, "cancelled": 1, "job_id": "j"})
    coordinator = SimpleNamespace(
        async_post_json=post,
        # 114: services that resolve tag expressions read this snapshot.
        # Default to an empty list so tests that don't set targets see
        # the same shape the coordinator exposes during a normal poll.
        data={"targets": targets_snapshot or []},
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    return hass, post


async def test_compile_service_posts_minimal_payload() -> None:
    hass, post = _hass_with_coordinator()
    await _handle_compile(_FakeCall(hass, {"targets": ["living-room.yaml"]}))
    post.assert_awaited_once()
    path, payload = post.call_args.args
    assert path == "/ui/api/compile"
    assert payload == {"targets": ["living-room.yaml"]}


async def test_compile_service_includes_version_when_set() -> None:
    hass, post = _hass_with_coordinator()
    await _handle_compile(
        _FakeCall(
            hass,
            {
                "targets": ["a.yaml", "b.yaml"],
                "esphome_version": "2026.3.2",
            },
        )
    )
    _, payload = post.call_args.args
    assert payload == {
        "targets": ["a.yaml", "b.yaml"],
        "esphome_version": "2026.3.2",
    }


async def test_compile_service_pins_worker_from_device_field() -> None:
    """#66 — the `worker` field is a worker device_id; resolve to client_id."""
    hass, post = _hass_with_coordinator()
    worker_dev = SimpleNamespace(
        identifiers={(DOMAIN, "worker:abc-client")},
    )
    fake_registry = SimpleNamespace(
        async_get=lambda did: worker_dev if did == "dev-worker-1" else None,
    )
    with patch("esphome_fleet.services.dr.async_get", return_value=fake_registry):
        await _handle_compile(
            _FakeCall(
                hass,
                {
                    "targets": ["a.yaml"],
                    "worker": "dev-worker-1",
                },
            )
        )
    _, payload = post.call_args.args
    assert payload == {
        "targets": ["a.yaml"],
        "pinned_client_id": "abc-client",
    }


async def test_compile_service_raises_when_worker_field_is_not_worker() -> None:
    """#66 — if someone wires a non-worker device into the `worker` field."""
    from homeassistant.exceptions import HomeAssistantError

    hass, _ = _hass_with_coordinator()
    target_dev = SimpleNamespace(
        identifiers={(DOMAIN, "target:foo.yaml")},
    )
    fake_registry = SimpleNamespace(async_get=lambda did: target_dev)
    with patch("esphome_fleet.services.dr.async_get", return_value=fake_registry):
        # QS.7 (1.6.1): exceptions carry a translation_key now —
        # assert on that instead of the message text so the test
        # doesn't need a hass fixture for string lookup.
        with pytest.raises(HomeAssistantError) as excinfo:
            await _handle_compile(
                _FakeCall(hass, {"targets": ["a.yaml"], "worker": "dev-x"})
            )
    assert excinfo.value.translation_key == "invalid_worker_device"


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
    """#37/#66 — picking a device that's known to HA but doesn't carry
    a `target:` Fleet identifier (e.g. the hub) raises. The service's
    ``target:`` filter in services.yaml should prevent this in the UI,
    but the handler defends against it regardless.
    """
    from homeassistant.exceptions import HomeAssistantError

    hass, _ = _hass_with_coordinator()

    fake_device = SimpleNamespace(
        identifiers={(DOMAIN, "hub:entry-xyz")},  # not a target
    )
    fake_registry = SimpleNamespace(
        async_get=lambda did: fake_device,
    )

    with patch("esphome_fleet.services.dr.async_get", return_value=fake_registry):
        with pytest.raises(HomeAssistantError) as excinfo:
            await _handle_compile(
                _FakeCall(hass, {"device_id": ["dev-456"]})
            )
    assert excinfo.value.translation_key == "no_managed_target_in_selection"


async def test_compile_raises_when_no_targets_and_no_devices() -> None:
    """#38 — calling compile with empty data gives a clear error."""
    from homeassistant.exceptions import HomeAssistantError

    hass, _ = _hass_with_coordinator()
    with pytest.raises(HomeAssistantError) as excinfo:
        await _handle_compile(_FakeCall(hass, {}))
    assert excinfo.value.translation_key == "no_target_selected"


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


# #63 tests removed in #66 — the "mix targets + workers in one picker"
# approach was replaced with separate picker fields. See
# test_compile_service_pins_worker_from_device_field for the new path.


# --- #64: schema validation + lifecycle ---

from esphome_fleet.services import (  # noqa: E402
    CANCEL_SCHEMA,
    COMPILE_SCHEMA,
    SERVICE_CANCEL,
    SERVICE_COMPILE,
    SERVICE_VALIDATE,
    VALIDATE_SCHEMA,
    async_register_services,
    async_unregister_services,
)
import voluptuous as vol  # noqa: E402


def test_compile_schema_accepts_target_injected_keys() -> None:
    """#53 — HA passes device_id/entity_id/etc. on every service call.
    The schema must not reject them.
    """
    # Common HA shapes: single string, list, None.
    data = {
        "device_id": ["dev-1"],
        "entity_id": None,
        "area_id": "living-room",
        "floor_id": [],
        "label_id": None,
    }
    # Doesn't raise — that's the assertion.
    COMPILE_SCHEMA(data)


def test_compile_schema_accepts_targets_list_and_all_sentinel() -> None:
    COMPILE_SCHEMA({"targets": ["foo.yaml", "bar.yaml"]})
    COMPILE_SCHEMA({"targets": "all"})
    COMPILE_SCHEMA({"targets": "outdated"})
    # cv.ensure_list wraps bare strings — plain "foo.yaml" is not valid
    # targets list (would be "outdated"/"all" only). But via ensure_list
    # wrapping, a single string becomes [string]:
    COMPILE_SCHEMA({"targets": "living-room.yaml"})  # wrapped to [string]


def test_compile_schema_rejects_dict_targets() -> None:
    """Targets must be a list of strings OR the `all`/`outdated` sentinels.
    cv.ensure_list will coerce a scalar (int/string) into a list, so
    the interesting rejection is a dict — which can't be list-ified.
    """
    import pytest
    with pytest.raises(vol.Invalid):
        COMPILE_SCHEMA({"targets": {"weird": "dict"}})


def test_compile_schema_all_fields_optional() -> None:
    """After #53 + #63, every field is optional — empty dict is valid
    (handler raises HomeAssistantError at runtime if nothing's pickable).
    """
    COMPILE_SCHEMA({})


def test_cancel_schema_requires_job_ids() -> None:
    import pytest
    with pytest.raises(vol.Invalid):
        CANCEL_SCHEMA({})
    CANCEL_SCHEMA({"job_ids": ["uuid-1", "uuid-2"]})
    # ensure_list wraps single strings
    CANCEL_SCHEMA({"job_ids": "just-one"})


def test_validate_schema_accepts_target_or_device_keys() -> None:
    VALIDATE_SCHEMA({"target": "foo.yaml"})
    VALIDATE_SCHEMA({"device_id": "dev-1"})
    VALIDATE_SCHEMA({})  # runtime check raises; schema is lenient


def test_async_register_services_registers_all_three() -> None:
    """Lifecycle: register_services installs compile, cancel, validate."""
    registered: dict[str, dict] = {}
    def has_service(domain, service):
        return service in registered
    def async_register(domain, service, handler, schema=None):
        registered[service] = {"handler": handler, "schema": schema, "domain": domain}
    def async_remove(domain, service):
        registered.pop(service, None)

    hass = SimpleNamespace(
        services=SimpleNamespace(
            has_service=has_service,
            async_register=async_register,
            async_remove=async_remove,
        ),
        data={DOMAIN: {}},
    )

    async_register_services(hass)
    assert set(registered.keys()) == {SERVICE_COMPILE, SERVICE_CANCEL, SERVICE_VALIDATE}
    for svc in (SERVICE_COMPILE, SERVICE_CANCEL, SERVICE_VALIDATE):
        assert registered[svc]["domain"] == DOMAIN
        assert registered[svc]["schema"] is not None
        assert callable(registered[svc]["handler"])


def test_async_register_services_is_idempotent() -> None:
    """Second register call is a no-op (has_service returns True)."""
    register_calls: list = []
    hass = SimpleNamespace(
        services=SimpleNamespace(
            has_service=lambda d, s: True,  # already registered
            async_register=lambda *a, **kw: register_calls.append(a),
        ),
        data={DOMAIN: {}},
    )
    async_register_services(hass)
    assert register_calls == []


def test_async_unregister_services_removes_when_domain_empty() -> None:
    """When the last config entry is gone, unregister tears services down."""
    removed: list[str] = []
    hass = SimpleNamespace(
        services=SimpleNamespace(
            has_service=lambda d, s: True,
            async_remove=lambda d, s: removed.append(s),
        ),
        data={},  # no DOMAIN key = no entries
    )
    async_unregister_services(hass)
    assert set(removed) == {SERVICE_COMPILE, SERVICE_CANCEL, SERVICE_VALIDATE}


def test_async_unregister_services_noop_when_entries_remain() -> None:
    """Don't tear down services if another config entry is still active."""
    removed: list[str] = []
    hass = SimpleNamespace(
        services=SimpleNamespace(
            has_service=lambda d, s: True,
            async_remove=lambda d, s: removed.append(s),
        ),
        data={DOMAIN: {"entry-2": "coordinator"}},
    )
    async_unregister_services(hass)
    assert removed == []


def test_services_yaml_parses() -> None:
    """#64 — services.yaml must be valid YAML with the expected structure.
    HA's frontend loads this file directly; a syntax error means the
    action editor shows no fields. Cheap CI guard.
    """
    from pathlib import Path
    import yaml
    path = Path(__file__).parent.parent / "ha-addon" / "custom_integration" / "esphome_fleet" / "services.yaml"
    data = yaml.safe_load(path.read_text())
    assert SERVICE_COMPILE in data
    assert SERVICE_CANCEL in data
    assert SERVICE_VALIDATE in data
    # Hassfest rule: ``target:`` must not carry integration or
    # manufacturer filters (those are Selector-only). Both services
    # ship bare ``target: {}`` — the runtime filter lives in
    # ``_resolve_device_ids_to_targets``, which only accepts devices
    # whose identifiers are under our DOMAIN.
    assert "target" in data[SERVICE_COMPILE]
    assert "target" in data[SERVICE_VALIDATE]
    # #66: compile exposes a separate `worker` device-selector field,
    # filtered to the worker manufacturer so stable/target devices hide.
    worker_field = data[SERVICE_COMPILE]["fields"]["worker"]
    worker_filter = worker_field["selector"]["device"]["filter"]
    assert any(f.get("manufacturer") == "Fleet for ESPHome Worker" for f in worker_filter)
    # #65: legacy `worker_id` string field is gone.
    assert "worker_id" not in data[SERVICE_COMPILE]["fields"]
    # 114: tag-expression fields are exposed on both compile and validate.
    assert "tags" in data[SERVICE_COMPILE]["fields"]
    assert "tags_op" in data[SERVICE_COMPILE]["fields"]
    assert "tags" in data[SERVICE_VALIDATE]["fields"]
    assert "tags_op" in data[SERVICE_VALIDATE]["fields"]


# --- 114: tag-expression service handlers ---

from esphome_fleet.services import _resolve_tags_to_targets  # noqa: E402


_TAG_TARGETS = [
    {"target": "office-a.yaml", "tags": "office,production"},
    {"target": "office-b.yaml", "tags": "office,staging"},
    {"target": "kitchen.yaml", "tags": "kitchen"},
    {"target": "untagged.yaml", "tags": None},
    {"target": "archived.yaml", "tags": "office", "archived": True},
]


def test_resolve_tags_any_of_default() -> None:
    coord = SimpleNamespace(data={"targets": _TAG_TARGETS})
    assert _resolve_tags_to_targets(coord, ["office"], "any_of") == [
        "office-a.yaml",
        "office-b.yaml",
    ]


def test_resolve_tags_all_of_intersects_required_tags() -> None:
    coord = SimpleNamespace(data={"targets": _TAG_TARGETS})
    assert _resolve_tags_to_targets(
        coord, ["office", "production"], "all_of"
    ) == ["office-a.yaml"]


def test_resolve_tags_none_of_excludes_tagged_devices() -> None:
    coord = SimpleNamespace(data={"targets": _TAG_TARGETS})
    # Devices that carry NEITHER `office` nor `kitchen` — only the
    # untagged row qualifies. Archived rows are dropped regardless.
    assert _resolve_tags_to_targets(
        coord, ["office", "kitchen"], "none_of"
    ) == ["untagged.yaml"]


def test_resolve_tags_skips_archived() -> None:
    coord = SimpleNamespace(data={"targets": _TAG_TARGETS})
    matches = _resolve_tags_to_targets(coord, ["office"], "any_of")
    assert "archived.yaml" not in matches


def test_resolve_tags_trims_and_drops_empty_tokens() -> None:
    coord = SimpleNamespace(data={"targets": _TAG_TARGETS})
    assert _resolve_tags_to_targets(coord, ["  office  ", ""], "any_of") == [
        "office-a.yaml",
        "office-b.yaml",
    ]


def test_resolve_tags_empty_input_returns_empty() -> None:
    coord = SimpleNamespace(data={"targets": _TAG_TARGETS})
    assert _resolve_tags_to_targets(coord, [], "any_of") == []
    assert _resolve_tags_to_targets(coord, ["   "], "any_of") == []


async def test_compile_service_resolves_tag_expression() -> None:
    """114 — tag expressions enqueue every matching target."""
    hass, post = _hass_with_coordinator(_TAG_TARGETS)
    await _handle_compile(_FakeCall(hass, {"tags": ["office"]}))
    _, payload = post.call_args.args
    assert payload == {"targets": ["office-a.yaml", "office-b.yaml"]}


async def test_compile_service_tags_with_all_of_op() -> None:
    hass, post = _hass_with_coordinator(_TAG_TARGETS)
    await _handle_compile(
        _FakeCall(hass, {"tags": ["office", "production"], "tags_op": "all_of"})
    )
    _, payload = post.call_args.args
    assert payload == {"targets": ["office-a.yaml"]}


async def test_compile_service_tags_zero_match_raises() -> None:
    from homeassistant.exceptions import HomeAssistantError

    hass, _ = _hass_with_coordinator(_TAG_TARGETS)
    with pytest.raises(HomeAssistantError) as excinfo:
        await _handle_compile(_FakeCall(hass, {"tags": ["nonexistent"]}))
    assert excinfo.value.translation_key == "no_targets_match_tags"


async def test_compile_service_device_picker_wins_over_tags() -> None:
    """Resolution precedence: device picker > tags > targets."""
    hass, post = _hass_with_coordinator(_TAG_TARGETS)
    fake_device = SimpleNamespace(
        identifiers={(DOMAIN, "target:specific.yaml")},
    )
    fake_registry = SimpleNamespace(async_get=lambda did: fake_device)
    with patch("esphome_fleet.services.dr.async_get", return_value=fake_registry):
        await _handle_compile(
            _FakeCall(
                hass,
                {"device_id": ["dev-1"], "tags": ["office"]},
            )
        )
    _, payload = post.call_args.args
    assert payload == {"targets": ["specific.yaml"]}


async def test_validate_service_resolves_single_tag_match() -> None:
    hass, post = _hass_with_coordinator(_TAG_TARGETS)
    await _handle_validate(_FakeCall(hass, {"tags": ["kitchen"]}))
    _, payload = post.call_args.args
    assert payload == {"target": "kitchen.yaml"}


async def test_validate_service_tags_multi_match_raises() -> None:
    from homeassistant.exceptions import HomeAssistantError

    hass, _ = _hass_with_coordinator(_TAG_TARGETS)
    with pytest.raises(HomeAssistantError) as excinfo:
        await _handle_validate(_FakeCall(hass, {"tags": ["office"]}))
    assert excinfo.value.translation_key == "tags_match_multiple"


async def test_validate_service_tags_zero_match_raises() -> None:
    from homeassistant.exceptions import HomeAssistantError

    hass, _ = _hass_with_coordinator(_TAG_TARGETS)
    with pytest.raises(HomeAssistantError) as excinfo:
        await _handle_validate(_FakeCall(hass, {"tags": ["nonexistent"]}))
    assert excinfo.value.translation_key == "no_targets_match_tags"


def test_compile_schema_accepts_tags_and_op() -> None:
    COMPILE_SCHEMA({"tags": ["office", "production"], "tags_op": "all_of"})
    COMPILE_SCHEMA({"tags": ["office"]})  # tags_op defaults at handler level


def test_compile_schema_rejects_unknown_tags_op() -> None:
    import pytest
    with pytest.raises(vol.Invalid):
        COMPILE_SCHEMA({"tags": ["x"], "tags_op": "weird_op"})


def test_validate_schema_accepts_tags() -> None:
    VALIDATE_SCHEMA({"tags": ["office"], "tags_op": "any_of"})
