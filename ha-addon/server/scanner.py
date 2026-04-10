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

# ---------------------------------------------------------------------------
# Per-device metadata stored as a YAML comment block at the top of each file.
# Format:
#   # distributed-esphome:
#   #   pin_version: 2026.3.3
#   #   schedule: 0 2 * * 0
#   #   schedule_enabled: true
# The block is invisible to ESPHome's parser and travels with the file.
# ---------------------------------------------------------------------------

_META_MARKER = "# distributed-esphome:"


def read_device_meta(config_dir: str, target: str) -> dict:
    """Read the ``# distributed-esphome:`` comment block from the top of a YAML file.

    The block must appear at the very top of the file (before any non-comment,
    non-blank line) to avoid matching user comments deeper in the file.

    Returns an empty dict if no block is found or if parsing fails.
    """
    import yaml  # noqa: PLC0415

    path = Path(config_dir) / target
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return {}

    # Scan from the top for the marker. Skip blank lines before it.
    marker_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue  # skip blank lines at the top
        if stripped == _META_MARKER.strip():
            marker_idx = i
            break
        if not stripped.startswith("#"):
            # Hit non-comment content before finding the marker → no block.
            return {}

    if marker_idx is None:
        return {}

    # Collect continuation lines: `#   key: value` (indented under the marker).
    # A continuation line must start with `#` followed by at least 2 spaces of
    # indent (so `#   ` — the marker has 0 indent, children have 2+).
    block_lines: list[str] = []
    for line in lines[marker_idx + 1:]:
        # Continuation: starts with "# " + at least 2 spaces of indent
        if line.startswith("#") and len(line) > 2 and line[1] == " " and line[2] == " ":
            # Strip the "# " prefix (first 2 chars)
            block_lines.append(line[2:])
        else:
            break  # end of block

    if not block_lines:
        return {}

    yaml_text = "\n".join(block_lines)
    try:
        result = yaml.safe_load(yaml_text)
        return result if isinstance(result, dict) else {}
    except Exception:
        logger.debug("Failed to parse device meta for %s", target, exc_info=True)
        return {}


def write_device_meta(config_dir: str, target: str, meta: dict) -> None:
    """Write, replace, or remove the ``# distributed-esphome:`` comment block.

    - Non-empty ``meta``: serializes to YAML, prefixes with ``# ``, inserts
      at the top of the file (before the first non-comment non-blank line).
    - Empty ``meta`` (``{}``): removes any existing block entirely.

    Preserves all other content in the file. Invalidates ``_config_cache``.
    """
    import yaml  # noqa: PLC0415

    path = Path(config_dir) / target
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)

    # 1. Remove any existing block (marker + continuations).
    new_lines: list[str] = []
    in_block = False
    for line in lines:
        stripped = line.strip()
        if not in_block and stripped == _META_MARKER.strip():
            in_block = True
            continue  # skip the marker line
        if in_block:
            # Continuation: "# " + 2+ spaces indent
            raw = line.rstrip("\n").rstrip("\r")
            if raw.startswith("#") and len(raw) > 2 and raw[1] == " " and raw[2] == " ":
                continue  # skip continuation line
            # Also skip the blank line we insert after the block (if any)
            if stripped == "" and not new_lines:
                continue
            in_block = False
        new_lines.append(line)

    # 2. If meta is non-empty, build the new block and prepend.
    if meta:
        # Serialize the dict as YAML (no document markers, default flow off)
        yaml_text = yaml.dump(meta, default_flow_style=False, sort_keys=False)
        # Prefix each line with "#   " (2-space indent under the marker)
        comment_lines = [_META_MARKER + "\n"]
        for yaml_line in yaml_text.splitlines():
            comment_lines.append(f"#   {yaml_line}\n")
        comment_lines.append("\n")  # blank line separator

        # Find insertion point: before the first non-blank non-comment line.
        # If the file starts with other comments (e.g., a shebang or user
        # comment), insert BEFORE them so our block is always first.
        new_lines = comment_lines + new_lines

    # 3. Write back.
    path.write_text("".join(new_lines), encoding="utf-8")

    # 4. Invalidate the config cache for this target.
    _config_cache.pop(target, None)


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
        # #14: detected from the YAML so the UI can gray out the Restart menu
        # item before the user clicks it (rather than letting a click hit the
        # endpoint and fail with "no restart button"). True iff the resolved
        # config has a ``button:`` entry with ``platform: restart``.
        "has_restart_button": False,
        # Network facts surfaced in the Devices tab via toggleable columns (#10).
        # network_type is the first matching connectivity block (wifi → ethernet
        # → openthread); the other three are independent yes/no flags derived
        # from the same block plus the top-level network: component.
        "network_type": None,        # 'wifi' | 'ethernet' | 'thread' | None — primary
        "network_static_ip": False,  # any block has manual_ip.static_ip
        "network_ipv6": False,       # top-level network.enable_ipv6 is true
        "network_ap_fallback": False,  # wifi.ap block configured
        "network_matter": False,     # matter: block present OR openthread: present
        # Per-device metadata from the # distributed-esphome: comment block.
        "pinned_version": None,      # pin_version from comment block
        "schedule": None,            # cron expression (5-field)
        "schedule_enabled": False,   # whether the schedule is active
        "schedule_last_run": None,   # ISO datetime of last triggered run
        "tags": None,                # comma-separated tag string
    }
    # Read the per-device metadata comment block FIRST — it's cheap (text scan,
    # no YAML resolution) and provides fields the rest of this function doesn't.
    device_meta = read_device_meta(config_dir, target)
    if device_meta:
        result["pinned_version"] = device_meta.get("pin_version")
        result["schedule"] = device_meta.get("schedule")
        result["schedule_enabled"] = device_meta.get("schedule_enabled", False)
        result["schedule_last_run"] = device_meta.get("schedule_last_run")
        result["tags"] = device_meta.get("tags")

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

    # #14: detect a `button: - platform: restart` entry in the resolved config.
    # ESPHome's button component is a list — scan all entries.
    button_block = config.get("button")
    if isinstance(button_block, list):
        for entry in button_block:
            if isinstance(entry, dict) and entry.get("platform") == "restart":
                result["has_restart_button"] = True
                break

    # Network type detection (#10). Track each block independently — a matter
    # device often has BOTH wifi (from a common include) AND openthread (the
    # actual network it uses). Picking the "first match wins" by literal block
    # order gives the wrong answer for matter-test.yaml (#13). Precedence for
    # the *primary* type label: openthread > ethernet > wifi, because more
    # specific signals beat the lowest-common-denominator wifi.
    blocks = {
        "wifi": isinstance(config.get("wifi"), dict),
        "ethernet": isinstance(config.get("ethernet"), dict),
        "openthread": isinstance(config.get("openthread"), dict),
    }
    if blocks["openthread"]:
        result["network_type"] = "thread"
    elif blocks["ethernet"]:
        result["network_type"] = "ethernet"
    elif blocks["wifi"]:
        result["network_type"] = "wifi"

    # Static-IP detection: scan ALL present blocks; any one with
    # manual_ip.static_ip flips the flag (a multi-block config might be
    # static on one and DHCP on another — surfacing "static" in that case
    # is the safer signal for the user).
    for name in ("wifi", "ethernet", "openthread"):
        if not blocks[name]:
            continue
        block = config.get(name)
        manual_ip = block.get("manual_ip") if isinstance(block, dict) else None
        if isinstance(manual_ip, dict) and manual_ip.get("static_ip"):
            result["network_static_ip"] = True
            break

    # AP fallback is wifi-only.
    wifi_block = config.get("wifi") if blocks["wifi"] else None
    if isinstance(wifi_block, dict) and isinstance(wifi_block.get("ap"), dict):
        result["network_ap_fallback"] = True

    # IPv6: top-level network: component with enable_ipv6: true. ESPHome
    # exposes this as a config-time flag; runtime IPv6 capability is implied
    # by the chip + network stack but the YAML toggle is the user's choice.
    network_block = config.get("network")
    if isinstance(network_block, dict) and network_block.get("enable_ipv6") is True:
        result["network_ipv6"] = True

    # Matter detection (#13). ESPHome 2024+ has an experimental ``matter:``
    # top-level component. The ``openthread:`` component, in ESPHome's data
    # model, only exists in the context of Matter support — there's no
    # "Thread without Matter" path. So either signal flips the flag.
    if isinstance(config.get("matter"), dict) or blocks["openthread"]:
        result["network_matter"] = True


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


def get_device_address(config: dict, device_name: str) -> tuple[str, str]:
    """Return the canonical address ESPHome would use for a device, plus its source.

    Mirrors ESPHome's own resolver in ``esphome.core.CORE.address``: walks
    ``wifi`` → ``ethernet`` → ``openthread`` in order, and for each block honors
    ``use_address`` → ``manual_ip.static_ip`` → ``{device_name}.local``.

    Used by ``build_name_to_target_map`` so we register an `address_override`
    for EVERY target, not just wifi-with-explicit-use_address. Without this,
    Thread-only and statically-IP'd devices have no proactive Device row, and
    any later mDNS discovery creates a duplicate row instead of merging into
    the YAML-derived one (bug #179).

    Returns ``(address, source)`` where source is one of:
      - ``"wifi_use_address"``, ``"ethernet_use_address"``, ``"openthread_use_address"``
      - ``"wifi_static_ip"``, ``"ethernet_static_ip"``
      - ``"mdns_default"`` — fell back to ``{device_name}.local``

    The source is exposed in the UI so users can see how each device's IP
    was resolved (#184).
    """
    fallback = (f"{device_name}.local", "mdns_default")

    if not isinstance(config, dict):
        return fallback

    for block_name in ("wifi", "ethernet", "openthread"):
        block = config.get(block_name)
        if not isinstance(block, dict):
            continue

        # 1. Explicit use_address always wins
        use_addr = block.get("use_address")
        if use_addr:
            return (str(use_addr), f"{block_name}_use_address")

        # 2. manual_ip.static_ip is the second choice
        manual_ip = block.get("manual_ip")
        if isinstance(manual_ip, dict):
            static_ip = manual_ip.get("static_ip")
            if static_ip:
                return (str(static_ip), f"{block_name}_static_ip")

        # If we found this block but neither key, fall through to mDNS .local
        return fallback

    return fallback


def build_name_to_target_map(
    config_dir: str, targets: list[str],
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    """Build a mapping from ESPHome device name → YAML filename.

    For each target, resolve the full config (including packages) and extract
    ``esphome.name``.  Always also map the filename stem so filename-based
    matching works as a fallback.

    Returns ``(name_map, encryption_keys, address_overrides, address_sources)``:
    - ``encryption_keys`` maps device names to base64-encoded noise PSK keys
    - ``address_overrides`` maps device names to the canonical address from
      ``get_device_address`` (always populated, even if it's just
      ``{device_name}.local``).
    - ``address_sources`` maps device names to the source of the address
      (``wifi_use_address``, ``wifi_static_ip``, ``ethernet_use_address``,
      ``ethernet_static_ip``, ``openthread_use_address``, ``mdns_default``).
      Used by the UI to show where each IP came from (#184).
    """
    name_map: dict[str, str] = {}
    encryption_keys: dict[str, str] = {}
    address_overrides: dict[str, str] = {}
    address_sources: dict[str, str] = {}
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

        # Always register an address override — get_device_address handles
        # wifi/ethernet/openthread with use_address, manual_ip.static_ip, and
        # {name}.local fallback. This ensures every YAML target has a
        # proactive Device row that mDNS discovery can merge into instead of
        # duplicating (bug #179).
        addr, src = get_device_address(config, key_name)
        address_overrides[key_name] = addr
        address_sources[key_name] = src
    return name_map, encryption_keys, address_overrides, address_sources


