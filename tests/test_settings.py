"""Unit tests for the in-app Settings store (SP.*).

Covers:
- Dataclass defaults.
- First-boot creation with dataclass defaults when no options.json.
- First-boot import from options.json for migrated fields (SP.2).
- Subsequent boots don't re-import.
- Round-trip load/save.
- Atomic write leaves no half-written settings.json on simulated crash.
- update_settings() validates + persists + rotates the singleton.
- Validation errors raise SettingsValidationError with the field name.
- Unknown keys in PATCH are rejected.
- get_settings() sees mutations immediately (live-effect floor).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import settings as settings_mod
from settings import (
    AppSettings,
    SettingsValidationError,
    get_settings,
    init_settings,
    settings_as_dict,
    update_settings,
)


@pytest.fixture(autouse=True)
def _reset():
    """Reset the module singleton between tests."""
    settings_mod._reset_for_tests()
    yield
    settings_mod._reset_for_tests()


# ---------------------------------------------------------------------------
# Defaults + first-boot
# ---------------------------------------------------------------------------


def test_dataclass_defaults_match_spec():
    s = AppSettings()
    assert s.auto_commit_on_save is True
    assert s.git_author_name == "HA User"
    assert s.git_author_email == "ha@distributed-esphome.local"
    assert s.job_history_retention_days == 365
    assert s.firmware_cache_max_gb == 2.0
    assert s.job_log_retention_days == 30


async def test_update_settings_accepts_git_author(tmp_path):
    init_settings(settings_path=tmp_path / "s.json", options_path=tmp_path / "o.json")
    updated = await update_settings({
        "git_author_name": "Stefan Zier",
        "git_author_email": "stefan@zier.com",
    })
    assert updated.git_author_name == "Stefan Zier"
    assert updated.git_author_email == "stefan@zier.com"


async def test_update_settings_trims_git_author_whitespace(tmp_path):
    init_settings(settings_path=tmp_path / "s.json", options_path=tmp_path / "o.json")
    updated = await update_settings({"git_author_name": "  Stefan Zier  "})
    assert updated.git_author_name == "Stefan Zier"


async def test_update_settings_rejects_empty_git_author_name(tmp_path):
    init_settings(settings_path=tmp_path / "s.json", options_path=tmp_path / "o.json")
    with pytest.raises(SettingsValidationError) as exc:
        await update_settings({"git_author_name": "   "})
    assert exc.value.field == "git_author_name"


async def test_update_settings_rejects_overlong_git_author_email(tmp_path):
    init_settings(settings_path=tmp_path / "s.json", options_path=tmp_path / "o.json")
    with pytest.raises(SettingsValidationError) as exc:
        await update_settings({"git_author_email": "a" * 500 + "@x.com"})
    assert exc.value.field == "git_author_email"


def test_init_creates_settings_file_when_absent(tmp_path: Path):
    settings_file = tmp_path / "settings.json"
    options_file = tmp_path / "options.json"  # doesn't exist

    s = init_settings(settings_path=settings_file, options_path=options_file)

    assert settings_file.exists()
    on_disk = json.loads(settings_file.read_text())
    assert on_disk == {
        "auto_commit_on_save": True,
        "git_author_name": "HA User",
        "git_author_email": "ha@distributed-esphome.local",
        "job_history_retention_days": 365,
        "firmware_cache_max_gb": 2.0,
        "job_log_retention_days": 30,
    }
    assert s == AppSettings()


def test_init_imports_migrated_fields_from_options_json(tmp_path: Path):
    """SP.2: first boot seeds migrated fields from options.json."""
    settings_file = tmp_path / "settings.json"
    options_file = tmp_path / "options.json"
    options_file.write_text(json.dumps({
        # Migrated fields:
        "job_history_retention_days": 90,
        "firmware_cache_max_gb": 5.0,
        "job_log_retention_days": 7,
        # Non-migrated — should be ignored:
        "token": "abc",
        "worker_offline_threshold": 60,
    }))

    s = init_settings(settings_path=settings_file, options_path=options_file)

    assert s.job_history_retention_days == 90
    assert s.firmware_cache_max_gb == 5.0
    assert s.job_log_retention_days == 7
    # Not imported: dataclass default preserved
    assert s.auto_commit_on_save is True

    on_disk = json.loads(settings_file.read_text())
    assert on_disk["job_history_retention_days"] == 90
    assert on_disk["firmware_cache_max_gb"] == 5.0


def test_init_does_not_reimport_on_subsequent_boots(tmp_path: Path):
    """SP.2: idempotent — once settings.json exists, options.json is ignored."""
    settings_file = tmp_path / "settings.json"
    options_file = tmp_path / "options.json"

    # Seed settings.json with a specific value.
    settings_file.write_text(json.dumps({
        "auto_commit_on_save": False,
        "job_history_retention_days": 30,
        "firmware_cache_max_gb": 1.0,
        "job_log_retention_days": 5,
    }))
    # options.json has very different values — must be ignored.
    options_file.write_text(json.dumps({
        "job_history_retention_days": 999,
        "firmware_cache_max_gb": 99.0,
    }))

    s = init_settings(settings_path=settings_file, options_path=options_file)

    assert s.auto_commit_on_save is False
    assert s.job_history_retention_days == 30
    assert s.firmware_cache_max_gb == 1.0


def test_init_tolerates_invalid_option_values_during_import(tmp_path: Path):
    """Garbage in options.json shouldn't crash startup."""
    settings_file = tmp_path / "settings.json"
    options_file = tmp_path / "options.json"
    options_file.write_text(json.dumps({
        "job_history_retention_days": "not-a-number",
        "firmware_cache_max_gb": -1.0,  # below floor
    }))

    s = init_settings(settings_path=settings_file, options_path=options_file)

    # Invalid imports fall back to dataclass defaults, don't crash.
    assert s.job_history_retention_days == 365
    assert s.firmware_cache_max_gb == 2.0


def test_init_tolerates_malformed_settings_file(tmp_path: Path):
    """Load-time: corrupt JSON leaves us with defaults rather than crashing."""
    settings_file = tmp_path / "settings.json"
    options_file = tmp_path / "options.json"
    settings_file.write_text("not json at all {")

    s = init_settings(settings_path=settings_file, options_path=options_file)

    assert s == AppSettings()


def test_init_tolerates_invalid_value_in_settings_file(tmp_path: Path):
    settings_file = tmp_path / "settings.json"
    options_file = tmp_path / "options.json"
    settings_file.write_text(json.dumps({
        "auto_commit_on_save": True,
        "job_history_retention_days": -5,  # below floor
        "firmware_cache_max_gb": 2.0,
        "job_log_retention_days": 30,
    }))

    s = init_settings(settings_path=settings_file, options_path=options_file)

    # Invalid value falls back to default, other values load correctly.
    assert s.job_history_retention_days == 365
    assert s.auto_commit_on_save is True


def test_init_ignores_unknown_keys_in_settings_file(tmp_path: Path, caplog):
    settings_file = tmp_path / "settings.json"
    options_file = tmp_path / "options.json"
    settings_file.write_text(json.dumps({
        "auto_commit_on_save": False,
        "future_feature_flag": True,  # not in dataclass
    }))

    with caplog.at_level("WARNING"):
        s = init_settings(settings_path=settings_file, options_path=options_file)

    assert s.auto_commit_on_save is False
    assert any("future_feature_flag" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# update_settings (PATCH)
# ---------------------------------------------------------------------------


async def test_update_settings_persists_and_rotates_singleton(tmp_path: Path):
    settings_file = tmp_path / "settings.json"
    options_file = tmp_path / "options.json"
    init_settings(settings_path=settings_file, options_path=options_file)

    assert get_settings().auto_commit_on_save is True

    updated = await update_settings({"auto_commit_on_save": False})

    assert updated.auto_commit_on_save is False
    # Singleton updated:
    assert get_settings().auto_commit_on_save is False
    # Disk updated:
    on_disk = json.loads(settings_file.read_text())
    assert on_disk["auto_commit_on_save"] is False


async def test_update_settings_partial_leaves_unspecified_unchanged(tmp_path: Path):
    init_settings(settings_path=tmp_path / "s.json", options_path=tmp_path / "o.json")
    await update_settings({"job_history_retention_days": 90})
    s = get_settings()
    assert s.job_history_retention_days == 90
    assert s.auto_commit_on_save is True  # unchanged
    assert s.firmware_cache_max_gb == 2.0  # unchanged


async def test_update_settings_rejects_unknown_key(tmp_path: Path):
    init_settings(settings_path=tmp_path / "s.json", options_path=tmp_path / "o.json")
    with pytest.raises(SettingsValidationError) as exc:
        await update_settings({"totally_fake_key": 1})
    assert exc.value.field == "totally_fake_key"


async def test_update_settings_rejects_out_of_range(tmp_path: Path):
    init_settings(settings_path=tmp_path / "s.json", options_path=tmp_path / "o.json")
    with pytest.raises(SettingsValidationError) as exc:
        await update_settings({"job_history_retention_days": -1})
    assert exc.value.field == "job_history_retention_days"


async def test_update_settings_rejects_non_numeric(tmp_path: Path):
    init_settings(settings_path=tmp_path / "s.json", options_path=tmp_path / "o.json")
    with pytest.raises(SettingsValidationError) as exc:
        await update_settings({"firmware_cache_max_gb": "lots"})
    assert exc.value.field == "firmware_cache_max_gb"


async def test_update_settings_coerces_string_bool(tmp_path: Path):
    """HA options.json sometimes delivers booleans as strings; tolerate that."""
    init_settings(settings_path=tmp_path / "s.json", options_path=tmp_path / "o.json")
    updated = await update_settings({"auto_commit_on_save": "false"})
    assert updated.auto_commit_on_save is False


async def test_update_settings_aborts_on_any_invalid_field(tmp_path: Path):
    """No partial application — one bad field kills the whole PATCH."""
    init_settings(settings_path=tmp_path / "s.json", options_path=tmp_path / "o.json")
    with pytest.raises(SettingsValidationError):
        await update_settings({
            "auto_commit_on_save": False,             # valid
            "job_history_retention_days": -1,         # invalid
        })
    # auto_commit_on_save should NOT have been applied.
    assert get_settings().auto_commit_on_save is True


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------


def test_atomic_write_leaves_no_tempfile_on_success(tmp_path: Path):
    settings_file = tmp_path / "settings.json"
    options_file = tmp_path / "options.json"
    init_settings(settings_path=settings_file, options_path=options_file)

    # Only settings.json should be in the directory (no temp files).
    contents = [p.name for p in tmp_path.iterdir()]
    assert "settings.json" in contents
    assert not any(p.startswith("settings.json.") for p in contents)


def test_atomic_write_failure_does_not_corrupt_existing_file(tmp_path: Path):
    """If os.replace raises, the existing settings.json must survive intact."""
    settings_file = tmp_path / "settings.json"
    options_file = tmp_path / "options.json"
    init_settings(settings_path=settings_file, options_path=options_file)

    original_content = settings_file.read_text()

    with patch("settings.os.replace", side_effect=OSError("simulated disk error")):
        with pytest.raises(OSError):
            settings_mod._atomic_write(settings_file, {"bogus": 1})

    # Original content intact.
    assert settings_file.read_text() == original_content
    # No orphaned tempfile.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith("settings.json.")]
    assert leftovers == []


# ---------------------------------------------------------------------------
# Live-effect (SP.5 floor)
# ---------------------------------------------------------------------------


async def test_get_settings_sees_update_immediately(tmp_path: Path):
    """The whole point of the Settings design — reads after a PATCH see new value."""
    init_settings(settings_path=tmp_path / "s.json", options_path=tmp_path / "o.json")
    assert get_settings().job_history_retention_days == 365
    await update_settings({"job_history_retention_days": 10})
    assert get_settings().job_history_retention_days == 10


def test_settings_as_dict_round_trips():
    """settings_as_dict is used by the REST GET handler."""
    with patch("settings._settings", AppSettings(auto_commit_on_save=False)):
        out = settings_as_dict()
    assert out == {
        "auto_commit_on_save": False,
        "git_author_name": "HA User",
        "git_author_email": "ha@distributed-esphome.local",
        "job_history_retention_days": 365,
        "firmware_cache_max_gb": 2.0,
        "job_log_retention_days": 30,
    }


def test_get_settings_before_init_returns_defaults_and_warns(caplog):
    """Defensive: wrong ordering shouldn't crash, just log."""
    with caplog.at_level("WARNING"):
        s = get_settings()
    assert s == AppSettings()
    assert any("before init_settings" in r.message for r in caplog.records)
