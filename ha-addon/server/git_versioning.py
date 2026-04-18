"""Local git-backed auto-versioning for ``/config/esphome/`` (AV.*).

On server startup the config directory becomes a local git repo if it
isn't one already. Every subsequent file-writing operation (editor
save, rename, meta update, …) triggers an async debounced commit. Users
get a safety net — per-file history, diff, and rollback — without ever
touching ``git``.

If the user already has their own git setup in ``/config/esphome/`` we
don't touch init — only the auto-commit-on-save stream runs, and only
if the user leaves :attr:`settings.auto_commit_on_save` on.

## Failure semantics

All git operations here are defensive: a missing ``git`` binary, a
corrupt index, or a read-only filesystem must never propagate into the
request path or take down the server. Failures are logged at WARNING
(or EXCEPTION for unexpected shape) and the caller keeps going.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Hard-coded fallback used ONLY if the settings module hasn't been
# initialised (test harnesses) and the repo has no configured identity.
# The user-facing defaults live in settings.AppSettings so they're
# editable in the Settings drawer; this constant just exists to keep
# git_versioning importable without a live settings singleton.
_FALLBACK_AUTHOR_NAME = "HA User"
_FALLBACK_AUTHOR_EMAIL = "ha@distributed-esphome.local"

# .gitignore entries that should always exist on an ESPHome config dir —
# secrets shouldn't end up in commits, and the ESPHome build cache is
# huge and machine-local.
GITIGNORE_ENTRIES: tuple[str, ...] = ("secrets.yaml", ".esphome/")

# 2-second debounce window for auto-commits (per path).
DEBOUNCE_SECONDS = 2.0


def _settings_identity() -> tuple[str, str]:
    """Return the (name, email) from Settings, with a defensive fallback.

    Kept wrapped so git_versioning doesn't crash if called before
    settings have been initialised (e.g. during early startup or in a
    test that imports git_versioning without running init_settings).
    """
    try:
        from settings import get_settings  # noqa: PLC0415

        s = get_settings()
        return (s.git_author_name, s.git_author_email)
    except Exception:
        return (_FALLBACK_AUTHOR_NAME, _FALLBACK_AUTHOR_EMAIL)


def _has_user_identity(config_dir: Path) -> bool:
    """True if the repo can resolve both ``user.name`` and ``user.email``.

    Checks the effective value (repo-local → global → system). Modern
    git will *synthesize* an identity from OS gecos + hostname when
    nothing is explicitly configured — but that path triggers a
    "configured automatically" warning on every commit, which we
    don't want. So we only treat explicitly-configured identities as
    "present"; a synthesized one means we should inject our fallback.
    """
    try:
        name = _run(["git", "config", "--get", "user.name"], cwd=config_dir, check=False)
        email = _run(["git", "config", "--get", "user.email"], cwd=config_dir, check=False)
    except Exception:
        logger.exception("git config probe failed in %s", config_dir)
        return False
    return bool(name.stdout.strip() and email.stdout.strip())


# ---------------------------------------------------------------------------
# Low-level git wrapper
# ---------------------------------------------------------------------------


def _run(cmd: list[str], cwd: Path, check: bool = True, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    """Run a git command, log the exact argv, and capture output.

    PY-2 applies: we have a module-level logger and log the command line
    before the subprocess runs, so a failure is triageable from logs
    alone.
    """
    logger.debug("git (cwd=%s): %s", cwd, " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _is_git_repo(path: Path) -> bool:
    """True if *path* contains a ``.git`` directory (or file — submodules)."""
    git_marker = path / ".git"
    return git_marker.is_dir() or git_marker.is_file()


# ---------------------------------------------------------------------------
# AV.1 — Auto-init
# ---------------------------------------------------------------------------


def init_repo(config_dir: Path) -> None:
    """Initialize *config_dir* as a git repo if it isn't one already.

    Idempotent. On a pre-existing repo we only append missing
    :data:`GITIGNORE_ENTRIES` and set a fallback user identity (so
    commits don't fail on a bare repo with no author configured) —
    the user's own config is never overridden.
    """
    config_dir = Path(config_dir)
    if not config_dir.is_dir():
        logger.warning("config_dir %s does not exist; skipping git auto-init", config_dir)
        return

    try:
        if _is_git_repo(config_dir):
            logger.info("%s is already a git repo; skipping auto-init", config_dir)
            # Do NOT touch the user's curated .gitignore on a pre-existing
            # repo — Pat-with-git owns that file. Identity is handled at
            # commit time (see ``_identity_override_args``) so we don't
            # need to write to .git/config here either.
            return

        # Fresh init. `-b main` sets the default branch deterministically
        # so we don't depend on the host git's init.defaultBranch config.
        _run(["git", "init", "-b", "main"], cwd=config_dir)
        _ensure_gitignore(config_dir)

        # Initial commit. Use ``-c user.name/email`` derived from
        # Settings so the author reflects whatever the user has
        # configured in the drawer (default: ``HA User``). A later
        # change to the Settings values won't retroactively rewrite
        # history — but every subsequent commit picks up the new
        # value via the same override path.
        _run(["git", "add", "-A"], cwd=config_dir)
        name, email = _settings_identity()
        result = _run(
            [
                "git",
                "-c", f"user.name={name}",
                "-c", f"user.email={email}",
                "commit",
                "-m", "Initial commit by distributed-esphome",
                "--allow-empty",
            ],
            cwd=config_dir,
            check=False,
        )
        if result.returncode == 0:
            logger.info("Initialized git repo in %s with initial commit", config_dir)
        else:
            logger.warning(
                "git init succeeded but initial commit failed in %s: %s",
                config_dir, (result.stderr or result.stdout).strip(),
            )
    except FileNotFoundError:
        logger.exception("git binary not found on PATH; auto-versioning disabled")
    except subprocess.TimeoutExpired:
        logger.exception("git operation timed out during init of %s", config_dir)
    except Exception:
        logger.exception("Unexpected failure during git auto-init of %s", config_dir)


def _identity_override_args(config_dir: Path) -> list[str]:
    """Build ``-c user.name=... -c user.email=...`` args when needed.

    Returns an empty list if the repo already has ``user.name`` and
    ``user.email`` configured — in that case we respect the user's own
    identity. Returns the override args derived from Settings if the
    repo has nothing configured; the Settings values (editable in the
    drawer) become the Fleet identity for this commit.
    """
    if _has_user_identity(config_dir):
        return []
    name, email = _settings_identity()
    return ["-c", f"user.name={name}", "-c", f"user.email={email}"]


def _gitignore_equivalents(entry: str) -> set[str]:
    """Return the set of gitignore patterns equivalent to *entry* at repo root.

    A user may ignore ``.esphome/`` by writing any of
    ``.esphome/`` / ``.esphome`` / ``/.esphome/`` / ``/.esphome`` —
    from git's perspective they all hide the repo-root directory.
    Treating these as equivalent keeps us from sprinkling redundant
    lines into a user's curated gitignore on boot (see hass-4 incident
    where ``/.esphome/`` was already present and we added ``.esphome/``).
    """
    stripped = entry.strip().strip("/")
    if not stripped:
        return set()
    # Build every leading-slash / trailing-slash permutation.
    cores = {stripped}
    return {
        form
        for core in cores
        for form in (core, f"/{core}", f"{core}/", f"/{core}/")
    }


def _ensure_gitignore(config_dir: Path) -> None:
    """Ensure :data:`GITIGNORE_ENTRIES` are covered in ``.gitignore``.

    Appends only entries that aren't already covered by an equivalent
    pattern. Never rewrites or reorders existing content. Safe on a
    user-managed repo with their own curated gitignore.
    """
    gi = config_dir / ".gitignore"
    existing = ""
    if gi.exists():
        try:
            existing = gi.read_text(encoding="utf-8")
        except OSError:
            logger.exception("Failed to read %s", gi)
            return

    # Collect normalized covered patterns (ignoring comments and blank
    # lines, and trailing-slash/leading-slash variants).
    covered: set[str] = set()
    for raw_line in existing.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # A more permissive covers-check: any of the equivalents of this
        # line counts as covering that equivalent of our entry.
        covered |= _gitignore_equivalents(line)

    missing = [entry for entry in GITIGNORE_ENTRIES if entry not in covered]
    if not missing:
        return

    parts = [existing]
    if existing and not existing.endswith("\n"):
        parts.append("\n")
    if not existing:
        parts.append("# Added by ESPHome Fleet auto-versioning\n")
    for entry in missing:
        parts.append(entry + "\n")
    new_content = "".join(parts)

    try:
        gi.write_text(new_content, encoding="utf-8")
        logger.info("Added gitignore entries to %s: %s", gi, ", ".join(missing))
    except OSError:
        logger.exception("Failed to write %s", gi)


# ---------------------------------------------------------------------------
# AV.2 — Debounced auto-commit
# ---------------------------------------------------------------------------


@dataclass
class _PendingCommit:
    action: str
    task: asyncio.Task[None]


_pending: dict[str, _PendingCommit] = {}
_pending_lock: asyncio.Lock | None = None
# Git's index is a single shared resource per repo, and concurrent
# commits race on ``.git/index.lock``. We serialise the commit step
# itself (the fast part — add + commit in sequence) so two paths hitting
# the debounce window back-to-back don't stomp on each other. The
# debounce scheduler itself (``_pending_lock``) is separate because
# scheduling is O(microseconds) whereas a commit is O(tens of ms).
_commit_lock: asyncio.Lock | None = None


def _get_pending_lock() -> asyncio.Lock:
    global _pending_lock
    if _pending_lock is None:
        _pending_lock = asyncio.Lock()
    return _pending_lock


def _get_commit_lock() -> asyncio.Lock:
    global _commit_lock
    if _commit_lock is None:
        _commit_lock = asyncio.Lock()
    return _commit_lock


async def commit_file(config_dir: Path, relpath: str, action: str) -> None:
    """Schedule an async debounced commit for *relpath* in *config_dir*.

    Debounces per-path: if a commit is already pending for *relpath*,
    the existing timer is cancelled and a new one starts. Rapid
    back-to-back saves on the same file (save, then pin, then schedule)
    coalesce into a single commit with the message from the *last*
    call. This mirrors how a user thinks about "one change" in the UI.

    Respects :attr:`settings.auto_commit_on_save`. When the toggle is
    off, this is a no-op — no git, no debounce timer, no background
    task. Check happens both up front (cheap opt-out) and right before
    the commit itself runs (so flipping the toggle during the debounce
    window takes effect immediately).
    """
    from settings import get_settings  # noqa: PLC0415

    if not get_settings().auto_commit_on_save:
        return

    async with _get_pending_lock():
        existing = _pending.get(relpath)
        if existing is not None:
            existing.task.cancel()
        task = asyncio.create_task(_delayed_commit(Path(config_dir), relpath, action))
        _pending[relpath] = _PendingCommit(action=action, task=task)


async def _delayed_commit(config_dir: Path, relpath: str, action: str) -> None:
    this_task = asyncio.current_task()
    try:
        await asyncio.sleep(DEBOUNCE_SECONDS)
    except asyncio.CancelledError:
        # A newer commit_file() took our slot; bow out silently.
        return

    # We slept to completion — claim our exit from the pending map if
    # we're still the owner (we might not be, if a new commit_file()
    # landed between our sleep-completion and here).
    async with _get_pending_lock():
        current = _pending.get(relpath)
        if current is not None and current.task is this_task:
            _pending.pop(relpath, None)

    from settings import get_settings  # noqa: PLC0415

    if not get_settings().auto_commit_on_save:
        return

    loop = asyncio.get_running_loop()
    try:
        async with _get_commit_lock():
            await loop.run_in_executor(None, _do_commit, config_dir, relpath, action)
    except Exception:
        logger.exception("Auto-commit of %s failed", relpath)


def _do_commit(config_dir: Path, relpath: str, action: str) -> None:
    """Stage and commit a single path. Safe to call even if nothing changed."""
    if not _is_git_repo(config_dir):
        logger.debug("Not a git repo: %s; skipping auto-commit of %s", config_dir, relpath)
        return

    try:
        # `--all -- <path>` stages modifications, additions, AND
        # deletions for the given pathspec — so a commit after a delete
        # or rename picks up the right changes without us needing to
        # know which kind of change it was.
        add = _run(["git", "add", "--all", "--", relpath], cwd=config_dir, check=False)
        if add.returncode != 0:
            logger.warning("git add failed for %s: %s", relpath, (add.stderr or add.stdout).strip())
            return

        # Inject Settings-driven identity only if the repo has nothing
        # configured. Live-read at commit time — editing
        # git_author_name/email in the Settings drawer takes effect on
        # the very next auto-commit, no restart.
        override_args = _identity_override_args(config_dir)
        result = _run(
            [
                "git",
                *override_args,
                "commit",
                "-m", f"{action}: {relpath}",
                "--", relpath,
            ],
            cwd=config_dir,
            check=False,
        )
        if result.returncode == 0:
            logger.info("Committed %s: %s", action, relpath)
        else:
            # Most common reason: "nothing to commit, working tree
            # clean" — harmless (the UI may have saved identical
            # content, or the file is gitignored). Keep at DEBUG so
            # we don't spam on every save.
            logger.debug(
                "git commit for %s was a no-op: %s",
                relpath, (result.stderr or result.stdout).strip(),
            )
    except FileNotFoundError:
        logger.exception("git binary not found on PATH; auto-commit disabled")
    except subprocess.TimeoutExpired:
        logger.exception("git operation timed out during commit of %s", relpath)
    except Exception:
        logger.exception("Unexpected failure during auto-commit of %s", relpath)


async def drain_pending_commits() -> None:
    """Await any in-flight debounced commits — test-only helper."""
    async with _get_pending_lock():
        tasks = [p.task for p in _pending.values()]
    for t in tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass


def _reset_for_tests() -> None:
    """Test-only: clear module state between cases.

    Called from :func:`tests.conftest._reset_auto_versioning_state`
    both before and after each test, so state bound to a now-closed
    event loop (locks, pending tasks) never leaks across tests. We
    drop references without calling ``.cancel()`` because the teardown
    path may run after the test loop has already shut down — and
    calling ``cancel()`` on a task whose loop is closed raises.
    Python will GC the orphaned tasks along with their dead loop.
    """
    global _pending, _pending_lock, _commit_lock
    _pending = {}
    _pending_lock = None
    _commit_lock = None


# ---------------------------------------------------------------------------
# Read-side (AV.3/4/5/7) placeholders
# ---------------------------------------------------------------------------


def get_head(config_dir: Path) -> str | None:
    """Return the current HEAD commit hash, or None if not a repo / empty.

    Used by AV.7 to stamp ``Job.config_hash`` at enqueue time so "diff
    since last compile" can be computed from git without a snapshot
    directory.
    """
    if not _is_git_repo(Path(config_dir)):
        return None
    try:
        result = _run(["git", "rev-parse", "HEAD"], cwd=Path(config_dir), check=False)
        if result.returncode == 0:
            return result.stdout.strip() or None
    except Exception:
        logger.exception("git rev-parse HEAD failed in %s", config_dir)
    return None
