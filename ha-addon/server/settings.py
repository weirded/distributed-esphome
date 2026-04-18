"""In-app user-facing settings, persisted to ``/data/settings.json``.

Scope: product feature toggles and operational knobs that we expect
users to edit at runtime — auto-commit-on-save, job-history retention,
cache budgets. Deliberately separate from :mod:`app_config` (Supervisor's
``options.json``) because:

1. Supervisor's Configuration tab triggers a full add-on restart on every
   edit — hostile UX for day-to-day toggles.
2. Product settings shouldn't clutter the deployment-plumbing surface
   (token, port, ``require_ha_auth``) that Supervisor *does* own.

See ``dev-plans/WORKITEMS-1.6.md`` §Settings for the full rationale.

Contract:

- :func:`get_settings` returns the current in-memory singleton. Cheap,
  safe to call from any code path. Consumers MUST call it at decision
  time (not at startup) so PATCH propagates without a restart.
- :func:`update_settings` validates + persists atomically + rotates the
  singleton. Call sites are expected to be async (it takes the lock).
- :func:`init_settings` runs once at server startup — loads the file or
  seeds it from ``options.json`` (one-time import).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

SETTINGS_FILE = Path("/data/settings.json")
OPTIONS_FILE = Path("/data/options.json")

# Fields migrated out of options.json. On first boot where settings.json
# is absent, their values are seeded from options.json if present. After
# that, settings.json is the only source of truth — edits in Supervisor
# Configuration have no effect and are documented in DOCS.md.
IMPORT_FROM_OPTIONS: tuple[str, ...] = (
    "job_history_retention_days",
    "firmware_cache_max_gb",
    "job_log_retention_days",
)


class SettingsValidationError(ValueError):
    """Raised by :func:`update_settings` when a value fails validation.

    Carries the offending field name so the REST layer can return a 400
    that pinpoints the problem.
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field


@dataclass
class AppSettings:
    """User-facing settings editable at runtime via ``/ui/api/settings``."""

    auto_commit_on_save: bool = True
    # Author used on Fleet-originated auto-commits (AV.2). Only applied
    # when the repo itself has no ``user.name``/``user.email`` configured
    # at any level (repo-local, global, system) — a user with their own
    # repo-local identity keeps it. See git_versioning.py.
    git_author_name: str = "HA User"
    git_author_email: str = "ha@distributed-esphome.local"
    job_history_retention_days: int = 365
    firmware_cache_max_gb: float = 2.0
    job_log_retention_days: int = 30


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _validate_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise SettingsValidationError(field, f"expected bool, got {value!r}")


def _validate_int_range(lo: int, hi: int) -> Callable[[Any, str], int]:
    def _v(value: Any, field: str) -> int:
        try:
            coerced = int(value)
        except (TypeError, ValueError):
            raise SettingsValidationError(field, f"expected integer, got {value!r}")
        if coerced < lo or coerced > hi:
            raise SettingsValidationError(field, f"must be between {lo} and {hi}, got {coerced}")
        return coerced

    return _v


def _validate_float_range(lo: float, hi: float) -> Callable[[Any, str], float]:
    def _v(value: Any, field: str) -> float:
        try:
            coerced = float(value)
        except (TypeError, ValueError):
            raise SettingsValidationError(field, f"expected number, got {value!r}")
        if coerced < lo or coerced > hi:
            raise SettingsValidationError(field, f"must be between {lo} and {hi}, got {coerced}")
        return coerced

    return _v


def _validate_str(max_len: int) -> Callable[[Any, str], str]:
    def _v(value: Any, field: str) -> str:
        if not isinstance(value, str):
            raise SettingsValidationError(field, f"expected string, got {type(value).__name__}")
        stripped = value.strip()
        if not stripped:
            raise SettingsValidationError(field, "must not be empty")
        if len(stripped) > max_len:
            raise SettingsValidationError(field, f"must be {max_len} characters or fewer")
        return stripped

    return _v


# Per-field validators. Any PATCH that names a key not listed here is
# rejected — keeps typos from silently disappearing.
_VALIDATORS: dict[str, Callable[[Any, str], Any]] = {
    "auto_commit_on_save": _validate_bool,
    # Git author. Don't validate email format — git itself accepts
    # arbitrary strings (e.g. "ha@distributed-esphome.local" isn't a
    # routable email), so requiring an RFC-shaped address would reject
    # legitimate values.
    "git_author_name": _validate_str(100),
    "git_author_email": _validate_str(256),
    # 0 = unlimited is explicitly allowed (matches JH.3 spec). 3650 = 10y.
    "job_history_retention_days": _validate_int_range(0, 3650),
    # Hard floor at 0.1 GB so a typo ("0") doesn't nuke cached firmware.
    "firmware_cache_max_gb": _validate_float_range(0.1, 1024.0),
    # 0 = unlimited; 3650 = 10y.
    "job_log_retention_days": _validate_int_range(0, 3650),
}


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_settings: AppSettings | None = None
_lock: asyncio.Lock | None = None
_settings_path: Path = SETTINGS_FILE
_options_path: Path = OPTIONS_FILE


def _get_lock() -> asyncio.Lock:
    # Lazy-create so import doesn't require a running loop.
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Atomically write JSON to *path* (tempfile in same dir + ``os.replace``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _read_json(path: Path) -> dict[str, Any]:
    """Read JSON object from *path*. Returns ``{}`` on any failure."""
    try:
        raw = path.read_text()
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        logger.error("%s is not a JSON object (got %s); ignoring", path, type(parsed).__name__)
    except FileNotFoundError:
        pass
    except Exception:
        logger.exception("Failed to read %s; treating as empty", path)
    return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init_settings(
    settings_path: Path | None = None,
    options_path: Path | None = None,
) -> AppSettings:
    """Load settings from disk, importing from ``options.json`` on first boot.

    Must be called exactly once at server startup before any consumer
    calls :func:`get_settings`. Idempotent: a second call re-reads the
    file (primarily for tests that mutate disk behind the module's back).

    Parameters let tests redirect to a scratch directory.
    """

    global _settings, _settings_path, _options_path

    if settings_path is not None:
        _settings_path = settings_path
    if options_path is not None:
        _options_path = options_path

    if _settings_path.exists():
        _settings = _load_from_file()
        logger.info("Loaded settings from %s", _settings_path)
        return _settings

    # First boot: seed from options.json for migrated fields, keep dataclass
    # defaults for everything else. If the filesystem is read-only (e.g. a
    # test harness running without /data), fall back to in-memory defaults
    # so the server still boots.
    _settings = _seed_from_options()
    try:
        _atomic_write(_settings_path, asdict(_settings))
        logger.info("Created %s with defaults (migrated fields imported from %s where present)", _settings_path, _options_path)
    except OSError:
        logger.warning(
            "Could not create %s (read-only fs?); serving defaults in-memory only",
            _settings_path,
        )
    return _settings


def _load_from_file() -> AppSettings:
    raw = _read_json(_settings_path)
    # Unknown keys are tolerated on load (forward-compat), but logged at
    # WARNING so they don't rot invisibly.
    known = {f.name for f in fields(AppSettings)}
    for key in sorted(set(raw) - known):
        logger.warning("Unknown key in %s: %r — ignored", _settings_path, key)

    defaults = AppSettings()
    kwargs: dict[str, Any] = {}
    for f in fields(AppSettings):
        if f.name in raw:
            try:
                kwargs[f.name] = _VALIDATORS[f.name](raw[f.name], f.name)
            except SettingsValidationError as exc:
                logger.error("Invalid value in %s for %s; using default: %s", _settings_path, f.name, exc)
                kwargs[f.name] = getattr(defaults, f.name)
        else:
            kwargs[f.name] = getattr(defaults, f.name)
    return AppSettings(**kwargs)


def _seed_from_options() -> AppSettings:
    """Build initial AppSettings, pulling migrated fields from options.json."""
    defaults = AppSettings()
    options = _read_json(_options_path)
    kwargs: dict[str, Any] = asdict(defaults)
    imported: list[str] = []
    for key in IMPORT_FROM_OPTIONS:
        if key in options:
            try:
                kwargs[key] = _VALIDATORS[key](options[key], key)
                imported.append(key)
            except SettingsValidationError as exc:
                logger.warning("Could not import %s from %s: %s", key, _options_path, exc)
    if imported:
        logger.info("Imported from %s: %s", _options_path, ", ".join(imported))
    return AppSettings(**kwargs)


def get_settings() -> AppSettings:
    """Return the current settings singleton.

    Cheap and safe — consumers should call this at decision time so
    changes made via :func:`update_settings` propagate without restart.
    """

    if _settings is None:
        # Defensive: if a code path reads settings before init_settings()
        # has run (e.g., an import-time access), return defaults so we
        # don't crash. Startup logs will flag the ordering issue.
        logger.warning("get_settings() called before init_settings(); returning defaults")
        return AppSettings()
    return _settings


async def update_settings(partial: dict[str, Any]) -> AppSettings:
    """Validate, persist, and apply a partial settings update.

    Unknown keys raise :class:`SettingsValidationError`. Values are
    validated per-field; any failure aborts the entire PATCH (no partial
    application). On success, the file is rewritten atomically and the
    in-memory singleton is replaced.
    """

    global _settings

    if not isinstance(partial, dict):
        raise SettingsValidationError("", "expected a JSON object")

    known = {f.name for f in fields(AppSettings)}
    unknown = set(partial) - known
    if unknown:
        # Pick one offending key for the error; log the rest.
        offender = sorted(unknown)[0]
        raise SettingsValidationError(offender, "unknown settings key")

    # Validate every value first so we don't partially apply.
    validated: dict[str, Any] = {}
    for key, value in partial.items():
        validated[key] = _VALIDATORS[key](value, key)

    async with _get_lock():
        current = get_settings()
        merged = AppSettings(**{**asdict(current), **validated})
        _atomic_write(_settings_path, asdict(merged))
        _settings = merged
        logger.info("Settings updated: %s", ", ".join(f"{k}={v!r}" for k, v in validated.items()))
        return merged


def settings_as_dict() -> dict[str, Any]:
    """Convenience: return the current settings as a plain dict."""
    return asdict(get_settings())


def _reset_for_tests() -> None:
    """Test-only: reset module state. Not part of the public API."""
    global _settings, _lock, _settings_path, _options_path
    _settings = None
    _lock = None
    _settings_path = SETTINGS_FILE
    _options_path = OPTIONS_FILE
