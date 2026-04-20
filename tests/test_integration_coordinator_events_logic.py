"""HI.12 — coordinator state-transition event tests (HI.6)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from esphome_fleet.coordinator import EVENT_COMPILE_COMPLETE, EsphomeFleetCoordinator


def _coord_with_fake_hass() -> tuple[EsphomeFleetCoordinator, MagicMock]:
    """Build a coordinator instance without triggering real HA init.

    The coordinator's __init__ calls helpers that need an actual
    HomeAssistant object; since we only exercise `_fire_terminal_events`
    here we bypass __init__ entirely and seed the attributes the method
    actually reads.
    """
    fake_bus = MagicMock()
    fake_hass = SimpleNamespace(bus=fake_bus)
    coord = EsphomeFleetCoordinator.__new__(EsphomeFleetCoordinator)
    coord.hass = fake_hass  # type: ignore[assignment]
    coord._last_job_states = {}  # type: ignore[attr-defined]
    # DataUpdateCoordinator sets up `logger` in __init__; add a stub
    # so the debug log line in _fire_terminal_events doesn't blow up.
    import logging
    coord.logger = logging.getLogger("test-coord")  # type: ignore[assignment]
    return coord, fake_bus


def test_first_poll_does_not_fire_events_for_terminal_jobs() -> None:
    """HI.6: don't fire on startup snapshots — those are historical jobs."""
    coord, bus = _coord_with_fake_hass()
    queue = [
        {"id": "job-1", "state": "success", "target": "a.yaml"},
        {"id": "job-2", "state": "failed", "target": "b.yaml"},
    ]
    coord._fire_terminal_events(queue)
    bus.async_fire.assert_not_called()


def test_pending_to_success_fires_event_with_payload() -> None:
    coord, bus = _coord_with_fake_hass()
    # First poll: job is pending.
    coord._fire_terminal_events([
        {"id": "job-1", "state": "pending", "target": "a.yaml"},
    ])
    bus.async_fire.assert_not_called()

    # Second poll: job flipped to success.
    coord._fire_terminal_events([{
        "id": "job-1",
        "state": "success",
        "target": "a.yaml",
        "duration_seconds": 42,
        "esphome_version": "2026.3.2",
        "assigned_hostname": "build-box",
        "assigned_client_id": "abc",
        "scheduled": True,
        "schedule_kind": "recurring",
    }])
    bus.async_fire.assert_called_once()
    event_type, payload = bus.async_fire.call_args.args
    assert event_type == EVENT_COMPILE_COMPLETE
    assert payload == {
        "job_id": "job-1",
        "target": "a.yaml",
        "state": "success",
        "duration_seconds": 42,
        "esphome_version": "2026.3.2",
        "worker_hostname": "build-box",
        "worker_id": "abc",
        "scheduled": True,
        "schedule_kind": "recurring",
    }


def test_working_to_failed_fires_event() -> None:
    coord, bus = _coord_with_fake_hass()
    coord._fire_terminal_events([{"id": "j", "state": "working", "target": "x.yaml"}])
    coord._fire_terminal_events([{"id": "j", "state": "failed", "target": "x.yaml"}])
    assert bus.async_fire.call_count == 1
    assert bus.async_fire.call_args.args[1]["state"] == "failed"


def test_terminal_to_terminal_does_not_fire() -> None:
    """Once terminal, metadata-only changes (log field, etc.) don't re-fire."""
    coord, bus = _coord_with_fake_hass()
    # Establish as pending first so the first terminal transition DOES fire.
    coord._fire_terminal_events([{"id": "j", "state": "pending", "target": "x.yaml"}])
    coord._fire_terminal_events([{"id": "j", "state": "success", "target": "x.yaml"}])
    assert bus.async_fire.call_count == 1
    # Subsequent polls keep the same terminal state — should NOT re-fire.
    coord._fire_terminal_events([{"id": "j", "state": "success", "target": "x.yaml"}])
    coord._fire_terminal_events([{"id": "j", "state": "success", "target": "x.yaml"}])
    assert bus.async_fire.call_count == 1


def test_same_state_across_polls_does_not_fire() -> None:
    """WORKING across two consecutive polls isn't a transition."""
    coord, bus = _coord_with_fake_hass()
    coord._fire_terminal_events([{"id": "j", "state": "working", "target": "x.yaml"}])
    coord._fire_terminal_events([{"id": "j", "state": "working", "target": "x.yaml"}])
    bus.async_fire.assert_not_called()


def test_disappeared_jobs_removed_from_tracker() -> None:
    """Jobs that leave the queue shouldn't linger in _last_job_states forever."""
    coord, _ = _coord_with_fake_hass()
    coord._fire_terminal_events([
        {"id": "a", "state": "success", "target": "a.yaml"},
        {"id": "b", "state": "pending", "target": "b.yaml"},
    ])
    assert set(coord._last_job_states) == {"a", "b"}
    # Next poll: "a" disappears (user cleared it), "b" remains.
    coord._fire_terminal_events([{"id": "b", "state": "pending", "target": "b.yaml"}])
    assert set(coord._last_job_states) == {"b"}
