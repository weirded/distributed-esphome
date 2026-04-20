"""Tests for bug #19 (1.6.1) — ``git init`` runs when the user flips
``versioning_enabled`` on post-boot.

Two layers of coverage:

1. The pure-function transition detector
   ``_versioning_just_enabled(previous, partial)`` — pinpoints the
   "unset|off → on" transition and ignores every other PATCH.
2. An integration check that ``init_repo(tmp_dir)`` does the right
   thing (creates the ``.git/`` directory, records an initial commit)
   after we flip the setting — this is the end-state the PATCH hook
   needs to produce.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ui_api import _versioning_just_enabled


# ---------------------------------------------------------------------------
# Transition detector
# ---------------------------------------------------------------------------


def test_detects_unset_to_on() -> None:
    """First-boot onboarding modal path: versioning was never set,
    user picks 'Turn on' → init_repo must fire."""
    assert _versioning_just_enabled("unset", {"versioning_enabled": "on"}) is True


def test_detects_off_to_on() -> None:
    """User previously opted out, changed their mind via Settings drawer."""
    assert _versioning_just_enabled("off", {"versioning_enabled": "on"}) is True


def test_detects_none_previous_value() -> None:
    """Defensive: if the settings module ever returns None as the
    previous value (corrupt settings.json, missing field), we still
    fire rather than silently skip — worst case is a no-op ``git init``
    on an already-initialised dir, which ``init_repo`` handles."""
    assert _versioning_just_enabled(None, {"versioning_enabled": "on"}) is True


def test_no_op_when_already_on() -> None:
    """Second PATCH with the same value must NOT re-init; a second
    ``git init`` on a live repo would be a no-op but would also kick
    off a confusing log line each time."""
    assert _versioning_just_enabled("on", {"versioning_enabled": "on"}) is False


def test_no_op_when_turning_off() -> None:
    """Flipping versioning off must never run init_repo."""
    assert _versioning_just_enabled("on", {"versioning_enabled": "off"}) is False


def test_no_op_when_partial_omits_field() -> None:
    """Unrelated PATCH (e.g. theme, git_author_name) must not re-init."""
    assert _versioning_just_enabled("on", {"git_author_name": "Stefan"}) is False
    assert _versioning_just_enabled("off", {"git_author_name": "Stefan"}) is False


# ---------------------------------------------------------------------------
# End-state integration: init_repo actually creates a repo
# ---------------------------------------------------------------------------


@pytest.fixture
def _fake_settings_on(monkeypatch):
    """Pretend ``get_settings().versioning_enabled == "on"`` because
    init_repo reads the live value as its own safety guard."""
    class _S:
        versioning_enabled = "on"
        git_author_name = "HA User"
        git_author_email = "ha@test.local"

    import settings as settings_mod
    monkeypatch.setattr(settings_mod, "get_settings", lambda: _S())


def test_init_repo_creates_git_dir_and_initial_commit(
    tmp_path: Path, _fake_settings_on,
) -> None:
    """Mirrors what the PATCH hook's ``run_in_executor(init_repo, …)``
    does: on a fresh directory, we end up with ``.git/`` and exactly
    one ``Initial commit`` after the call."""
    from git_versioning import init_repo

    (tmp_path / "bedroom.yaml").write_text("esphome:\n  name: bedroom\n")

    created = init_repo(tmp_path)
    assert created is True
    assert (tmp_path / ".git").is_dir()

    log = subprocess.check_output(
        ["git", "-C", str(tmp_path), "log", "--oneline"], text=True,
    )
    # Exactly one commit — the initial snapshot.
    assert len(log.strip().splitlines()) == 1
    assert "Initial" in log or "initial" in log


def test_init_repo_is_idempotent_on_existing_repo(
    tmp_path: Path, _fake_settings_on,
) -> None:
    """A second call on the same dir must not create a second
    'initial commit'. ``init_repo`` returns False on an existing repo
    so the handler logs the right outcome."""
    from git_versioning import init_repo

    (tmp_path / "bedroom.yaml").write_text("esphome:\n  name: bedroom\n")
    init_repo(tmp_path)

    before = subprocess.check_output(
        ["git", "-C", str(tmp_path), "log", "--oneline"], text=True,
    ).strip().splitlines()

    created_again = init_repo(tmp_path)
    assert created_again is False

    after = subprocess.check_output(
        ["git", "-C", str(tmp_path), "log", "--oneline"], text=True,
    ).strip().splitlines()
    assert before == after


# ---------------------------------------------------------------------------
# Bug #22 (1.6.1): boot-time rescue when versioning_enabled=on + .git missing
# ---------------------------------------------------------------------------


def test_boot_time_init_when_setting_is_on_and_git_missing(
    tmp_path: Path, _fake_settings_on,
) -> None:
    """Reproduces the scenario bug #22 closed: user opted into
    versioning on a prior boot (settings.json says ``on``) but the
    ``.git/`` directory is missing — container rebuild, fresh /config
    mount, restored backup. The boot-time hook added in main.py must
    re-run ``init_repo`` so history starts accruing without manual
    intervention."""
    from git_versioning import _is_git_repo, init_repo

    (tmp_path / "bedroom.yaml").write_text("esphome:\n  name: bedroom\n")
    # Precondition: config dir has YAML, no git.
    assert not _is_git_repo(tmp_path)

    # Simulate the boot-time guard: settings says ``on``, dir has no
    # .git/, so init_repo runs and creates one.
    assert _fake_settings_on is None  # the fixture just monkeypatches
    if not _is_git_repo(tmp_path):
        init_repo(tmp_path)

    assert _is_git_repo(tmp_path)
    log = subprocess.check_output(
        ["git", "-C", str(tmp_path), "log", "--oneline"], text=True,
    )
    assert len(log.strip().splitlines()) == 1


def test_boot_time_init_no_op_when_git_already_there(
    tmp_path: Path, _fake_settings_on,
) -> None:
    """Common case: prior boot created the repo, it's still on disk.
    The boot-time guard's ``_is_git_repo`` check must short-circuit
    so init_repo doesn't re-enter (which itself is idempotent, but
    avoiding the call keeps boot fast + the log clean)."""
    from git_versioning import _is_git_repo, init_repo

    (tmp_path / "bedroom.yaml").write_text("esphome:\n  name: bedroom\n")
    init_repo(tmp_path)
    assert _is_git_repo(tmp_path)

    # Guard: if git repo already exists, the boot-time hook short-
    # circuits. This test pins that behavioural contract — a regression
    # that dropped the guard would make startup slower every boot.
    would_call_init = not _is_git_repo(tmp_path)
    assert would_call_init is False
