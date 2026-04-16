"""ESPHome config directory scanner and bundle generator."""

from __future__ import annotations

import io
import logging
import subprocess
import sys
import tarfile
import threading
from pathlib import Path
from typing import Optional

from constants import SECRETS_YAML

logger = logging.getLogger(__name__)

# Module-level selected version; set at startup and via POST /ui/api/esphome-version.
# None means "fall back to the installed package version".
_selected_esphome_version: Optional[str] = None

# ---------------------------------------------------------------------------
# SE.2 / SE.3 / SE.7 — Server-side ESPHome lazy install
# ---------------------------------------------------------------------------
#
# The server used to bake ESPHome into its Docker image (`esphome` in
# requirements.txt). That was the source of #51 (version bump breaks the
# lock), #56-class (macOS-only transitives leaking in), and #20 (upstream
# API changes invisible until re-bump). SE.1 drops that baked-in package;
# SE.2 replaces it with a lazy install into `/data/esphome-versions/<ver>/`
# via the `VersionManager` already used by workers.
#
# Lifecycle:
#   - on_startup schedules `ensure_esphome_installed(version)` as a
#     background task.
#   - `VersionManager.ensure_version` creates a venv + pip-installs ESPHome.
#   - On success we prepend `<venv>/lib/python{M.N}/site-packages/` to
#     sys.path (SE.3) so the deferred `import esphome.*` in
#     `_resolve_esphome_config` picks up the venv copy.
#   - Until that ready-event fires, callers that need ESPHome see
#     `_server_esphome_venv is None` and degrade gracefully:
#     `_resolve_esphome_config` returns None (callers already tolerate it);
#     `validate_config` returns 503; `get_esphome_version` returns
#     "installing".
#
# Why module globals instead of an app-attached singleton: `scanner` is
# imported by main.py, ui_api.py, and the scheduler at module load time.
# The import-level function-scoped `from esphome.* import` calls in
# `_resolve_esphome_config` need the venv on sys.path *before* they run.
# Module globals + idempotent activation is the simplest way to guarantee
# that ordering without threading the app instance through every caller.

_server_esphome_venv: Optional[Path] = None
_server_esphome_bin: Optional[str] = None
_esphome_ready: threading.Event = threading.Event()
_esphome_install_failed: bool = False
# Per-process memoized `esphome version` output (SE.7). Runs a subprocess
# the first time, caches the result so the 1 Hz polling endpoints don't
# fork-exec repeatedly. Cleared on re-install via `set_esphome_version`.
_esphome_version_cache: Optional[str] = None


def _activate_esphome_venv(venv_path: Path) -> bool:
    """Prepend *venv_path*'s site-packages onto ``sys.path`` (SE.3).

    Idempotent — re-activating the same venv is a no-op. Returns True on
    success, False if the site-packages directory can't be located (venv
    is malformed / interpreter mismatch).
    """
    # site-packages lives at <venv>/lib/pythonX.Y/site-packages. Resolve
    # X.Y from the running interpreter — the VersionManager creates venvs
    # using `sys.executable` so this always matches.
    site_dir = (
        venv_path / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    )
    if not site_dir.is_dir():
        logger.warning("venv site-packages missing at %s", site_dir)
        return False
    site_str = str(site_dir)
    if site_str in sys.path:
        return True
    sys.path.insert(0, site_str)
    logger.info("Activated ESPHome venv on sys.path: %s", site_str)
    return True


def ensure_esphome_installed(
    version: str,
    *,
    versions_base: Path = Path("/data/esphome-versions"),
    max_versions: int = 5,
) -> None:
    """Install ESPHome *version* into the server's venv cache (SE.2).

    Blocking — intended to run inside an executor (see
    `main.on_startup`). On success, sets module globals + fires
    `_esphome_ready`. On failure, flips `_esphome_install_failed` to
    True and leaves the event clear; callers degrade gracefully.

    Idempotent: a second call for the same version is a fast cache hit
    inside VersionManager and just re-activates the venv on sys.path.
    """
    global _server_esphome_venv, _server_esphome_bin, _esphome_install_failed
    global _esphome_version_cache

    # VersionManager lives in the bundled client code. In production the
    # Dockerfile copies client/ to /app/client; locally the test harness
    # has client on sys.path via conftest. Cover both.
    if "/app/client" not in sys.path:
        sys.path.insert(0, "/app/client")
    try:
        from version_manager import VersionManager  # noqa: PLC0415
    except ImportError:
        logger.warning(
            "version_manager unavailable — cannot lazy-install ESPHome. "
            "Running off the bundled package (see SE.1)."
        )
        _esphome_install_failed = True
        return

    logger.info("Installing ESPHome %s into %s (may take 1–3 min on first run)", version, versions_base)
    try:
        vm = VersionManager(versions_base=versions_base, max_versions=max_versions)
        bin_path = vm.ensure_version(version)
    except Exception:
        logger.exception("ensure_esphome_installed(%s) failed", version)
        _esphome_install_failed = True
        return

    venv_path = Path(bin_path).parent.parent  # <venv>/bin/esphome → <venv>
    if not _activate_esphome_venv(venv_path):
        _esphome_install_failed = True
        return

    _server_esphome_venv = venv_path
    _server_esphome_bin = bin_path
    _esphome_install_failed = False
    # Bust the version cache — a fresh install may have a different
    # version from what we previously reported (e.g. after a refresh).
    _esphome_version_cache = None
    _esphome_ready.set()
    logger.info("ESPHome %s ready at %s", version, bin_path)


def set_esphome_version(version: str) -> None:
    """Set the active ESPHome version used for new compile jobs."""
    global _selected_esphome_version, _esphome_version_cache
    previous = _selected_esphome_version
    _selected_esphome_version = version
    # SE.7: drop the cached CLI-probed version when the selected version
    # changes. Next `_get_installed_esphome_version` call will re-probe.
    if previous != version:
        _esphome_version_cache = None
    # SP.3 cleanup: the three callers (on_startup, pypi_version_refresher,
    # ui_api.set_esphome_version_handler) each log their own INFO message
    # with the right context ("Active ESPHome version: X", "…detected: X",
    # "…changed to X via UI"). This helper firing its own INFO alongside
    # duplicated the message at startup and added log noise.
    logger.debug("ESPHome version set to %s", version)
    # #55: broadcast so HA integrations update the
    # `SelectedEsphomeVersionSensor` immediately instead of waiting on
    # the 30-s coordinator poll. Only fire on actual transitions.
    if previous != version:
        try:
            from event_bus import EVENT_TARGETS_CHANGED, broadcast  # noqa: PLC0415
            broadcast(EVENT_TARGETS_CHANGED)
        except Exception:
            logger.debug("event_bus broadcast failed", exc_info=True)


def get_esphome_version() -> str:
    """Return the active ESPHome version.

    Priority:
    1. Explicitly set version (via ``set_esphome_version`` or the UI).
    2. Installed ESPHome package — the venv's `esphome version` CLI
       output (SE.7) when the venv is ready, falling back to
       ``importlib.metadata`` for the bundled package (test / pre-SE.1).
    3. Fallback: ``"unknown"`` on any error, or ``"installing"`` during
       the first-boot install window before ``_esphome_ready`` fires.
    """
    if _selected_esphome_version:
        return _selected_esphome_version
    return _get_installed_esphome_version()


def _get_installed_esphome_version() -> str:
    """Return the installed ESPHome version, or a diagnostic sentinel.

    SE.7 — ordered lookup:
      1. If the venv has been activated (`_esphome_ready` fired), run
         `<venv>/bin/esphome version` once and cache the result.
      2. Otherwise fall back to `importlib.metadata.version("esphome")` —
         covers the test harness (bundled package on sys.path) and the
         pre-SE.1 transitional state where ESPHome is still baked into
         the server image.
      3. If the install is mid-flight (ready event clear, no metadata),
         return ``"installing"`` so the UI can surface a banner rather
         than crash.
      4. Fallback on exception: ``"unknown"``.
    """
    global _esphome_version_cache

    if _esphome_version_cache is not None:
        return _esphome_version_cache

    if _esphome_ready.is_set() and _server_esphome_bin:
        try:
            # ESPHome prints "Version: X.Y.Z" on stdout for this subcommand.
            # Short timeout; the venv binary is local so it's near-instant.
            result = subprocess.run(
                [_server_esphome_bin, "version"],
                capture_output=True, text=True, timeout=10, check=True,
            )
            for line in result.stdout.splitlines():
                stripped = line.strip()
                if stripped.lower().startswith("version:"):
                    _esphome_version_cache = stripped.split(":", 1)[1].strip()
                    return _esphome_version_cache
            # Older builds printed just the bare version on stdout.
            stripped = result.stdout.strip()
            if stripped:
                _esphome_version_cache = stripped.split()[-1]
                return _esphome_version_cache
        except Exception:
            logger.debug("venv esphome version lookup failed", exc_info=True)

    try:
        from importlib.metadata import version  # noqa: PLC0415
        return version("esphome")
    except Exception:
        logger.debug("Could not determine esphome version", exc_info=True)
        # If we know the install is mid-flight, surface that state so the
        # UI banner can render "Installing ESPHome…" rather than a blank.
        if not _esphome_ready.is_set() and not _esphome_install_failed:
            return "installing"
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
# Create / duplicate device helpers (CD.1 / CD.2)
#
# #43: ESPHome YAMLs use custom tags like ``!include``, ``!secret``, ``!extend``,
# ``!remove``, and ``!lambda`` that stdlib ``yaml.safe_load`` refuses to parse
# ("could not determine a constructor for the tag '!include'"). For duplicate
# we want a plain round-trip that preserves these tags, so we build a custom
# SafeLoader + SafeDumper pair that represents any ``!tag`` as a ``_Tagged``
# opaque wrapper and re-emits it on dump.
# ---------------------------------------------------------------------------


class _Tagged:
    """Opaque wrapper that preserves a YAML tag (e.g. ``!include``) on round-trip."""

    __slots__ = ("tag", "value")

    def __init__(self, tag: str, value: object) -> None:
        self.tag = tag
        self.value = value

    def __repr__(self) -> str:
        return f"_Tagged({self.tag!r}, {self.value!r})"


def _build_tag_preserving_yaml():
    """Return a (Loader, Dumper) pair that preserves arbitrary ``!tag`` markers.

    Lazy import + closure so we only pay the yaml import cost on create/dup.
    """
    import yaml  # noqa: PLC0415

    class _TagPreservingLoader(yaml.SafeLoader):
        pass

    class _TagPreservingDumper(yaml.SafeDumper):
        pass

    def _construct_tagged(loader, tag_suffix, node):
        tag = node.tag
        if isinstance(node, yaml.ScalarNode):
            return _Tagged(tag, loader.construct_scalar(node))
        if isinstance(node, yaml.SequenceNode):
            return _Tagged(tag, loader.construct_sequence(node, deep=True))
        return _Tagged(tag, loader.construct_mapping(node, deep=True))

    def _represent_tagged(dumper, data):
        if isinstance(data.value, list):
            return dumper.represent_sequence(data.tag, data.value)
        if isinstance(data.value, dict):
            return dumper.represent_mapping(data.tag, data.value)
        return dumper.represent_scalar(data.tag, str(data.value))

    # Multi-constructor with prefix "!" catches !include, !secret, !lambda, etc.
    _TagPreservingLoader.add_multi_constructor("!", _construct_tagged)
    _TagPreservingDumper.add_representer(_Tagged, _represent_tagged)

    return _TagPreservingLoader, _TagPreservingDumper


def create_stub_yaml(name: str) -> str:
    """Return a minimal ESPHome YAML stub with the given device name.

    The stub contains only the ``esphome.name`` field so the new device shows
    up in the Devices tab immediately. The user is expected to add board,
    platform, and components via the editor. Routed through ``yaml.safe_dump``
    per PY-1 — never hand-rolled string concatenation for YAML content.
    """
    import yaml  # noqa: PLC0415

    body = yaml.safe_dump({"esphome": {"name": name}}, sort_keys=False, default_flow_style=False)
    return body + "\n# Add board, platform, and components here.\n"


def duplicate_device(config_dir: str, source: str, new_name: str) -> str:
    """Read ``source`` YAML, rewrite ``esphome.name`` to ``new_name``, return YAML.

    NOTE: ``yaml.safe_dump`` drops comments. That's deliberate for duplicate
    — the user is starting from a template, not maintaining a shared file.
    If ``esphome.name`` is resolved via ``${substitutions.name}`` in the
    source, we rewrite the substitution instead so the indirection is
    preserved. Raises FileNotFoundError if the source doesn't exist or
    ValueError if the source is not a parseable YAML mapping.

    #43: custom ``!include``/``!secret``/... tags are preserved on
    round-trip via a tag-preserving Loader/Dumper pair.
    """
    import yaml  # noqa: PLC0415

    src_path = Path(config_dir) / source
    if not src_path.exists():
        raise FileNotFoundError(f"Source file not found: {source}")

    Loader, Dumper = _build_tag_preserving_yaml()

    content = src_path.read_text(encoding="utf-8")
    try:
        data = yaml.load(content, Loader=Loader)  # noqa: S506 — custom SafeLoader subclass
    except yaml.YAMLError as e:
        raise ValueError(f"Source YAML is not parseable: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Source YAML is not a mapping at the top level")

    # ESPHome convention: ``substitutions.name`` is almost always the device
    # name, used by included packages as ``${name}``. If it exists, rewrite
    # it — even if top-level ``esphome.name`` is a literal — so the rename
    # propagates into every include that uses ${name}.
    subs = data.get("substitutions")
    if isinstance(subs, dict) and "name" in subs:
        subs["name"] = new_name

    esphome_block = data.get("esphome")
    if isinstance(esphome_block, dict):
        existing_name = esphome_block.get("name")
        if isinstance(existing_name, str) and existing_name.startswith("${") and existing_name.endswith("}"):
            # Top-level esphome.name is a ``${substitutions.foo}`` reference.
            # If the reference target exists in substitutions, rewrite *that*
            # entry (preserving the indirection). Otherwise clobber
            # esphome.name directly so the file still names the device.
            sub_key = existing_name[2:-1]
            if isinstance(subs, dict) and sub_key in subs:
                subs[sub_key] = new_name
            else:
                esphome_block["name"] = new_name
        elif isinstance(existing_name, str):
            # Literal name at top level — rewrite it.
            esphome_block["name"] = new_name
        # If esphome.name is absent we leave the top-level block alone: the
        # real name probably lives in an included package under ${name},
        # which we've already rewritten via substitutions.name above. Only
        # inject a literal esphome.name when there's also no substitutions
        # fallback to carry the rename.
        elif not (isinstance(subs, dict) and "name" in subs):
            esphome_block["name"] = new_name
    elif isinstance(subs, dict) and "name" in subs:
        # No esphome block at all but we did rewrite substitutions.name — the
        # include pipeline will fill esphome.name from ${name}, so don't add
        # a redundant top-level block.
        pass
    else:
        data["esphome"] = {"name": new_name}

    # #54: strip network-address pins inherited from the source so the
    # duplicate doesn't get reported "online" just because its YAML
    # points at the source's IP. The device poller would happily connect
    # to the source's address, receive a successful response (from the
    # OLD device still sitting at that IP), and mark the duplicate
    # online even though nothing at the new identity actually responds.
    # The user is expected to re-provision WiFi creds / IP for the new
    # device — leaving these fields off the YAML is the natural default.
    for block_name in ("wifi", "ethernet", "openthread"):
        block = data.get(block_name)
        if isinstance(block, dict):
            block.pop("use_address", None)
            manual_ip = block.get("manual_ip")
            if isinstance(manual_ip, dict):
                manual_ip.pop("static_ip", None)
                # Drop the empty container so we don't litter the YAML.
                if not manual_ip:
                    block.pop("manual_ip", None)

    return yaml.dump(data, Dumper=Dumper, sort_keys=False, default_flow_style=False)


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

    # #41: broadcast so HA integrations refresh immediately instead of
    # waiting on the 30 s coordinator poll. Cheap no-op when nothing is
    # subscribed.
    try:
        from event_bus import EVENT_TARGETS_CHANGED, broadcast  # noqa: PLC0415
        broadcast(EVENT_TARGETS_CHANGED)
    except Exception:
        logger.debug("event_bus broadcast failed", exc_info=True)


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

        # SE.4: early-return during the first-boot install window so the
        # scanner degrades gracefully instead of raising ImportError.
        # Callers (device_poller, /ui/api/targets) already tolerate a
        # None return — they fall back to `yaml.safe_load` for metadata
        # (friendly_name etc. stays raw ${...} until ESPHome is ready).
        # The import-guard below is belt-and-suspenders for the pre-SE.1
        # world where the bundled package is still on sys.path.
        if not _esphome_ready.is_set() and _server_esphome_venv is None:
            try:
                import esphome  # noqa: PLC0415, F401
            except ImportError:
                logger.info(
                    "ESPHome still installing — skipping config resolution for %s "
                    "(UI will use raw YAML metadata until the venv is ready)",
                    target,
                )
                return None

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

        # Resolve ${substitutions}. ESPHome 2026.4.0 reshaped the API
        # in two ways we have to accommodate:
        #   1. dropped the `ignore_missing` kwarg
        #   2. changed do_substitution_pass from in-place mutation to
        #      returning a new config (previously discarded its return
        #      value)
        # We must pass `ignore_missing=True` when it's accepted — without
        # it, any unresolved substitution raises `cv.Invalid` which the
        # outer `except Exception` swallows and the whole resolve returns
        # None (bug #22: friendly_name missing for devices whose YAML uses
        # ${device_name} in the name field). Try the legacy signature
        # first; the TypeError on new ESPHome drops us into the new form,
        # which always tolerates missing subs via the warn-only path.
        try:
            do_substitution_pass(config, None, ignore_missing=True)  # type: ignore[call-arg]
        except TypeError:
            # esphome>=2026.4.0 dropped ignore_missing and returns a new
            # config instead of mutating in place.
            result = do_substitution_pass(config, None)
            if result is not None:
                config = result

        _config_cache[target] = (mtime, config)
        return config
    except Exception as exc:
        # DL.1: promote to WARNING so operators can see which target fails
        # to resolve (previously only visible at DEBUG; issue #60). Keep the
        # full traceback at DEBUG so we don't spam the log with stack dumps.
        logger.warning(
            "Could not resolve config for %s: %s (%s) — stack trace at DEBUG",
            target, type(exc).__name__, exc,
        )
        logger.debug("Full traceback for %s resolve failure:", target, exc_info=True)
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
        "schedule_once": None,       # ISO datetime for one-time schedule
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
        result["schedule_once"] = device_meta.get("schedule_once")
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

    # #74: detect presence of the web_server component. ESPHome allows
    # `web_server:` with no value (enables with defaults), which YAML
    # parses as {"web_server": None}. Check key PRESENCE, not value.
    if "web_server" in config:
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

    # #74: detect web_server in raw config too (fallback when full resolution
    # failed but top-level YAML has web_server:)
    if not result["has_web_server"] and "web_server" in raw_config:
        result["has_web_server"] = True


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
        # DL.2: log the resolved address waterfall so operators can see
        # at a glance which field the scanner used — narrows down
        # live-logs "Device not found" reports (issue #60) to one of
        # three buckets: name normalization, address resolution, or
        # actual missing device. Fires once per target per scan.
        logger.info(
            "Target %s → device %r at %s (source=%s)",
            target, key_name, addr, src,
        )
    return name_map, encryption_keys, address_overrides, address_sources


