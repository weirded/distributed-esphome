"""#197 — every UI-driven file op must leave the git working tree clean.

Locks in the invariant the user named "no dangling files in git": after
any endpoint that writes, renames, archives, restores, or deletes a
file under ``/config/esphome/``, ``git status --porcelain`` (via
``git_versioning.dirty_paths``) must come back empty once the debounced
commit pipeline has drained.

This is the regression net for the ``deleted: <archived>`` class of bug
fixed in #94 (delete-from-archive used to bypass the git layer) and the
broader concern that a future endpoint adds a write but forgets the
matching ``commit_file`` call.

Each scenario:
    1. Boots a fresh UI test app on a git-versioned config dir.
    2. Drives one endpoint to perform exactly one file mutation.
    3. Awaits ``drain_pending_commits`` so debounced commits land.
    4. Asserts the tree is clean.

If a new file-mutating endpoint lands without a commit hook, add a
scenario here — the assertion will catch the gap.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import git_versioning as gv
from test_ui_api import _UiApp, _make_ui_app, _write_config  # type: ignore


@pytest.fixture
def _enable_socket():
    try:
        import pytest_socket as _pytest_socket  # type: ignore[import-not-found]
    except ImportError:
        yield
        return
    _pytest_socket.enable_socket()
    yield


async def _make_versioned_app(tmp_path: Path) -> _UiApp:
    """UI app with a fresh git repo + versioning_enabled=on."""
    gv._reset_for_tests()
    ta = await _make_ui_app(tmp_path)
    # _make_ui_app already flips versioning_enabled='on'; init the repo
    # explicitly because the test app skips main.py's startup hook.
    gv.init_repo(ta.config_dir)
    return ta


async def _seed_committed_target(ta: _UiApp, filename: str = "device1.yaml", name: str = "device1") -> None:
    """Write a YAML, save it via the API so it lands in a commit, drain."""
    _write_config(ta.config_dir, filename, name)
    # Drive a real commit so the file is tracked at HEAD before each
    # scenario mutates it. Bypassing the API here would leave the file
    # untracked and conflate the seed-state with the op under test.
    await gv.commit_file(ta.config_dir, filename, "seed")
    await gv.drain_pending_commits()
    assert gv.dirty_paths(ta.config_dir) == set(), \
        f"seed left tree dirty: {gv.dirty_paths(ta.config_dir)}"


async def _assert_clean(ta: _UiApp) -> None:
    await gv.drain_pending_commits()
    dirty = gv.dirty_paths(ta.config_dir)
    assert dirty == set(), f"working tree dirty after op: {dirty}"


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


async def test_save_target_content_leaves_tree_clean(tmp_path, _enable_socket):
    ta = await _make_versioned_app(tmp_path)
    try:
        await _seed_committed_target(ta)
        new_content = "esphome:\n  name: device1\n\nesp32:\n  board: esp32dev\n"
        resp = await ta.post(
            "/ui/api/targets/device1.yaml/content",
            json={"content": new_content},
        )
        assert resp.status == 200
        await _assert_clean(ta)
    finally:
        gv._reset_for_tests()
        await ta.close()


async def test_create_then_save_target_leaves_tree_clean(tmp_path, _enable_socket):
    """Create-staged + save flow: the .pending.* dotfile is replaced by
    the final file inside the same logical operation; both the deletion
    of the staged file and the addition of the final file must land in
    the same commit boundary so no dotfile dangles."""
    ta = await _make_versioned_app(tmp_path)
    try:
        resp = await ta.post(
            "/ui/api/targets",
            json={"filename": "newdev"},
        )
        assert resp.status == 200
        body = await resp.json()
        staged = body["target"]
        assert staged.startswith(".pending.")

        # Save the staged file, which renames .pending.newdev.yaml → newdev.yaml.
        save = await ta.post(
            f"/ui/api/targets/{staged}/content",
            json={"content": "esphome:\n  name: newdev\n\nesp32:\n  board: esp32dev\n"},
        )
        assert save.status == 200
        await _assert_clean(ta)
    finally:
        gv._reset_for_tests()
        await ta.close()


async def test_archive_target_leaves_tree_clean(tmp_path, _enable_socket):
    ta = await _make_versioned_app(tmp_path)
    try:
        await _seed_committed_target(ta)
        resp = await ta.delete("/ui/api/targets/device1.yaml")
        assert resp.status == 200
        assert (ta.config_dir / ".archive" / "device1.yaml").exists()
        await _assert_clean(ta)
    finally:
        gv._reset_for_tests()
        await ta.close()


async def test_permanent_delete_leaves_tree_clean(tmp_path, _enable_socket):
    ta = await _make_versioned_app(tmp_path)
    try:
        await _seed_committed_target(ta)
        resp = await ta.delete("/ui/api/targets/device1.yaml?archive=false")
        assert resp.status == 200
        assert not (ta.config_dir / "device1.yaml").exists()
        await _assert_clean(ta)
    finally:
        gv._reset_for_tests()
        await ta.close()


async def test_restore_from_archive_leaves_tree_clean(tmp_path, _enable_socket):
    """#63 archive_and_commit + restore_and_commit pair via git mv —
    both the archive and the restore commits must clean the tree."""
    ta = await _make_versioned_app(tmp_path)
    try:
        await _seed_committed_target(ta)
        # Archive first so there's something to restore.
        archived = await ta.delete("/ui/api/targets/device1.yaml")
        assert archived.status == 200
        await _assert_clean(ta)

        restored = await ta.post("/ui/api/archive/device1.yaml/restore")
        assert restored.status == 200
        assert (ta.config_dir / "device1.yaml").exists()
        assert not (ta.config_dir / ".archive" / "device1.yaml").exists()
        await _assert_clean(ta)
    finally:
        gv._reset_for_tests()
        await ta.close()


async def test_permanent_delete_from_archive_leaves_tree_clean(tmp_path, _enable_socket):
    """#94 regression guard: pre-fix, this path used a bare ``os.unlink``
    and left a ``deleted: .archive/<f>`` row in working-tree until some
    unrelated commit swept it up. The new code routes through
    ``delete_archived_and_commit`` which must finish cleanly."""
    ta = await _make_versioned_app(tmp_path)
    try:
        await _seed_committed_target(ta)
        archived = await ta.delete("/ui/api/targets/device1.yaml")
        assert archived.status == 200
        await _assert_clean(ta)

        deleted = await ta.delete("/ui/api/archive/device1.yaml")
        assert deleted.status == 200
        assert not (ta.config_dir / ".archive" / "device1.yaml").exists()
        await _assert_clean(ta)
    finally:
        gv._reset_for_tests()
        await ta.close()


async def test_rename_target_leaves_tree_clean(tmp_path, _enable_socket):
    """Rename writes the new file and unlinks the old; both halves must
    show up in commits so neither path lingers as dirty."""
    ta = await _make_versioned_app(tmp_path)
    try:
        await _seed_committed_target(ta)
        resp = await ta.post(
            "/ui/api/targets/device1.yaml/rename",
            json={"new_name": "renamed-dev"},
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["new_filename"] == "renamed-dev.yaml"
        await _assert_clean(ta)
    finally:
        gv._reset_for_tests()
        await ta.close()


async def test_pin_then_unpin_leaves_tree_clean(tmp_path, _enable_socket):
    ta = await _make_versioned_app(tmp_path)
    try:
        await _seed_committed_target(ta)
        pinned = await ta.post(
            "/ui/api/targets/device1.yaml/pin",
            json={"version": "2026.3.3"},
        )
        assert pinned.status == 200
        await _assert_clean(ta)

        unpinned = await ta.delete("/ui/api/targets/device1.yaml/pin")
        assert unpinned.status == 200
        await _assert_clean(ta)
    finally:
        gv._reset_for_tests()
        await ta.close()


async def test_meta_update_leaves_tree_clean(tmp_path, _enable_socket):
    ta = await _make_versioned_app(tmp_path)
    try:
        await _seed_committed_target(ta)
        resp = await ta.post(
            "/ui/api/targets/device1.yaml/meta",
            json={"tags": "office, indoor"},
        )
        assert resp.status == 200
        await _assert_clean(ta)
    finally:
        gv._reset_for_tests()
        await ta.close()


async def test_schedule_set_then_clear_leaves_tree_clean(tmp_path, _enable_socket):
    ta = await _make_versioned_app(tmp_path)
    try:
        await _seed_committed_target(ta)
        scheduled = await ta.post(
            "/ui/api/targets/device1.yaml/schedule",
            json={"cron": "0 2 * * 0"},
        )
        assert scheduled.status == 200
        await _assert_clean(ta)

        cleared = await ta.delete("/ui/api/targets/device1.yaml/schedule")
        assert cleared.status == 200
        await _assert_clean(ta)
    finally:
        gv._reset_for_tests()
        await ta.close()


async def test_secrets_yaml_edit_does_not_dirty_tree(tmp_path, _enable_socket):
    """Editing secrets.yaml must NOT leave the working tree dirty.

    secrets.yaml is in :data:`git_versioning.GITIGNORE_ENTRIES` because
    it carries plaintext credentials and we don't want to commit those.
    The save endpoint still calls ``commit_file`` on it (the endpoint
    doesn't know which files are gitignored), so the safety relies on
    the gitignore + ``git add --all`` skipping ignored paths. This test
    locks that combination in place — if a future change drops
    secrets.yaml from the ignore list, this test fails immediately
    rather than letting the leak slip into a release.
    """
    ta = await _make_versioned_app(tmp_path)
    try:
        await _seed_committed_target(ta)
        resp = await ta.post(
            "/ui/api/targets/secrets.yaml/content",
            json={"content": "wifi_password: rotated\n"},
        )
        assert resp.status == 200
        # File on disk got the new content but git status must stay
        # silent because secrets.yaml is ignored.
        assert (ta.config_dir / "secrets.yaml").read_text() == "wifi_password: rotated\n"
        await _assert_clean(ta)
    finally:
        gv._reset_for_tests()
        await ta.close()


# ---------------------------------------------------------------------------
# Negative control — the assertion *can* fire, so a forgotten commit_file
# in some future endpoint won't be silently rationalised away.
# ---------------------------------------------------------------------------


async def test_external_edit_without_commit_does_dirty_tree(tmp_path, _enable_socket):
    """If we bypass the API and edit a tracked file directly, the tree
    DOES go dirty — confirms ``dirty_paths`` is actually observing
    something. Without this, every other test in the file could pass
    just because ``dirty_paths`` was always returning empty by mistake.
    """
    ta = await _make_versioned_app(tmp_path)
    try:
        await _seed_committed_target(ta)
        (ta.config_dir / "device1.yaml").write_text("# external edit\n")
        # No commit_file, no drain — just check git sees the change.
        assert "device1.yaml" in gv.dirty_paths(ta.config_dir)
    finally:
        gv._reset_for_tests()
        await ta.close()
