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

# .gitignore entries that should always exist on an ESPHome config dir.
# Secrets shouldn't end up in commits, and the ESPHome build cache is
# huge + machine-local.
#
# #63 update (dev.35): ``.archive/`` is NO LONGER ignored. The archive
# flow now uses `git mv` so a delete-then-restore preserves the file's
# history across the archive/unarchive boundary, and `git log --follow`
# threads through the move. The soft-delete copy in `.archive/<name>`
# is a normal tracked file and shows up in `git status` like any other
# config.
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


def _versioning_active(path: Path) -> bool:
    """#97 + #98: combined gate — the feature toggle AND a real repo on disk.

    Used by every git-write wrapper in this module. When the user has
    flipped ``versioning_enabled`` off (or hasn't yet decided — the
    ``'unset'`` state #98 introduces), we don't run any git commands:
    no commit, no ls-files, no blame. The module becomes inert.
    Callers should generally prefer this over raw
    :func:`_is_git_repo` except for the init path itself.
    """
    try:
        from settings import get_settings  # noqa: PLC0415

        if get_settings().versioning_enabled != "on":
            return False
    except Exception:
        # Settings not initialised (e.g. very early startup). Fall
        # through to the repo-presence check so this doesn't block
        # init_repo from running.
        pass
    return _is_git_repo(path)


# ---------------------------------------------------------------------------
# AV.1 — Auto-init
# ---------------------------------------------------------------------------


def init_repo(config_dir: Path) -> bool:
    """Initialize *config_dir* as a git repo if it isn't one already.

    Returns:
        True  — we initialised a fresh repo (Fleet owns it).
        False — the directory was already a git repo (user owns it),
                or initialisation failed / was skipped.

    The return value is used by :func:`settings.init_settings` to pick
    a sensible ``auto_commit_on_save`` default on first boot: fresh
    install → auto-commit on (Pat-no-git case); pre-existing repo →
    auto-commit off so Fleet doesn't spray ``save: foo.yaml`` commits
    into the user's curated log (Pat-with-git case).

    On a pre-existing repo we only append missing
    :data:`GITIGNORE_ENTRIES` and set a fallback user identity (so
    commits don't fail on a bare repo with no author configured) —
    the user's own config is never overridden.
    """
    # #97 + #98: top-level feature toggle. When versioning is
    # anything other than ``'on'`` (including the ``'unset'`` first-
    # boot state) no new repo should appear — not even on a fresh
    # install. The user has to explicitly opt in via the onboarding
    # modal before we touch their config dir.
    try:
        from settings import get_settings  # noqa: PLC0415
        state = get_settings().versioning_enabled
        if state != "on":
            logger.info("versioning_enabled=%r; skipping git auto-init", state)
            return False
    except Exception:
        pass

    config_dir = Path(config_dir)
    if not config_dir.is_dir():
        logger.warning("config_dir %s does not exist; skipping git auto-init", config_dir)
        return False

    try:
        if _is_git_repo(config_dir):
            logger.info("%s is already a git repo; skipping auto-init", config_dir)
            # Do NOT touch the user's curated .gitignore on a pre-existing
            # repo — Pat-with-git owns that file. Identity is handled at
            # commit time (see ``_identity_override_args``) so we don't
            # need to write to .git/config here either.
            return False

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
        return True
    except FileNotFoundError:
        logger.exception("git binary not found on PATH; auto-versioning disabled")
    except subprocess.TimeoutExpired:
        logger.exception("git operation timed out during init of %s", config_dir)
    except Exception:
        logger.exception("Unexpected failure during git auto-init of %s", config_dir)
    return False


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


async def commit_file(
    config_dir: Path,
    relpath: str,
    action: str,
    message: str | None = None,
) -> None:
    """Schedule an async debounced commit for *relpath* in *config_dir*.

    Debounces per-path: if a commit is already pending for *relpath*,
    the existing timer is cancelled and a new one starts. Rapid
    back-to-back saves on the same file (save, then pin, then schedule)
    coalesce into a single commit with the message from the *last*
    call. This mirrors how a user thinks about "one change" in the UI.

    When *message* is provided and non-empty, it replaces the
    auto-generated ``f"{action}: {relpath}"`` subject. Used for bug #24
    — the Save button in the editor prompts for a commit message on
    user-initiated saves, and that message flows in here.

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
        task = asyncio.create_task(_delayed_commit(Path(config_dir), relpath, action, message))
        _pending[relpath] = _PendingCommit(action=action, task=task)


async def _delayed_commit(
    config_dir: Path,
    relpath: str,
    action: str,
    message: str | None = None,
) -> None:
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
            await loop.run_in_executor(None, _do_commit, config_dir, relpath, action, message)
    except Exception:
        logger.exception("Auto-commit of %s failed", relpath)


# Bug #34: human-readable default subjects keyed by action. The old
# ``f"{action}: {relpath}"`` form repeated the filename (already visible
# via git's per-commit file listing) and read as jargon to non-technical
# users. Unmapped actions fall back to the action label capitalised — a
# safe default for future additions that haven't been curated here yet.
_DEFAULT_SUBJECTS: dict[str, str] = {
    "save": "Automatically saved after editing in UI",
    "create": "Created new device in UI",
    "delete": "Deleted device in UI",
    "restore": "Restored archived device",
    "rename": "Renamed device",
    "rename (old)": "Renamed device (old path)",
    "pin": "Pinned ESPHome version",
    "unpin": "Unpinned ESPHome version",
    "meta": "Updated device metadata",
    "schedule": "Updated scheduled upgrade",
    "unschedule": "Removed scheduled upgrade",
    "schedule toggle": "Toggled scheduled upgrade",
    "schedule once": "Set one-time scheduled upgrade",
}


def _default_subject(action: str, relpath: str) -> str:
    """Return the default commit subject for *action* / *relpath*.

    Bug #34: prefers the curated human-readable label from
    :data:`_DEFAULT_SUBJECTS`. Falls back to ``"<Action>: <relpath>"``
    for unmapped actions so future additions that forget to curate
    here still produce a legible message rather than blank output.
    """
    mapped = _DEFAULT_SUBJECTS.get(action)
    if mapped:
        return mapped
    return f"{action.capitalize()}: {relpath}"


def _do_commit(
    config_dir: Path,
    relpath: str,
    action: str,
    message: str | None = None,
) -> None:
    """Stage and commit a single path. Safe to call even if nothing changed."""
    if not _versioning_active(config_dir):
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
        subject = message.strip() if message and message.strip() else _default_subject(action, relpath)
        result = _run(
            [
                "git",
                *override_args,
                "commit",
                "-m", subject,
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
    if not _versioning_active(Path(config_dir)):
        return None
    try:
        result = _run(["git", "rev-parse", "HEAD"], cwd=Path(config_dir), check=False)
        if result.returncode == 0:
            return result.stdout.strip() or None
    except Exception:
        logger.exception("git rev-parse HEAD failed in %s", config_dir)
    return None


# ---------------------------------------------------------------------------
# AV.3 — History
# ---------------------------------------------------------------------------


def changed_paths_between(config_dir: Path, from_hash: str, to_hash: str) -> set[str]:
    """Return the set of repo-relative paths that differ between two commits.

    Bug #32: used by ``/ui/api/targets`` to recolor the Upgrade button
    when a device's last-flashed config hash is behind HEAD AND the
    target's YAML is among the files that changed since. Single
    ``git diff --name-only <from> <to>`` per unique from-hash; results
    are cached by the caller across targets.

    Validates hashes the same way :func:`rollback_file` does to keep
    shell metachars out of the pathspec. Returns an empty set on any
    validation failure, non-repo, or git error — never raises.
    """
    config_dir = Path(config_dir)
    if not _versioning_active(config_dir):
        return set()
    for h in (from_hash, to_hash):
        if not (4 <= len(h) <= 40 and all(c in "0123456789abcdef" for c in h.lower())):
            return set()
    try:
        result = _run(
            ["git", "diff", "--name-only", from_hash, to_hash],
            cwd=config_dir,
            check=False,
        )
    except Exception:
        logger.exception("git diff --name-only %s %s failed in %s", from_hash, to_hash, config_dir)
        return set()
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _find_creation_commit(config_dir: Path, relpath: str) -> str | None:
    """Return the SHA where *relpath* was first added, following renames.

    Returns ``None`` when the file has no committed add, when the dir
    isn't a git repo, or when git errors out. Used by :func:`file_history`
    to strip phantom ancestors that ``git log --follow`` emits when it
    mis-attributes a brand-new file's content to an unrelated deleted
    file in the repo's pre-Fleet history (bug #28).

    ``--follow --diff-filter=A --reverse`` yields adds only, oldest
    first; the first line is the file's true birth. For legitimate
    renames, this is the *original* filename's creation commit (the
    correct "start of history" to include in the drawer).
    """
    if not _versioning_active(Path(config_dir)):
        return None
    try:
        result = _run(
            [
                "git", "log",
                "--follow",
                "--diff-filter=A",
                "--reverse",
                "--format=%H",
                "--",
                relpath,
            ],
            cwd=Path(config_dir),
            check=False,
        )
    except Exception:
        logger.exception("git log --diff-filter=A failed for %s in %s", relpath, config_dir)
        return None
    if result.returncode != 0:
        return None
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return lines[0] if lines else None


def file_history(
    config_dir: Path,
    relpath: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, object]]:
    """Return commit history for *relpath*, newest first.

    Each entry: ``{hash, short_hash, message, date, author, lines_added,
    lines_removed}``. ``--follow`` tracks renames, so asking for
    ``bedroom.yaml``'s history still works after it was renamed from
    ``upstairs-bedroom.yaml``.

    Bug #28: ``git log --follow`` has a well-known false-positive mode
    where it attributes a newly-created file's ancestry to any deleted
    file with ≥50% content similarity in the pre-import commit history.
    We guard against that by finding the file's real creation commit
    via :func:`_find_creation_commit` and truncating the entry list at
    that commit — anything older is a phantom.

    Empty list on any of: not a git repo, file never committed, git
    errors. Never raises — callers render "no history yet" when empty.
    """
    config_dir = Path(config_dir)
    if not _versioning_active(config_dir):
        return []

    # Per-commit header line starts with a distinct marker so we can
    # parse line-by-line and correctly associate `--numstat` lines with
    # the commit they follow. The output shape is:
    #
    #     C<sep>SHA<sep>SHORT<sep>EPOCH<sep>NAME<sep>EMAIL<sep>MESSAGE
    #     <blank>
    #     <added>\t<removed>\t<path>     (one or more numstat lines)
    #     C<sep>...                       (next commit)
    #
    # NOTE: field separator is ``\x1f`` (Unit Separator), NOT ``\x1e``
    # (Record Separator) — the latter is listed by Python's
    # ``str.splitlines()`` as a line boundary, which shreds every
    # header into one-field-per-line during parsing.
    marker = "C"
    sep = "\x1f"
    fmt = sep.join([marker, "%H", "%h", "%at", "%an", "%ae", "%s"])

    try:
        result = _run(
            [
                "git", "log",
                f"--skip={max(offset, 0)}",
                f"--max-count={max(limit, 1)}",
                "--follow",
                "--numstat",
                f"--format={fmt}",
                "--",
                relpath,
            ],
            cwd=config_dir,
            check=False,
        )
    except Exception:
        logger.exception("git log failed for %s in %s", relpath, config_dir)
        return []

    if result.returncode != 0:
        logger.debug("git log for %s returned %d: %s", relpath, result.returncode, result.stderr.strip())
        return []

    entries = _parse_log_with_numstat(result.stdout, marker, sep)

    # Bug #28: drop phantom ancestors. If we can identify the real creation
    # commit, truncate the newest-first list at that hash. We only truncate
    # when the creation hash actually appears in the entries we fetched — if
    # it's past the current page (offset+limit), the entries we *did* get
    # are still legitimate mid-history commits and must be returned as-is.
    creation_hash = _find_creation_commit(Path(config_dir), relpath)
    if creation_hash:
        for i, e in enumerate(entries):
            if e.get("hash") == creation_hash:
                entries = entries[:i + 1]
                break

    return entries


def _parse_log_with_numstat(raw: str, marker: str, field_sep: str) -> list[dict[str, object]]:
    """Parse ``git log --numstat`` output with a per-commit header marker.

    Accumulates each commit's numstat rows into local ints, then writes
    the final counts into the entry dict in one go — avoids a dict read
    on every stat line (which mypy then flags as `call-overload` on
    ``int(current["lines_added"])`` since the dict is ``dict[str, object]``).
    """
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    added_total = 0
    removed_total = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.startswith(marker + field_sep):
            # Flush the previous commit's accumulated counts.
            if current is not None:
                current["lines_added"] = added_total
                current["lines_removed"] = removed_total
                entries.append(current)
            added_total = 0
            removed_total = 0
            fields = line.split(field_sep)
            if len(fields) < 7:
                current = None
                continue
            _m, sha, short_sha, epoch, author_name, author_email, message = fields[:7]
            try:
                epoch_int = int(epoch)
            except ValueError:
                epoch_int = 0
            current = {
                "hash": sha,
                "short_hash": short_sha,
                "date": epoch_int,
                "author_name": author_name,
                "author_email": author_email,
                "message": message,
                "lines_added": 0,
                "lines_removed": 0,
            }
            continue
        # numstat lines: "<added>\t<removed>\t<path>". Binary files show "-".
        if current is None:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added_str, removed_str = parts[0], parts[1]
        if added_str != "-":
            try:
                added_total += int(added_str)
            except ValueError:
                pass
        if removed_str != "-":
            try:
                removed_total += int(removed_str)
            except ValueError:
                pass
    if current is not None:
        current["lines_added"] = added_total
        current["lines_removed"] = removed_total
        entries.append(current)
    return entries


ARCHIVE_DIRNAME = ".archive"


def _staged_paths(config_dir: Path) -> set[str]:
    """Return the set of paths that currently have staged changes.

    Used by #95 to filter commit-time pathspecs down to what's actually
    different from HEAD. Passing a pathspec that doesn't match anything
    staged makes ``git commit -- pathspec`` emit
    ``pathspec '...' did not match any file(s) known to git`` and return
    non-zero even when the intended paths are in the index — see the
    hass-4 WARNING on 2026-04-19. Empty set on any failure (treated as
    "nothing known to be staged").
    """
    diff = _run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=config_dir, check=False,
    )
    if diff.returncode != 0:
        return set()
    return {line for line in diff.stdout.splitlines() if line}


async def archive_and_commit(config_dir: Path, relpath: str) -> bool:
    """Bug #63: archive + commit in one shot.

    Runs :func:`archive_with_git_mv` synchronously (git ops are fast
    enough that the event loop doesn't care), then — if auto-commit is
    on — commits BOTH sides of the move (deletion of the root path,
    addition of ``.archive/<relpath>``) in a single commit so git's
    rename detection on the commit diff picks it up as ``R``.

    Returns True when the archive move itself succeeded. The commit is
    best-effort — if auto-commit is off or the commit fails, the
    on-disk move is still correct, and the next manual / auto commit
    will catch up.
    """
    from settings import get_settings  # noqa: PLC0415

    config_dir = Path(config_dir)
    moved = archive_with_git_mv(config_dir, relpath)
    if not moved:
        return False
    if not _versioning_active(config_dir) or not get_settings().auto_commit_on_save:
        return True

    dest_rel = f"{ARCHIVE_DIRNAME}/{relpath}"
    override = _identity_override_args(config_dir)
    # Stage both sides — git mv already did this, but re-staging covers
    # the raw-rename fallback where the source wasn't tracked.
    _run(["git", "add", "--all", "--", relpath, dest_rel], cwd=config_dir, check=False)
    # #95: filter pathspecs to those actually staged so we never feed a
    # "pathspec did not match" to ``git commit``.
    wanted = _staged_paths(config_dir) & {relpath, dest_rel}
    if not wanted:
        return True
    commit = _run(
        ["git", *override, "commit",
         "-m", "Archived device (soft-delete)",
         "--", *sorted(wanted)],
        cwd=config_dir, check=False,
    )
    if commit.returncode != 0 and "nothing to commit" not in (commit.stderr + commit.stdout).lower():
        logger.warning(
            "archive commit failed for %s: %s",
            relpath, (commit.stderr or commit.stdout).strip(),
        )
    return True


async def restore_and_commit(config_dir: Path, filename: str) -> bool:
    """Bug #63: restore + commit in one shot — inverse of
    :func:`archive_and_commit`.

    #95: when the ``.archive/<file>`` side was never tracked in git
    (e.g. it was archived under the pre-#63 gitignored-``.archive/``
    regime and restored after the upgrade), the src pathspec isn't
    known to git, so we filter it out of the final ``git commit`` call.
    """
    from settings import get_settings  # noqa: PLC0415

    config_dir = Path(config_dir)
    moved = restore_with_git_mv(config_dir, filename)
    if not moved:
        return False
    if not _versioning_active(config_dir) or not get_settings().auto_commit_on_save:
        return True

    src_rel = f"{ARCHIVE_DIRNAME}/{filename}"
    override = _identity_override_args(config_dir)
    _run(["git", "add", "--all", "--", src_rel, filename], cwd=config_dir, check=False)
    wanted = _staged_paths(config_dir) & {src_rel, filename}
    if not wanted:
        return True
    commit = _run(
        ["git", *override, "commit",
         "-m", "Restored archived device",
         "--", *sorted(wanted)],
        cwd=config_dir, check=False,
    )
    if commit.returncode != 0 and "nothing to commit" not in (commit.stderr + commit.stdout).lower():
        logger.warning(
            "restore commit failed for %s: %s",
            filename, (commit.stderr or commit.stdout).strip(),
        )
    return True


async def delete_archived_and_commit(config_dir: Path, filename: str) -> bool:
    """#94: delete a file under ``.archive/`` and commit the removal.

    Pre-#63 ``.archive/`` was gitignored, so deleting an archived file
    was a pure ``os.unlink``. Post-#63 the directory is tracked, which
    means a bare unlink leaves a dangling ``deleted:`` entry in the
    working tree that only gets committed the next time some *other*
    write path runs the auto-committer. Fix: do the delete through
    ``git rm`` when the file is tracked, and commit immediately so the
    history reflects the operation.

    Falls back to a raw ``unlink()`` when the file was never tracked
    (e.g. the pre-#63 archive case where the file predates tracking).
    Returns True when the filesystem delete succeeded.
    """
    from settings import get_settings  # noqa: PLC0415

    config_dir = Path(config_dir)
    rel = f"{ARCHIVE_DIRNAME}/{filename}"
    path = config_dir / rel

    if not path.exists():
        return False

    if not _versioning_active(config_dir):
        try:
            path.unlink()
            return True
        except Exception:
            logger.exception("delete_archived unlink failed for %s", filename)
            return False

    tracked = _run(
        ["git", "ls-files", "--error-unmatch", "--", rel],
        cwd=config_dir, check=False,
    )
    if tracked.returncode != 0:
        # Not tracked — nothing for git to record; raw unlink.
        try:
            path.unlink()
            return True
        except Exception:
            logger.exception("delete_archived unlink fallback failed for %s", filename)
            return False

    rm = _run(["git", "rm", "--", rel], cwd=config_dir, check=False)
    if rm.returncode != 0:
        logger.warning(
            "git rm %s failed: %s",
            rel, (rm.stderr or rm.stdout).strip(),
        )
        # Clean up the working tree if git left the file in place.
        if path.exists():
            try:
                path.unlink()
            except Exception:
                logger.exception("cleanup unlink failed for %s", filename)
        return True  # filesystem side is correct; the commit just didn't land

    if not get_settings().auto_commit_on_save:
        return True

    override = _identity_override_args(config_dir)
    wanted = _staged_paths(config_dir) & {rel}
    if not wanted:
        return True
    commit = _run(
        ["git", *override, "commit",
         "-m", "Deleted archived device",
         "--", *sorted(wanted)],
        cwd=config_dir, check=False,
    )
    if commit.returncode != 0 and "nothing to commit" not in (commit.stderr + commit.stdout).lower():
        logger.warning(
            "delete_archived commit failed for %s: %s",
            filename, (commit.stderr or commit.stdout).strip(),
        )
    return True


def archive_with_git_mv(config_dir: Path, relpath: str) -> bool:
    """Bug #63: move *relpath* into ``.archive/`` using ``git mv`` so
    the operation reads as a rename in git history.

    Falls back to a filesystem rename when the source file isn't
    currently tracked (fresh, uncommitted creates that the user
    immediately deletes). Returns True on success, False on hard
    failure. Non-repo paths go through the raw rename silently — the
    caller is responsible for creating the archive directory.
    """
    config_dir = Path(config_dir)
    src = config_dir / relpath
    archive_dir = config_dir / ARCHIVE_DIRNAME
    dest_rel = f"{ARCHIVE_DIRNAME}/{relpath}"
    dest = config_dir / dest_rel

    archive_dir.mkdir(exist_ok=True)

    if not _versioning_active(config_dir):
        try:
            src.rename(dest)
            return True
        except Exception:
            logger.exception("archive rename failed for %s", relpath)
            return False

    # Check if src is tracked — an untracked file can't be `git mv`d.
    tracked = _run(
        ["git", "ls-files", "--error-unmatch", "--", relpath],
        cwd=config_dir, check=False,
    )
    if tracked.returncode != 0:
        try:
            src.rename(dest)
            return True
        except Exception:
            logger.exception("archive rename fallback failed for %s", relpath)
            return False

    try:
        mv = _run(["git", "mv", relpath, dest_rel], cwd=config_dir, check=False)
        if mv.returncode != 0:
            logger.warning(
                "git mv %s → %s failed: %s",
                relpath, dest_rel, (mv.stderr or mv.stdout).strip(),
            )
            # Best-effort fallback: try a raw rename + let the next
            # auto-commit pick it up as delete+add (rename detection
            # may or may not kick in, but the file at least lands).
            if src.exists() and not dest.exists():
                try:
                    src.rename(dest)
                    return True
                except Exception:
                    logger.exception("fallback rename failed for %s", relpath)
            return False
        return True
    except Exception:
        logger.exception("archive_with_git_mv pipeline failed for %s", relpath)
        return False


def restore_with_git_mv(config_dir: Path, filename: str) -> bool:
    """Bug #63: move *filename* from ``.archive/`` back to the config
    root using ``git mv`` so history threads across archive → restore.

    Returns True on success, False otherwise. Non-repo paths fall back
    to a raw filesystem rename.
    """
    config_dir = Path(config_dir)
    src_rel = f"{ARCHIVE_DIRNAME}/{filename}"
    src = config_dir / src_rel
    dest = config_dir / filename

    if not src.exists():
        return False

    if not _versioning_active(config_dir):
        try:
            src.rename(dest)
            return True
        except Exception:
            logger.exception("restore rename failed for %s", filename)
            return False

    tracked = _run(
        ["git", "ls-files", "--error-unmatch", "--", src_rel],
        cwd=config_dir, check=False,
    )
    if tracked.returncode != 0:
        try:
            src.rename(dest)
            return True
        except Exception:
            logger.exception("restore rename fallback failed for %s", filename)
            return False

    try:
        mv = _run(["git", "mv", src_rel, filename], cwd=config_dir, check=False)
        if mv.returncode != 0:
            logger.warning(
                "git mv %s → %s failed: %s",
                src_rel, filename, (mv.stderr or mv.stdout).strip(),
            )
            if src.exists() and not dest.exists():
                try:
                    src.rename(dest)
                    return True
                except Exception:
                    logger.exception("fallback rename failed for %s", filename)
            return False
        return True
    except Exception:
        logger.exception("restore_with_git_mv pipeline failed for %s", filename)
        return False


# ---------------------------------------------------------------------------
# AV.4 — Diff
# ---------------------------------------------------------------------------


def rollback_file(config_dir: Path, relpath: str, hash: str) -> dict[str, object]:
    """AV.5: restore *relpath* to its content at *hash*.

    ``git checkout <hash> -- <relpath>`` overwrites the working-tree file
    with the historical version. If ``settings.auto_commit_on_save`` is
    true, we also ``git add + git commit`` so the rollback is itself a
    recorded entry in history (``revert: <file> to <short_hash>``). If
    auto-commit is off the working tree is left dirty — the user is
    expected to review and commit via :func:`commit_file_now` (AV.11).

    Returns a dict with:
      - ``content``: the restored file text (empty string on failure)
      - ``committed``: whether a revert commit was created
      - ``hash``: the new revert commit's full SHA (None if ``committed``
        is False)
      - ``short_hash``: 7-char form (None if not committed)

    Raises nothing — callers render the returned ``content`` and status.
    """
    config_dir = Path(config_dir)
    if not _versioning_active(config_dir):
        logger.warning("rollback_file called on non-repo %s", config_dir)
        return {"content": "", "committed": False, "hash": None, "short_hash": None}

    # Validate hash up-front so we don't pass a shell metachar to git.
    if not (4 <= len(hash) <= 40 and all(c in "0123456789abcdef" for c in hash.lower())):
        logger.warning("Rejected rollback request with malformed hash: %r", hash)
        return {"content": "", "committed": False, "hash": None, "short_hash": None}

    try:
        checkout = _run(["git", "checkout", hash, "--", relpath], cwd=config_dir, check=False)
    except Exception:
        logger.exception("git checkout failed for %s @ %s", relpath, hash)
        return {"content": "", "committed": False, "hash": None, "short_hash": None}
    if checkout.returncode != 0:
        logger.warning("git checkout refused %s @ %s: %s", relpath, hash, (checkout.stderr or checkout.stdout).strip())
        return {"content": "", "committed": False, "hash": None, "short_hash": None}

    # Read the restored content so the UI can refresh without a separate
    # read — the editor already rendered the old buffer by the time we
    # got here, so handing back the new content saves a round trip.
    content = ""
    try:
        content = (config_dir / relpath).read_text(encoding="utf-8")
    except OSError:
        logger.exception("Failed to read rolled-back file %s", relpath)

    from settings import get_settings  # noqa: PLC0415
    if not get_settings().auto_commit_on_save:
        return {"content": content, "committed": False, "hash": None, "short_hash": None}

    # Bug #34: human-readable revert subject. Short hash kept in the
    # message so ``git log --oneline`` still pins the restore target.
    short = hash[:7]
    msg = f"Restored earlier version ({short})"
    try:
        add = _run(["git", "add", "--all", "--", relpath], cwd=config_dir, check=False)
        if add.returncode != 0:
            logger.warning("git add failed during rollback of %s", relpath)
            return {"content": content, "committed": False, "hash": None, "short_hash": None}
        override = _identity_override_args(config_dir)
        commit = _run(
            ["git", *override, "commit", "-m", msg, "--", relpath],
            cwd=config_dir,
            check=False,
        )
        if commit.returncode != 0:
            # Nothing to commit is possible if the user rolled back to
            # the exact current HEAD — not an error, just not a new
            # commit. Return current HEAD as the effective hash.
            if "nothing to commit" in (commit.stderr + commit.stdout).lower():
                head = get_head(config_dir)
                return {
                    "content": content,
                    "committed": False,
                    "hash": head,
                    "short_hash": head[:7] if head else None,
                }
            logger.warning("git commit failed during rollback: %s", (commit.stderr or commit.stdout).strip())
            return {"content": content, "committed": False, "hash": None, "short_hash": None}
        new_head = get_head(config_dir)
        logger.info("Rolled back %s to %s and committed %s", relpath, short, new_head[:7] if new_head else "?")
        return {
            "content": content,
            "committed": True,
            "hash": new_head,
            "short_hash": new_head[:7] if new_head else None,
        }
    except Exception:
        logger.exception("rollback commit pipeline failed for %s", relpath)
        return {"content": content, "committed": False, "hash": None, "short_hash": None}


def commit_file_now(
    config_dir: Path,
    relpath: str,
    message: str | None = None,
) -> dict[str, object]:
    """AV.11: immediate (non-debounced) commit for *relpath*.

    Differs from :func:`commit_file` (auto-commit debounced path) in
    two ways:

    1. Runs inline — the caller gets the commit result back, which is
       needed for the manual-commit UI to render the new hash.
    2. Always runs regardless of ``settings.auto_commit_on_save``.
       This is the "user explicitly asked to commit" action; it's the
       escape valve for when auto-commit is off.

    Returns ``{committed, hash, short_hash, message}``. ``committed`` is
    False when there was nothing to commit (file matched HEAD) — not an
    error, just informational.
    """
    config_dir = Path(config_dir)
    if not _versioning_active(config_dir):
        return {"committed": False, "hash": None, "short_hash": None, "message": None}

    # Bug #34: human-readable manual-commit subject. The "(manual)" tail
    # distinguishes user-invoked commits from the auto-save path —
    # useful when scanning ``git log`` for what Fleet vs the user did.
    effective_msg = message.strip() if message and message.strip() else "Manually committed from UI"
    try:
        add = _run(["git", "add", "--all", "--", relpath], cwd=config_dir, check=False)
        if add.returncode != 0:
            logger.warning("git add failed for %s: %s", relpath, (add.stderr or add.stdout).strip())
            return {"committed": False, "hash": None, "short_hash": None, "message": None}

        override = _identity_override_args(config_dir)
        commit = _run(
            ["git", *override, "commit", "-m", effective_msg, "--", relpath],
            cwd=config_dir,
            check=False,
        )
        if commit.returncode != 0:
            # "nothing to commit" is the happy no-op path.
            if "nothing to commit" in (commit.stderr + commit.stdout).lower():
                return {"committed": False, "hash": None, "short_hash": None, "message": None}
            logger.warning("manual commit failed for %s: %s", relpath, (commit.stderr or commit.stdout).strip())
            return {"committed": False, "hash": None, "short_hash": None, "message": None}
        new_head = get_head(config_dir)
        logger.info("Manual commit for %s: %s (%s)", relpath, new_head[:7] if new_head else "?", effective_msg)
        return {
            "committed": True,
            "hash": new_head,
            "short_hash": new_head[:7] if new_head else None,
            "message": effective_msg,
        }
    except Exception:
        logger.exception("manual commit pipeline failed for %s", relpath)
        return {"committed": False, "hash": None, "short_hash": None, "message": None}


def file_content_at(config_dir: Path, relpath: str, hash: str | None) -> str | None:
    """Return the content of *relpath* at commit *hash*, or ``None`` on error.

    When ``hash`` is ``None``, returns the current working-tree content
    (what's on disk right now). Used by the History panel's side-by-side
    diff viewer (bug #10) to render both sides in Monaco's ``DiffEditor``.

    Hash values are validated as 4-40 hex chars to keep shell metachars
    out of ``git show``.
    """
    config_dir = Path(config_dir)

    # Working-tree read doesn't need a git repo.
    if hash is None:
        try:
            return (config_dir / relpath).read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        except Exception:
            logger.exception("Failed to read %s for content-at(None)", relpath)
            return None

    if not _versioning_active(config_dir):
        return None
    if not (4 <= len(hash) <= 40 and all(c in "0123456789abcdef" for c in hash.lower())):
        # Bug #15 (reopened): drop from WARNING to DEBUG. The 400
        # response the handler returns is evidence enough; WARNING
        # turns a client-side bug into log noise that operators can't
        # act on.
        logger.debug("Rejected content-at request with malformed hash: %r", hash)
        return None

    try:
        # `git show <hash>:<path>` prints the file's contents at that commit.
        result = _run(["git", "show", f"{hash}:{relpath}"], cwd=config_dir, check=False)
    except Exception:
        logger.exception("git show failed for %s @ %s", relpath, hash)
        return None

    if result.returncode != 0:
        # File didn't exist at that commit → return "" so the diff
        # viewer renders it as "added" / "deleted" cleanly.
        return ""
    return result.stdout


def dirty_paths(config_dir: Path) -> set[str]:
    """Bug #16: return every relpath under *config_dir* that has
    uncommitted changes. One ``git status --porcelain`` call covers the
    whole repo — cheap enough to run per `/ui/api/targets` refresh
    (1 Hz SWR poll), much more efficient than N per-file probes.

    Returns an empty set on non-repo dirs, empty-repo state, or git
    errors. Rename lines (``R foo -> bar``) contribute BOTH the old
    and new path so either side shows as dirty until committed.
    Untracked files (``??`` status) are included so a newly-created
    target before its first commit shows up.
    """
    config_dir = Path(config_dir)
    if not _versioning_active(config_dir):
        return set()

    try:
        result = _run(["git", "status", "--porcelain"], cwd=config_dir, check=False)
    except Exception:
        logger.exception("git status failed in %s", config_dir)
        return set()
    if result.returncode != 0:
        return set()

    dirty: set[str] = set()
    for line in result.stdout.splitlines():
        # Porcelain v1 format: XY<space><path>[ -> <path2>]
        if len(line) < 4:
            continue
        rest = line[3:]
        if " -> " in rest:
            old, new = rest.split(" -> ", 1)
            dirty.add(old.strip())
            dirty.add(new.strip())
        else:
            dirty.add(rest.strip())
    return dirty


def file_status(config_dir: Path, relpath: str) -> dict[str, object]:
    """AV.6 support: return per-file dirtiness + HEAD hash for the panel banner.

    Returns ``{has_uncommitted_changes, head_hash, head_short_hash}``.
    All false / None on non-repo directories.
    """
    config_dir = Path(config_dir)
    if not _versioning_active(config_dir):
        return {"has_uncommitted_changes": False, "head_hash": None, "head_short_hash": None}

    try:
        # `--porcelain` gives a stable, parser-friendly output.
        # Two lines possible: staged + unstaged. Either means dirty.
        status = _run(["git", "status", "--porcelain", "--", relpath], cwd=config_dir, check=False)
    except Exception:
        logger.exception("git status failed for %s in %s", relpath, config_dir)
        return {"has_uncommitted_changes": False, "head_hash": None, "head_short_hash": None}

    dirty = bool(status.stdout.strip()) if status.returncode == 0 else False
    head = get_head(config_dir)
    return {
        "has_uncommitted_changes": dirty,
        "head_hash": head,
        "head_short_hash": head[:7] if head else None,
    }


def file_diff(
    config_dir: Path,
    relpath: str,
    from_hash: str | None = None,
    to_hash: str | None = None,
) -> str:
    """Return a unified diff string for *relpath* between two commits.

    - Both hashes given → ``git diff <from> <to> -- <path>``
    - Only *from_hash* given → diff against HEAD
    - Only *to_hash* given → diff the working tree (uncommitted changes)
      against *to_hash* (unusual; mostly for symmetry)
    - Neither given → diff the working tree against HEAD (uncommitted
      changes on the current branch)

    Empty string on any of: not a git repo, file has no history, git
    errors, or the two versions are identical. Rejects shell-metachar
    input by validating hashes against ``[0-9a-f]{4,40}``.
    """
    config_dir = Path(config_dir)
    if not _versioning_active(config_dir):
        return ""

    def _valid_hash(h: str) -> bool:
        return 4 <= len(h) <= 40 and all(c in "0123456789abcdef" for c in h.lower())

    for h in (from_hash, to_hash):
        if h and not _valid_hash(h):
            logger.warning("Rejected diff request with malformed hash: %r", h)
            return ""

    args = ["git", "diff", "--no-color"]
    if from_hash and to_hash:
        args += [from_hash, to_hash]
    elif from_hash:
        args += [from_hash, "HEAD"]
    elif to_hash:
        args += [to_hash]
    # else: default working-tree-vs-HEAD (no extra args).
    args += ["--", relpath]

    try:
        result = _run(args, cwd=config_dir, check=False)
    except Exception:
        logger.exception("git diff failed for %s in %s", relpath, config_dir)
        return ""

    if result.returncode != 0:
        logger.debug("git diff returned %d: %s", result.returncode, result.stderr.strip())
        return ""
    return result.stdout
