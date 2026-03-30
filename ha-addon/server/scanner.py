"""ESPHome config directory scanner and bundle generator."""

from __future__ import annotations

import io
import logging
import tarfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def scan_configs(config_dir: str) -> list[str]:
    """
    Scan *config_dir* for top-level ESPHome YAML config files.

    Returns a list of filenames (not full paths), excluding ``secrets.yaml``.
    """
    base = Path(config_dir)
    if not base.is_dir():
        logger.warning("Config dir %s does not exist or is not a directory", config_dir)
        return []

    results: list[str] = []
    for p in sorted(base.glob("*.yaml")):
        if p.name.startswith("."):
            continue
        if p.name.lower() == "secrets.yaml":
            continue
        results.append(p.name)

    logger.debug("Discovered %d configs in %s: %s", len(results), config_dir, results)
    return results


def create_bundle(config_dir: str) -> bytes:
    """
    Create a tar.gz archive of the entire *config_dir* tree, including
    ``secrets.yaml``.

    Returns raw bytes (the caller is responsible for base64-encoding if needed).
    """
    base = Path(config_dir)
    buf = io.BytesIO()

    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            arcname = str(path.relative_to(base))
            tar.add(str(path), arcname=arcname)
            logger.debug("Added %s to bundle", arcname)

    return buf.getvalue()


def get_device_metadata(config_dir: str, target: str) -> dict:
    """Return display metadata from a YAML config file.

    Returns a dict with keys:
      - friendly_name: str | None  — esphome.friendly_name (substitutions resolved)
      - device_name:   str | None  — esphome.name formatted as title case
      - comment:       str | None  — esphome.comment
    """
    result: dict = {"friendly_name": None, "device_name": None, "comment": None}
    try:
        from esphome.yaml_util import load_yaml  # noqa: PLC0415
        from esphome.components.substitutions import do_substitution_pass  # noqa: PLC0415
        from esphome.core import CORE  # noqa: PLC0415

        path = Path(config_dir) / target
        CORE.config_path = path
        config = load_yaml(path)
        if not isinstance(config, dict):
            return result

        do_substitution_pass(config, None, ignore_missing=True)

        esphome_block = config.get("esphome") or {}
        if isinstance(esphome_block, dict):
            friendly = esphome_block.get("friendly_name")
            if friendly:
                result["friendly_name"] = str(friendly)
            raw_name = esphome_block.get("name")
            if raw_name:
                result["device_name"] = str(raw_name).replace("_", " ").replace("-", " ").title()
            comment = esphome_block.get("comment")
            if comment:
                result["comment"] = str(comment)
        return result
    except Exception:
        logger.debug("Could not parse metadata from %s", target, exc_info=True)
        return result


def get_friendly_name(config_dir: str, target: str) -> Optional[str]:
    """Return the best available display name for a target (backwards compat)."""
    meta = get_device_metadata(config_dir, target)
    return meta["friendly_name"] or meta["device_name"]


def build_name_to_target_map(config_dir: str, targets: list[str]) -> dict[str, str]:
    """Build a mapping from ESPHome device name → YAML filename.

    For each target, parse the ``esphome.name`` field.  If explicitly set, map
    that name to the target.  Always also map the filename stem (without
    extension) so filename-based matching still works as a fallback.
    """
    name_map: dict[str, str] = {}
    for target in targets:
        stem = Path(target).stem
        name_map[stem] = target  # fallback: filename stem
        meta = get_device_metadata(config_dir, target)
        raw_name = meta.get("device_name")
        if raw_name:
            # device_name is title-cased for display; recover the raw name
            # by re-parsing the YAML (get_device_metadata already does this).
            pass
        # Parse raw esphome.name directly (not the title-cased display version)
        try:
            from esphome.yaml_util import load_yaml  # noqa: PLC0415
            from esphome.components.substitutions import do_substitution_pass  # noqa: PLC0415
            from esphome.core import CORE  # noqa: PLC0415

            path = Path(config_dir) / target
            CORE.config_path = path
            config = load_yaml(path)
            if isinstance(config, dict):
                do_substitution_pass(config, None, ignore_missing=True)
                esphome_block = config.get("esphome") or {}
                if isinstance(esphome_block, dict):
                    esph_name = esphome_block.get("name")
                    if esph_name:
                        name_map[str(esph_name)] = target
        except Exception:
            logger.debug("Could not parse esphome.name from %s", target, exc_info=True)
    return name_map


def get_esphome_version() -> str:
    """Return the installed ESPHome package version, or 'unknown' on error."""
    try:
        from importlib.metadata import version  # noqa: PLC0415
        return version("esphome")
    except Exception:
        logger.debug("Could not determine esphome version", exc_info=True)
        return "unknown"
