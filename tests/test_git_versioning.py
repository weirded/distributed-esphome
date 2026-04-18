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
def _reset_modules(tmp_path: Path, monkeypatch):
    """Clean module state + wire settings to a scratch file per test.

    We also scrub the git identity env so the developer's ambient
    ``~/.gitconfig`` doesn't leak into ``_has_user_identity`` probes —
    on CI / hass-4 there's no global config anyway, and that's the
    behaviour these tests care about.
    """
    gv._reset_for_tests()
    settings_mod._reset_for_tests()
    settings_mod.init_settings(
        settings_path=tmp_path / "settings.json",
        options_path=tmp_path / "options.json",
    )
    for var in (
        "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.delenv(var, raising=False)
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(fake_home / ".gitconfig-nonexistent"))
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


def test_init_repo_leaves_preexisting_repo_alone(tmp_path: Path):
    """Pre-existing user repo: no new commit, no .gitignore touch."""
    d = _make_config_dir(tmp_path)
    # Pre-seed as a user's own git repo with their own curated gitignore.
    subprocess.run(["git", "init", "-b", "main"], cwd=str(d), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "User"], cwd=str(d), check=True)
    subprocess.run(["git", "config", "user.email", "u@x.com"], cwd=str(d), check=True)
    (d / ".gitignore").write_text("/.esphome/\n**/.pioenvs/\n")  # user's curated set
    original_gitignore = (d / ".gitignore").read_text()
    subprocess.run(["git", "add", "-A"], cwd=str(d), check=True)
    subprocess.run(["git", "commit", "-m", "user's own initial"], cwd=str(d), check=True, capture_output=True)

    gv.init_repo(d)

    # Only the user's commit — we didn't add our own.
    messages = _log_messages(d)
    assert messages == ["user's own initial"]
    # .gitignore is byte-identical — we never touch a pre-existing
    # user's curated gitignore, even if our safety-net entries are
    # missing. Respects Pat-with-git's autonomy.
    assert (d / ".gitignore").read_text() == original_gitignore


def test_init_repo_writes_gitignore_on_fresh_init_only(tmp_path: Path):
    """Fresh Fleet-init: .gitignore is created with safety-net entries.

    Pre-existing repos (see the separate test) get left alone.
    """
    d = _make_config_dir(tmp_path)

    gv.init_repo(d)

    gi = (d / ".gitignore").read_text()
    assert "secrets.yaml" in gi
    assert ".esphome/" in gi


def test_init_repo_uses_smart_gitignore_on_fresh_init(tmp_path: Path):
    """Fresh init: if there's somehow a pre-existing .gitignore (not a repo
    yet), we still recognise equivalent forms and don't duplicate lines."""
    d = _make_config_dir(tmp_path)
    # Not a git repo yet — but somebody dropped a .gitignore in the dir.
    (d / ".gitignore").write_text("/.esphome/\n/secrets.yaml\n")
    original = (d / ".gitignore").read_text()

    gv.init_repo(d)

    # Leading-slash forms cover our safety-net entries; no append.
    assert (d / ".gitignore").read_text() == original


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


async def test_commit_file_respects_preexisting_user_identity(tmp_path: Path):
    """Hass-4 regression: a pre-existing repo's user.name/email must survive.

    Before the fix, ``_do_commit`` passed ``-c user.name=HA User`` on
    every commit, which stomped the user's own identity on any
    pre-existing repo. Now commits pick up whatever the repo / user
    / system config resolves to.
    """
    d = _make_config_dir(tmp_path)
    subprocess.run(["git", "init", "-b", "main"], cwd=str(d), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Stefan Zier"], cwd=str(d), check=True)
    subprocess.run(["git", "config", "user.email", "stefan@zier.com"], cwd=str(d), check=True)
    subprocess.run(["git", "add", "-A"], cwd=str(d), check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial checkin"],
        cwd=str(d),
        check=True,
        capture_output=True,
    )

    gv.init_repo(d)  # pre-existing path — must not touch identity.

    old = gv.DEBOUNCE_SECONDS
    gv.DEBOUNCE_SECONDS = 0.05
    try:
        (d / "living-room.yaml").write_text("edited\n")
        await gv.commit_file(d, "living-room.yaml", "save")
        await gv.drain_pending_commits()
    finally:
        gv.DEBOUNCE_SECONDS = old

    # Grab the author of the top commit.
    result = subprocess.run(
        ["git", "log", "--format=%an <%ae>", "-1"],
        cwd=str(d),
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "Stefan Zier <stefan@zier.com>"


async def test_commit_file_uses_fleet_identity_on_fresh_init(tmp_path: Path):
    """Fresh Fleet-init repo uses Settings-driven identity for commits."""
    d = _make_config_dir(tmp_path)
    gv.init_repo(d)

    old = gv.DEBOUNCE_SECONDS
    gv.DEBOUNCE_SECONDS = 0.05
    try:
        (d / "living-room.yaml").write_text("edited\n")
        await gv.commit_file(d, "living-room.yaml", "save")
        await gv.drain_pending_commits()
    finally:
        gv.DEBOUNCE_SECONDS = old

    result = subprocess.run(
        ["git", "log", "--format=%an <%ae>", "-1"],
        cwd=str(d),
        capture_output=True,
        text=True,
        check=True,
    )
    # Default AppSettings values land here since no PATCH has been made.
    assert result.stdout.strip() == "HA User <ha@distributed-esphome.local>"


async def test_commit_file_identity_follows_settings_change(tmp_path: Path):
    """Live-effect: change git_author_name/email in Settings, next commit uses it.

    This is the whole point of making the identity configurable —
    Stefan opens the Settings drawer on hass-4, changes to his own
    name + email, and the very next Fleet commit shows him as the
    author without any restart.
    """
    d = _make_config_dir(tmp_path)
    gv.init_repo(d)

    await settings_mod.update_settings({
        "git_author_name": "Stefan Zier",
        "git_author_email": "stefan@zier.com",
    })

    old = gv.DEBOUNCE_SECONDS
    gv.DEBOUNCE_SECONDS = 0.05
    try:
        (d / "living-room.yaml").write_text("edited after settings change\n")
        await gv.commit_file(d, "living-room.yaml", "save")
        await gv.drain_pending_commits()
    finally:
        gv.DEBOUNCE_SECONDS = old

    result = subprocess.run(
        ["git", "log", "--format=%an <%ae>", "-1"],
        cwd=str(d),
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "Stefan Zier <stefan@zier.com>"


async def test_commit_file_repo_identity_still_wins_over_settings(tmp_path: Path):
    """If the repo has its own user.name/email, Settings values are ignored."""
    d = _make_config_dir(tmp_path)
    subprocess.run(["git", "init", "-b", "main"], cwd=str(d), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Repo Owner"], cwd=str(d), check=True)
    subprocess.run(["git", "config", "user.email", "owner@example.com"], cwd=str(d), check=True)
    subprocess.run(["git", "add", "-A"], cwd=str(d), check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(d),
        check=True,
        capture_output=True,
    )

    # Even with Settings pointing at a Fleet identity, the repo's own
    # config should take precedence.
    await settings_mod.update_settings({
        "git_author_name": "Should Not Appear",
        "git_author_email": "should-not-appear@nope.test",
    })

    gv.init_repo(d)

    old = gv.DEBOUNCE_SECONDS
    gv.DEBOUNCE_SECONDS = 0.05
    try:
        (d / "living-room.yaml").write_text("edited\n")
        await gv.commit_file(d, "living-room.yaml", "save")
        await gv.drain_pending_commits()
    finally:
        gv.DEBOUNCE_SECONDS = old

    result = subprocess.run(
        ["git", "log", "--format=%an <%ae>", "-1"],
        cwd=str(d),
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "Repo Owner <owner@example.com>"


def test_init_repo_does_not_write_identity_into_repo_config(tmp_path: Path):
    """Fresh init no longer writes user.name/email to .git/config.

    Identity is injected at commit time via ``-c`` overrides, so the
    repo-local config stays pristine — a user who later runs
    ``git config user.name Stefan`` in /config/esphome takes over
    cleanly without having to unset our value first.
    """
    d = _make_config_dir(tmp_path)
    gv.init_repo(d)

    name = subprocess.run(
        ["git", "config", "--local", "--get", "user.name"],
        cwd=str(d),
        capture_output=True,
        text=True,
    )
    email = subprocess.run(
        ["git", "config", "--local", "--get", "user.email"],
        cwd=str(d),
        capture_output=True,
        text=True,
    )
    # `git config --local --get` returns exit code 1 when the key
    # isn't set; stdout is empty either way.
    assert name.stdout.strip() == ""
    assert email.stdout.strip() == ""


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
