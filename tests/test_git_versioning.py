"""Unit tests for AV.* — local git-backed auto-versioning.

Covers:
- init_repo on a fresh dir creates .git + .gitignore + initial commit.
- init_repo on an existing git repo skips init (leaves .git intact) but
  appends missing .gitignore entries.
- commit_file is a no-op when settings.auto_commit_on_save is False.
- commit_file debounces: rapid back-to-back calls coalesce into one
  commit with the last action's message.
- commit_file gracefully tolerates a non-repo target (logs, no crash).
- get_head returns HEAD hash after a commit.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import pytest

import git_versioning as gv
import settings as settings_mod


@pytest.fixture(autouse=True)
def _reset_modules(tmp_path: Path):
    """Clean module state + wire settings to a scratch file per test."""
    gv._reset_for_tests()
    settings_mod._reset_for_tests()
    settings_mod.init_settings(
        settings_path=tmp_path / "settings.json",
        options_path=tmp_path / "options.json",
    )
    yield
    gv._reset_for_tests()
    settings_mod._reset_for_tests()


def _make_config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    (d / "living-room.yaml").write_text("esphome:\n  name: living-room\n")
    return d


def _has_commits(repo: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _log_messages(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "log", "--format=%s"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _log_count(repo: Path) -> int:
    return len(_log_messages(repo))


# ---------------------------------------------------------------------------
# init_repo
# ---------------------------------------------------------------------------


def test_init_repo_creates_git_and_initial_commit(tmp_path: Path):
    d = _make_config_dir(tmp_path)
    gv.init_repo(d)

    assert (d / ".git").is_dir()
    assert (d / ".gitignore").is_file()
    assert "secrets.yaml" in (d / ".gitignore").read_text()
    assert ".esphome/" in (d / ".gitignore").read_text()

    messages = _log_messages(d)
    assert len(messages) == 1
    assert "Initial commit by distributed-esphome" in messages[0]


def test_init_repo_is_idempotent_on_existing_repo(tmp_path: Path):
    d = _make_config_dir(tmp_path)
    # Pre-seed as a user's own git repo with a manual commit.
    subprocess.run(["git", "init", "-b", "main"], cwd=str(d), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "User"], cwd=str(d), check=True)
    subprocess.run(["git", "config", "user.email", "u@x.com"], cwd=str(d), check=True)
    # Leave .gitignore missing on purpose — we should append to it.
    subprocess.run(["git", "add", "-A"], cwd=str(d), check=True)
    subprocess.run(["git", "commit", "-m", "user's own initial"], cwd=str(d), check=True, capture_output=True)

    gv.init_repo(d)

    # Still only the user's commit — we didn't add our own.
    messages = _log_messages(d)
    assert messages == ["user's own initial"]
    # But .gitignore now has our entries.
    gi = (d / ".gitignore").read_text()
    assert "secrets.yaml" in gi
    assert ".esphome/" in gi


def test_init_repo_appends_only_missing_gitignore_entries(tmp_path: Path):
    d = _make_config_dir(tmp_path)
    (d / ".gitignore").write_text("secrets.yaml\n# my own comment\nmy-ignored-dir/\n")

    gv.init_repo(d)

    gi = (d / ".gitignore").read_text()
    # Existing lines preserved verbatim.
    assert "# my own comment" in gi
    assert "my-ignored-dir/" in gi
    # secrets.yaml already present — not duplicated.
    assert gi.count("secrets.yaml") == 1
    # Missing entry appended.
    assert ".esphome/" in gi


def test_init_repo_tolerates_missing_config_dir(tmp_path: Path, caplog):
    nonexistent = tmp_path / "does-not-exist"
    with caplog.at_level("WARNING"):
        gv.init_repo(nonexistent)
    assert any("does not exist" in r.message for r in caplog.records)


def test_init_repo_swallows_git_errors(tmp_path: Path, monkeypatch, caplog):
    """If git isn't on PATH we log and move on, never crash startup."""
    d = _make_config_dir(tmp_path)
    # Point subprocess at a guaranteed-missing binary by emptying PATH.
    monkeypatch.setenv("PATH", "/nonexistent-path-for-test")
    with caplog.at_level("ERROR"):
        gv.init_repo(d)
    # No .git was created.
    assert not (d / ".git").exists()


# ---------------------------------------------------------------------------
# commit_file
# ---------------------------------------------------------------------------


async def test_commit_file_is_noop_when_disabled(tmp_path: Path):
    d = _make_config_dir(tmp_path)
    gv.init_repo(d)
    baseline = _log_count(d)

    await settings_mod.update_settings({"auto_commit_on_save": False})
    # Modify the file so a commit would actually happen if enabled.
    (d / "living-room.yaml").write_text("esphome:\n  name: living-room\n# edit\n")
    await gv.commit_file(d, "living-room.yaml", "save")
    await gv.drain_pending_commits()

    assert _log_count(d) == baseline


async def test_commit_file_produces_a_commit(tmp_path: Path):
    d = _make_config_dir(tmp_path)
    gv.init_repo(d)
    baseline = _log_count(d)

    # Shrink debounce so the test doesn't sit in sleep().
    old = gv.DEBOUNCE_SECONDS
    gv.DEBOUNCE_SECONDS = 0.05
    try:
        (d / "living-room.yaml").write_text("esphome:\n  name: living-room\n# edit\n")
        await gv.commit_file(d, "living-room.yaml", "save")
        await gv.drain_pending_commits()
    finally:
        gv.DEBOUNCE_SECONDS = old

    messages = _log_messages(d)
    assert len(messages) == baseline + 1
    assert messages[0] == "save: living-room.yaml"


async def test_commit_file_debounces_coalesces_rapid_calls(tmp_path: Path):
    """Fast sequence of calls collapses into one commit with the last action."""
    d = _make_config_dir(tmp_path)
    gv.init_repo(d)
    baseline = _log_count(d)

    old = gv.DEBOUNCE_SECONDS
    gv.DEBOUNCE_SECONDS = 0.15
    try:
        (d / "living-room.yaml").write_text("a\n")
        await gv.commit_file(d, "living-room.yaml", "save")
        await asyncio.sleep(0.02)
        (d / "living-room.yaml").write_text("a\nb\n")
        await gv.commit_file(d, "living-room.yaml", "pin")
        await asyncio.sleep(0.02)
        (d / "living-room.yaml").write_text("a\nb\nc\n")
        await gv.commit_file(d, "living-room.yaml", "schedule")
        await gv.drain_pending_commits()
    finally:
        gv.DEBOUNCE_SECONDS = old

    messages = _log_messages(d)
    assert len(messages) == baseline + 1
    # Last caller's action wins — matches how a human thinks about
    # "one edit session".
    assert messages[0] == "schedule: living-room.yaml"


async def test_commit_file_unrelated_paths_each_get_their_own_commit(tmp_path: Path):
    d = _make_config_dir(tmp_path)
    (d / "bedroom.yaml").write_text("esphome:\n  name: bedroom\n")
    gv.init_repo(d)
    baseline = _log_count(d)

    old = gv.DEBOUNCE_SECONDS
    gv.DEBOUNCE_SECONDS = 0.05
    try:
        (d / "living-room.yaml").write_text("edit 1\n")
        await gv.commit_file(d, "living-room.yaml", "save")
        (d / "bedroom.yaml").write_text("edit 2\n")
        await gv.commit_file(d, "bedroom.yaml", "save")
        await gv.drain_pending_commits()
    finally:
        gv.DEBOUNCE_SECONDS = old

    assert _log_count(d) == baseline + 2


async def test_commit_file_on_non_repo_dir_is_safe(tmp_path: Path, caplog):
    """If init never ran (or was nuked) commit_file must not crash."""
    d = _make_config_dir(tmp_path)
    # No init_repo — no .git/.

    old = gv.DEBOUNCE_SECONDS
    gv.DEBOUNCE_SECONDS = 0.02
    try:
        with caplog.at_level("DEBUG"):
            await gv.commit_file(d, "living-room.yaml", "save")
            await gv.drain_pending_commits()
    finally:
        gv.DEBOUNCE_SECONDS = old
    assert not (d / ".git").exists()


# ---------------------------------------------------------------------------
# get_head (groundwork for AV.7)
# ---------------------------------------------------------------------------


def test_get_head_returns_sha_after_init(tmp_path: Path):
    d = _make_config_dir(tmp_path)
    gv.init_repo(d)
    head = gv.get_head(d)
    assert head is not None
    assert len(head) == 40  # full sha
    assert all(c in "0123456789abcdef" for c in head)


def test_get_head_on_non_repo_returns_none(tmp_path: Path):
    d = tmp_path / "not-a-repo"
    d.mkdir()
    assert gv.get_head(d) is None
