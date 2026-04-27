"""Tests for TG.1 — worker tag persistence + env-var seed.

The store maps a worker identity (hostname; falls back to a stable
``worker_id`` for the rare hostname-collision case) to a list of tag
strings. Tags travel with the docker invocation only on the
*first* registration; thereafter the persistent server-side entry
wins so the user can edit a worker's tags from the UI without the
worker's env clobbering them on the next restart. The
``WORKER_TAGS_OVERWRITE`` knob (set as a flag on the registration
payload) restores the old "env always wins" behaviour for scripted
multi-worker deployments.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worker_tags import WorkerTagStore


@pytest.fixture
def store(tmp_path: Path) -> WorkerTagStore:
    return WorkerTagStore(path=tmp_path / "worker-tags.json")


# ---------------------------------------------------------------------------
# load_or_seed — first-time seed vs. server-side wins vs. overwrite
# ---------------------------------------------------------------------------


def test_load_or_seed_first_time_persists_tags(store: WorkerTagStore, tmp_path: Path) -> None:
    tags = store.load_or_seed("host-1", ["prod", "linux"], overwrite=False)
    assert tags == ["prod", "linux"]
    saved = json.loads((tmp_path / "worker-tags.json").read_text())
    assert saved["tags"]["host-1"] == ["prod", "linux"]


def test_load_or_seed_server_side_wins_after_first_registration(store: WorkerTagStore) -> None:
    store.load_or_seed("host-1", ["prod"], overwrite=False)
    # Worker re-registers later with a different env — server keeps the original.
    tags = store.load_or_seed("host-1", ["staging"], overwrite=False)
    assert tags == ["prod"]


def test_load_or_seed_overwrite_clobbers(store: WorkerTagStore) -> None:
    store.load_or_seed("host-1", ["prod"], overwrite=False)
    tags = store.load_or_seed("host-1", ["staging", "rebuild"], overwrite=True)
    assert tags == ["staging", "rebuild"]


def test_load_or_seed_overwrite_with_empty_clears(store: WorkerTagStore) -> None:
    """``WORKER_TAGS_OVERWRITE=1`` with no ``WORKER_TAGS`` clears the entry."""
    store.load_or_seed("host-1", ["prod", "linux"], overwrite=False)
    tags = store.load_or_seed("host-1", [], overwrite=True)
    assert tags == []
    assert store.get_tags("host-1") == []


def test_load_or_seed_first_time_with_no_tags_returns_empty(store: WorkerTagStore) -> None:
    """Worker with no ``WORKER_TAGS`` env on first registration → empty, persisted."""
    tags = store.load_or_seed("host-1", None, overwrite=False)
    assert tags == []
    # An entry now exists for host-1 — subsequent registrations don't reseed.
    tags2 = store.load_or_seed("host-1", ["late"], overwrite=False)
    assert tags2 == []


def test_load_or_seed_existing_entry_no_payload_keeps_existing(store: WorkerTagStore) -> None:
    store.load_or_seed("host-1", ["prod"], overwrite=False)
    # Worker re-registers without sending tags (older worker version).
    tags = store.load_or_seed("host-1", None, overwrite=False)
    assert tags == ["prod"]


# ---------------------------------------------------------------------------
# Persistence across instances
# ---------------------------------------------------------------------------


def test_persistence_across_instances(tmp_path: Path) -> None:
    s1 = WorkerTagStore(path=tmp_path / "worker-tags.json")
    s1.load_or_seed("host-1", ["prod"], overwrite=False)

    s2 = WorkerTagStore(path=tmp_path / "worker-tags.json")
    assert s2.get_tags("host-1") == ["prod"]


def test_corrupt_file_yields_empty_store(tmp_path: Path) -> None:
    path = tmp_path / "worker-tags.json"
    path.write_text("{not valid json")
    s = WorkerTagStore(path=path)
    assert s.get_tags("anyone") == []
    # Recovery still allows new seeds.
    assert s.load_or_seed("host-1", ["prod"], overwrite=False) == ["prod"]


def test_missing_file_yields_empty_store(tmp_path: Path) -> None:
    s = WorkerTagStore(path=tmp_path / "does-not-exist.json")
    assert s.get_tags("anyone") == []


def test_unknown_schema_version_resets_safely(tmp_path: Path) -> None:
    path = tmp_path / "worker-tags.json"
    path.write_text(json.dumps({"version": 999, "tags": {"host-1": ["prod"]}}))
    s = WorkerTagStore(path=path)
    # Unknown version → treat as empty rather than guessing at a future schema.
    assert s.get_tags("host-1") == []


# ---------------------------------------------------------------------------
# set_tags (authoritative UI edit path — wired by TG.4 later)
# ---------------------------------------------------------------------------


def test_set_tags_authoritative(store: WorkerTagStore) -> None:
    store.load_or_seed("host-1", ["prod"], overwrite=False)
    result = store.set_tags("host-1", ["fast", "linux"])
    assert result == ["fast", "linux"]
    assert store.get_tags("host-1") == ["fast", "linux"]


def test_set_tags_creates_entry_for_unknown_identity(store: WorkerTagStore) -> None:
    result = store.set_tags("brand-new", ["a"])
    assert result == ["a"]
    assert store.get_tags("brand-new") == ["a"]


def test_get_tags_unknown_returns_empty(store: WorkerTagStore) -> None:
    assert store.get_tags("unknown") == []


# ---------------------------------------------------------------------------
# Normalisation — trim / drop empties / dedupe (preserve order)
# ---------------------------------------------------------------------------


def test_normalise_trims_drops_empties_and_dedupes(store: WorkerTagStore) -> None:
    tags = store.load_or_seed("host-1", [" prod ", "prod", "linux", ""], overwrite=False)
    # Trim whitespace, drop empty strings, dedupe (case-sensitive); keep first-seen order.
    assert tags == ["prod", "linux"]


def test_normalise_set_tags(store: WorkerTagStore) -> None:
    result = store.set_tags("host-1", ["  a  ", "b", "a"])
    assert result == ["a", "b"]


# ---------------------------------------------------------------------------
# all_tags helper — fleet-wide tag pool (used by UI autocomplete in TG.7)
# ---------------------------------------------------------------------------


def test_all_tags_returns_union(store: WorkerTagStore) -> None:
    store.set_tags("host-1", ["prod", "linux"])
    store.set_tags("host-2", ["prod", "macos"])
    store.set_tags("host-3", [])
    assert store.all_tags() == ["linux", "macos", "prod"]
