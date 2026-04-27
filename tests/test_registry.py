"""Unit tests for WorkerRegistry — register, heartbeat, disable, versioning."""

from __future__ import annotations

import pytest

from registry import WorkerRegistry


@pytest.fixture
def reg():
    return WorkerRegistry()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_register_returns_client_id(reg):
    client_id = reg.register("host1", "linux/amd64")
    assert client_id is not None
    assert len(client_id) > 0


def test_register_stores_client(reg):
    client_id = reg.register("host1", "linux/amd64")
    worker = reg.get(client_id)
    assert worker is not None
    assert worker.hostname == "host1"
    assert worker.platform == "linux/amd64"


def test_register_stores_client_version(reg):
    client_id = reg.register("host1", "linux/amd64", client_version="0.0.1")
    worker = reg.get(client_id)
    assert worker.client_version == "0.0.1"


def test_register_client_version_none_by_default(reg):
    client_id = reg.register("host1", "linux/amd64")
    worker = reg.get(client_id)
    assert worker.client_version is None


def test_register_stores_tags(reg):
    """TG.1: worker tags ride along with the in-memory Worker record."""
    client_id = reg.register("host1", "linux/amd64", tags=["prod", "linux"])
    worker = reg.get(client_id)
    assert worker.tags == ["prod", "linux"]


def test_register_tags_default_empty(reg):
    client_id = reg.register("host1", "linux/amd64")
    worker = reg.get(client_id)
    assert worker.tags == []


def test_register_tags_to_dict_includes_tags(reg):
    client_id = reg.register("host1", "linux/amd64", tags=["fast"])
    d = reg.get(client_id).to_dict()
    assert d["tags"] == ["fast"]


def test_set_tags_updates_in_memory(reg):
    client_id = reg.register("host1", "linux/amd64", tags=["prod"])
    assert reg.set_tags(client_id, ["staging", "fast"]) is True
    assert reg.get(client_id).tags == ["staging", "fast"]


def test_set_tags_unknown_returns_false(reg):
    assert reg.set_tags("unknown-id", ["a"]) is False


def test_register_re_register_with_tags_replaces(reg):
    """A worker re-registering with the same client_id and new tags keeps
    them — registration is the funnel through which the persistent
    WorkerTagStore decides what to write; whatever the registry receives
    is what the source of truth resolved to."""
    cid = reg.register("host1", "linux/amd64", tags=["prod"])
    reg.register("host1", "linux/amd64", existing_client_id=cid, tags=["staging"])
    assert reg.get(cid).tags == ["staging"]


def test_register_re_register_with_tags_none_preserves(reg):
    """Passing tags=None on re-register means "leave alone" (older worker
    versions that don't send the field still re-register fine)."""
    cid = reg.register("host1", "linux/amd64", tags=["prod"])
    reg.register("host1", "linux/amd64", existing_client_id=cid, tags=None)
    assert reg.get(cid).tags == ["prod"]


def test_register_multiple_clients_unique_ids(reg):
    id1 = reg.register("host1", "linux/amd64")
    id2 = reg.register("host2", "linux/amd64")
    assert id1 != id2


def test_get_all_returns_all_clients(reg):
    reg.register("host1", "linux/amd64")
    reg.register("host2", "linux/arm64")
    workers = reg.get_all()
    assert len(workers) == 2


# ---------------------------------------------------------------------------
# Heartbeat and online detection
# ---------------------------------------------------------------------------

def test_heartbeat_returns_true_for_known_client(reg):
    client_id = reg.register("host1", "linux/amd64")
    assert reg.heartbeat(client_id) is True


def test_heartbeat_returns_false_for_unknown_client(reg):
    assert reg.heartbeat("unknown-id") is False


def test_is_online_after_register(reg):
    client_id = reg.register("host1", "linux/amd64")
    assert reg.is_online(client_id, threshold_secs=30) is True


def test_is_online_unknown_client(reg):
    assert reg.is_online("unknown-id") is False


def test_is_online_respects_threshold(reg):
    client_id = reg.register("host1", "linux/amd64")
    worker = reg.get(client_id)
    # Backdate last_seen far into the past
    from datetime import datetime, timedelta, timezone
    worker.last_seen = datetime.now(timezone.utc) - timedelta(seconds=60)
    assert reg.is_online(client_id, threshold_secs=30) is False
    assert reg.is_online(client_id, threshold_secs=120) is True


# ---------------------------------------------------------------------------
# Disable / enable
# ---------------------------------------------------------------------------

def test_set_disabled_disables_client(reg):
    client_id = reg.register("host1", "linux/amd64")
    assert reg.set_disabled(client_id, True) is True
    worker = reg.get(client_id)
    assert worker.disabled is True


def test_set_disabled_enables_client(reg):
    client_id = reg.register("host1", "linux/amd64")
    reg.set_disabled(client_id, True)
    reg.set_disabled(client_id, False)
    worker = reg.get(client_id)
    assert worker.disabled is False


def test_set_disabled_returns_false_for_unknown(reg):
    assert reg.set_disabled("unknown-id", True) is False


def test_client_not_disabled_by_default(reg):
    client_id = reg.register("host1", "linux/amd64")
    worker = reg.get(client_id)
    assert worker.disabled is False


def test_disable_does_not_affect_online_status(reg):
    """Disabling a worker should not change is_online — it only affects job assignment."""
    client_id = reg.register("host1", "linux/amd64")
    reg.set_disabled(client_id, True)
    assert reg.is_online(client_id, threshold_secs=30) is True


# ---------------------------------------------------------------------------
# Current job tracking
# ---------------------------------------------------------------------------

def test_set_job_stores_job_id(reg):
    client_id = reg.register("host1", "linux/amd64")
    assert reg.set_job(client_id, "job-123") is True
    assert reg.get(client_id).current_job_id == "job-123"


def test_set_job_clears_job_id(reg):
    client_id = reg.register("host1", "linux/amd64")
    reg.set_job(client_id, "job-123")
    reg.set_job(client_id, None)
    assert reg.get(client_id).current_job_id is None


def test_set_job_returns_false_for_unknown(reg):
    assert reg.set_job("unknown-id", "job-123") is False


# ---------------------------------------------------------------------------
# to_dict serialization
# ---------------------------------------------------------------------------

def test_to_dict_includes_all_fields(reg):
    client_id = reg.register("host1", "linux/amd64", client_version="0.0.1")
    d = reg.get(client_id).to_dict()
    assert d["client_id"] == client_id
    assert d["hostname"] == "host1"
    assert d["platform"] == "linux/amd64"
    assert d["client_version"] == "0.0.1"
    assert d["disabled"] is False
    assert d["current_job_id"] is None
    assert "last_seen" in d
