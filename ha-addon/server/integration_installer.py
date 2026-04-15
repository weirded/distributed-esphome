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
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


# Source lives inside the container — bundled by the Dockerfile's
# `COPY custom_integration/` at /app/custom_integration/.
DEFAULT_SOURCE_DIR = Path("/app/custom_integration/esphome_fleet")

# HA mounts the user's config at /config via the homeassistant_config map
# (HI.9). Custom integrations live at /config/custom_components/<domain>.
DEFAULT_DESTINATION_DIR = Path("/config/custom_components/esphome_fleet")


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


def install_integration(
    source_dir: Path = DEFAULT_SOURCE_DIR,
    destination_dir: Path = DEFAULT_DESTINATION_DIR,
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

    source_version = _read_manifest_version(source_dir / "manifest.json")
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

    try:
        if destination_dir.exists():
            shutil.rmtree(destination_dir)
        shutil.copytree(source_dir, destination_dir)
    except Exception:
        logger.exception(
            "Failed to copy HA integration %s → %s; add-on will keep running",
            source_dir,
            destination_dir,
        )
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
