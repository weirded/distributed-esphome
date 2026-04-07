"""ESPHome config directory scanner and bundle generator."""

from __future__ import annotations

import io
import logging
import tarfile
from pathlib import Path
from typing import Optional

from constants import SECRETS_YAML

logger = logging.getLogger(__name__)

# Module-level selected version; set at startup and via POST /ui/api/esphome-version.
# None means "fall back to the installed package version".
_selected_esphome_version: Optional[str] = None


def set_esphome_version(version: str) -> None:
    """Set the active ESPHome version used for new compile jobs."""
    global _selected_esphome_version
    _selected_esphome_version = version
    logger.info("ESPHome version set to %s", version)


def get_esphome_version() -> str:
    """Return the active ESPHome version.

    Priority:
    1. Explicitly set version (via ``set_esphome_version`` or the UI).
    2. Installed ESPHome package (``importlib.metadata``).
    3. Fallback: ``"unknown"``.
    """
    if _selected_esphome_version:
        return _selected_esphome_version
    return _get_installed_esphome_version()


def _get_installed_esphome_version() -> str:
    """Return the installed ESPHome package version, or 'unknown' on error."""
    try:
        from importlib.metadata import version  # noqa: PLC0415
        return version("esphome")
    except Exception:
        logger.debug("Could not determine esphome version", exc_info=True)
        return "unknown"


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
        if p.name.lower() == SECRETS_YAML:
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
            # Skip macOS resource fork files and metadata noise
            if path.name.startswith("._") or path.name == ".DS_Store":
                logger.debug("Skipping resource fork file: %s", path)
                continue
            arcname = str(path.relative_to(base))
            tar.add(str(path), arcname=arcname)
            logger.debug("Added %s to bundle", arcname)

    return buf.getvalue()


# Cache resolved configs by (target, mtime) to avoid repeated git clones
_config_cache: dict[str, tuple[float, dict]] = {}  # target → (mtime, resolved_config)


def _resolve_esphome_config(config_dir: str, target: str) -> Optional[dict]:
    """Fully resolve an ESPHome YAML config including packages and substitutions.

    Uses ESPHome's own resolution pipeline so that ``packages:``, ``!include``,
    and ``${substitutions}`` are all handled identically to ``esphome compile``.

    Results are cached by file mtime — only re-resolved when the file changes.

    Returns the resolved config dict, or None on error.
    """
    try:
        path = Path(config_dir) / target
        mtime = path.stat().st_mtime

        # Return cached result if mtime hasn't changed
        cached = _config_cache.get(target)
        if cached and cached[0] == mtime:
            return cached[1]

        from esphome.yaml_util import load_yaml  # noqa: PLC0415
        from esphome.components.substitutions import do_substitution_pass  # noqa: PLC0415
        from esphome.components.packages import do_packages_pass, merge_packages  # noqa: PLC0415
        from esphome.core import CORE  # noqa: PLC0415

        CORE.config_path = path
        config = load_yaml(path)
        if not isinstance(config, dict):
            return None

        # Resolve packages (local + remote includes). Skip git updates if we
        # already have a cached result for any version of this file — the first
        # resolution will clone, subsequent ones reuse the local checkout.
        already_resolved = target in _config_cache
        config = do_packages_pass(config, skip_update=already_resolved)
        config = merge_packages(config)

        # Resolve ${substitutions}
        do_substitution_pass(config, None, ignore_missing=True)

        _config_cache[target] = (mtime, config)
        return config
    except Exception:
        logger.debug("Could not resolve config for %s", target, exc_info=True)
        return None


def get_device_metadata(config_dir: str, target: str) -> dict:
    """Return display metadata from a YAML config file.

    Returns a dict with keys:
      - friendly_name:  str | None  — esphome.friendly_name (substitutions resolved)
      - device_name:    str | None  — esphome.name formatted as title case
      - comment:        str | None  — esphome.comment
      - area:           str | None  — esphome.area
      - project_name:   str | None  — esphome.project.name
      - project_version:str | None  — esphome.project.version
      - has_web_server: bool        — True if the web_server component is present
    """
    result: dict = {
        "friendly_name": None,
        "device_name": None,
        "device_name_raw": None,  # raw esphome.name value (hyphens/underscores preserved)
        "comment": None,
        "area": None,
        "project_name": None,
        "project_version": None,
        "has_web_server": False,
    }
    config = _resolve_esphome_config(config_dir, target)
    if config is not None:
        _extract_metadata(config, result)

    # Fallback: if full resolution failed or left gaps, try raw YAML for
    # literal fields (area, comment, project) that don't need substitution.
    if config is None or result["area"] is None:
        raw_config = _load_raw_yaml(config_dir, target)
        if raw_config is not None:
            _fill_missing_metadata(raw_config, result)

    return result


def _extract_metadata(config: dict, result: dict) -> None:
    """Extract all metadata fields from a fully resolved ESPHome config."""
    esphome_block = config.get("esphome") or {}
    if isinstance(esphome_block, dict):
        friendly = esphome_block.get("friendly_name")
        if friendly:
            result["friendly_name"] = str(friendly)
        raw_name = esphome_block.get("name")
        if raw_name:
            result["device_name_raw"] = str(raw_name)
            result["device_name"] = str(raw_name).replace("_", " ").replace("-", " ").title()
        comment = esphome_block.get("comment")
        if comment:
            result["comment"] = str(comment)
        area = esphome_block.get("area")
        if area:
            result["area"] = str(area)
        project = esphome_block.get("project")
        if isinstance(project, dict):
            pname = project.get("name")
            if pname:
                result["project_name"] = str(pname)
            pver = project.get("version")
            if pver:
                result["project_version"] = str(pver)

    # Detect presence of the web_server component
    if config.get("web_server") is not None:
        result["has_web_server"] = True


def _is_literal(value: str) -> bool:
    """Return True if value is a literal string (no unresolved ${substitutions})."""
    return "${" not in value


def _load_raw_yaml(config_dir: str, target: str) -> Optional[dict]:
    """Load a YAML file with a permissive loader (ignores !include, !secret, etc.)."""
    try:
        import yaml  # noqa: PLC0415

        class _PermissiveLoader(yaml.SafeLoader):
            pass

        def _passthrough(loader, node):  # type: ignore
            if isinstance(node, yaml.ScalarNode):
                return loader.construct_scalar(node)
            if isinstance(node, yaml.SequenceNode):
                return loader.construct_sequence(node)
            if isinstance(node, yaml.MappingNode):
                return loader.construct_mapping(node)
            return None

        _PermissiveLoader.add_constructor(None, _passthrough)  # type: ignore[arg-type]

        raw_path = Path(config_dir) / target
        with open(raw_path, encoding="utf-8") as f:
            config = yaml.load(f, Loader=_PermissiveLoader)  # noqa: S506
        return config if isinstance(config, dict) else None
    except Exception:
        return None


def _resolve_simple_subs(value: str, subs: dict) -> str:
    """Resolve simple ${key} substitutions from a dict. Returns the value with substitutions applied."""
    import re  # noqa: PLC0415
    def _replace(m: re.Match) -> str:
        key = m.group(1)
        return str(subs.get(key, m.group(0)))
    return re.sub(r'\$\{(\w+)\}', _replace, value)


def _fill_missing_metadata(raw_config: dict, result: dict) -> None:
    """Fill gaps in result from raw (unresolved) YAML.

    Resolves simple ${key} substitutions from the substitutions block.
    Never overwrites values already set by the full ESPHome resolution.
    """
    subs = raw_config.get("substitutions") or {}
    if not isinstance(subs, dict):
        subs = {}

    def _resolve(val: str) -> Optional[str]:
        """Resolve substitutions and return the value if it's fully resolved."""
        if not val:
            return None
        resolved = _resolve_simple_subs(str(val), subs)
        return resolved if _is_literal(resolved) else None

    esphome_block = raw_config.get("esphome") or {}
    if isinstance(esphome_block, dict):
        if result["friendly_name"] is None:
            result["friendly_name"] = _resolve(esphome_block.get("friendly_name") or "")
        if result["device_name"] is None:
            raw_name = _resolve(esphome_block.get("name") or "")
            if raw_name:
                result["device_name_raw"] = raw_name
                result["device_name"] = raw_name.replace("_", " ").replace("-", " ").title()
        if result["comment"] is None:
            result["comment"] = _resolve(esphome_block.get("comment") or "")
        if result["area"] is None:
            result["area"] = _resolve(esphome_block.get("area") or "")
        if result["project_name"] is None:
            project = esphome_block.get("project")
            if isinstance(project, dict):
                result["project_name"] = _resolve(project.get("name") or "")
                if result["project_version"] is None:
                    result["project_version"] = _resolve(project.get("version") or "")

    # Check substitutions for area as last resort
    if result["area"] is None:
        sub_area = subs.get("area")
        if sub_area and _is_literal(str(sub_area)):
            result["area"] = str(sub_area)


def get_friendly_name(config_dir: str, target: str) -> Optional[str]:
    """Return the best available display name for a target (backwards compat)."""
    meta = get_device_metadata(config_dir, target)
    return meta["friendly_name"] or meta["device_name"]


def build_name_to_target_map(
    config_dir: str, targets: list[str],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Build a mapping from ESPHome device name → YAML filename.

    For each target, resolve the full config (including packages) and extract
    ``esphome.name``.  Always also map the filename stem so filename-based
    matching works as a fallback.

    Returns (name_map, encryption_keys, address_overrides) where:
    - encryption_keys maps device names to base64-encoded noise PSK keys
    - address_overrides maps device names to wifi.use_address values
    """
    name_map: dict[str, str] = {}
    encryption_keys: dict[str, str] = {}
    address_overrides: dict[str, str] = {}
    for target in targets:
        stem = Path(target).stem
        name_map[stem] = target  # fallback: filename stem

        config = _resolve_esphome_config(config_dir, target)
        if config is None:
            continue
        esphome_block = config.get("esphome") or {}
        device_name: Optional[str] = None
        if isinstance(esphome_block, dict):
            esph_name = esphome_block.get("name")
            if esph_name:
                device_name = str(esph_name)
                name_map[device_name] = target
                # Also map the underscore-normalized variant so mDNS names
                # (which replace hyphens with underscores) resolve correctly.
                normalized = device_name.replace("-", "_")
                if normalized != device_name:
                    name_map[normalized] = target

        key_name = device_name or stem

        # Extract API encryption key if present
        api_block = config.get("api") or {}
        if isinstance(api_block, dict):
            enc_block = api_block.get("encryption") or {}
            if isinstance(enc_block, dict):
                key = enc_block.get("key")
                if key:
                    encryption_keys[key_name] = str(key)

        # Extract wifi.use_address override if present
        wifi_block = config.get("wifi") or {}
        if isinstance(wifi_block, dict):
            use_addr = wifi_block.get("use_address")
            if use_addr:
                address_overrides[key_name] = str(use_addr)
    return name_map, encryption_keys, address_overrides


