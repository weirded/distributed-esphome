"""HA custom-integration auto-installer (HI.8).

On every add-on start, compare the version of the integration bundled
inside the container (`/app/custom_integration/esphome_fleet/manifest.json`)
against whatever is currently at
`/config/custom_components/esphome_fleet/manifest.json`. If it's missing
or outdated, replace it in place.

Safe to run on every boot: only copies when the versions differ. If the
source directory isn't mounted (e.g. during unit tests), returns
quietly. Never crashes the server on a failure — the integration is a
nice-to-have, the add-on must keep running either way.

The actual reload-in-HA step is deliberately NOT automated. Supervisor's
public API doesn't have a reload-integrations endpoint, and calling a
private one would be fragile. Users get a one-line INFO log pointing
them at Settings → Devices & Services when an install/update happens.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


# Source lives inside the container — bundled by the Dockerfile's
# `COPY custom_integration/` at /app/custom_integration/.
DEFAULT_SOURCE_DIR = Path("/app/custom_integration/esphome_fleet")

# HA mounts the user's config at /config via the homeassistant_config map
# (HI.9). Custom integrations live at /config/custom_components/<domain>.
DEFAULT_DESTINATION_DIR = Path("/config/custom_components/esphome_fleet")

# The add-on's VERSION file (bundled by the Dockerfile at /app/VERSION).
# We substitute this into the integration's manifest.json on install so
# HA's "Installed integrations" list shows the same version as the add-on
# itself — #30.
DEFAULT_VERSION_FILE = Path("/app/VERSION")


def _read_manifest_version(manifest_path: Path) -> str | None:
    try:
        with manifest_path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        version = data.get("version")
        return str(version) if version is not None else None
    except FileNotFoundError:
        return None
    except Exception:
        logger.debug("Could not parse %s", manifest_path, exc_info=True)
        return None


def _read_addon_version(version_file: Path) -> str | None:
    try:
        return version_file.read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None
    except Exception:
        logger.debug("Could not read %s", version_file, exc_info=True)
        return None


def _patch_manifest_version(manifest_path: Path, version: str) -> None:
    """Rewrite manifest.json's `version` field atomically (CR.10).

    Write to a sibling tempfile, then `os.replace` over the target —
    either HA sees the pre-patch contents or the fully-patched file,
    never a zero-byte or half-written manifest.
    """
    with manifest_path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    data["version"] = version
    # `delete=False` + `os.replace` is the standard atomic-rewrite
    # pattern. We own the removal on the success path; a crash between
    # the tempfile write and `os.replace` leaves the tempfile orphaned
    # (harmless — no one reads `.esphome_fleet.XXXX.manifest.json`).
    fd, tmp_path = tempfile.mkstemp(
        dir=manifest_path.parent,
        prefix=f".{manifest_path.name}.",
        suffix=".new",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2)
            fp.write("\n")
        os.replace(tmp_path, manifest_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def install_integration(
    source_dir: Path = DEFAULT_SOURCE_DIR,
    destination_dir: Path = DEFAULT_DESTINATION_DIR,
    version_file: Path = DEFAULT_VERSION_FILE,
) -> str:
    """Ensure the custom integration at *destination_dir* matches *source_dir*.

    Returns one of: ``"installed"``, ``"updated"``, ``"unchanged"``,
    ``"skipped_no_source"``, ``"skipped_no_parent"``, ``"failed"``.
    Always catches exceptions — the server must keep booting even if
    this fails.
    """
    if not source_dir.is_dir():
        logger.debug(
            "HA integration source %s not present — skipping auto-install "
            "(expected in dev environments / unit tests)",
            source_dir,
        )
        return "skipped_no_source"

    # #30: prefer the add-on's VERSION file so the integration manifest
    # version moves in lockstep with each release / dev bump. Fall back
    # to whatever is hardcoded in the source manifest only if VERSION is
    # missing (e.g. running out of a dev checkout without the Dockerfile
    # having copied it in).
    source_version = _read_addon_version(version_file) or _read_manifest_version(
        source_dir / "manifest.json"
    )
    if source_version is None:
        logger.warning(
            "HA integration source %s has no readable manifest.json version — "
            "refusing to auto-install to avoid shipping a broken integration",
            source_dir,
        )
        return "failed"

    # /config/custom_components/ parent must exist — if it doesn't,
    # /config wasn't mounted (user hasn't approved read-write access
    # yet, or the add-on is running in an unusual environment).
    parent = destination_dir.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        logger.warning(
            "Couldn't create %s (HA config dir not writable?) — "
            "skipping HA integration auto-install",
            parent,
        )
        return "skipped_no_parent"

    destination_version = _read_manifest_version(destination_dir / "manifest.json")
    if destination_version == source_version:
        logger.info(
            "HA integration esphome_fleet at v%s already installed in %s",
            source_version,
            destination_dir,
        )
        return "unchanged"

    # CR.10: atomic copy-then-replace. The old `rmtree(dest); copytree(src, dest)`
    # pattern left a window where a crash between the two calls would
    # strand /config/custom_components/esphome_fleet/ as missing until the
    # next successful boot. Copy to a sibling `.new` staging dir first,
    # swap it in with `os.replace` (atomic on the same filesystem), then
    # remove the previous tree. Ignore __pycache__ / *.pyc so future edits
    # to the source tree don't leak build cache into user HA config.
    staging_dir = destination_dir.with_name(destination_dir.name + ".new")
    try:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        shutil.copytree(
            source_dir,
            staging_dir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        _patch_manifest_version(staging_dir / "manifest.json", source_version)
        # os.replace works even when the destination already exists and
        # IS a directory, as long as we're on the same filesystem and the
        # new name refers to a directory too. POSIX guarantees atomicity.
        previous_dir = destination_dir.with_name(destination_dir.name + ".old")
        if destination_dir.exists():
            if previous_dir.exists():
                shutil.rmtree(previous_dir)
            os.replace(destination_dir, previous_dir)
        os.replace(staging_dir, destination_dir)
        if previous_dir.exists():
            shutil.rmtree(previous_dir, ignore_errors=True)
    except Exception:
        logger.exception(
            "Failed to copy HA integration %s → %s; add-on will keep running",
            source_dir,
            destination_dir,
        )
        # Best-effort cleanup of the staging tree so we don't wedge on retry.
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        return "failed"

    if destination_version is None:
        logger.info(
            "Installed HA integration esphome_fleet v%s → %s. "
            "Add it via Settings → Devices & Services → ESPHome Fleet.",
            source_version,
            destination_dir,
        )
        return "installed"

    logger.info(
        "Updated HA integration esphome_fleet %s → %s in %s. "
        "Restart Home Assistant to pick up the new version.",
        destination_version,
        source_version,
        destination_dir,
    )
    return "updated"
