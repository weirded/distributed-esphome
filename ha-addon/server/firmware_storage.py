"""Per-queue-item firmware storage (FD.5/FD.6/FD.7, extended in #69).

Binaries produced by download-only (or side-stored from OTA) jobs land at
``/data/firmware/{job_id}.{variant}.bin``. Each job may carry multiple
variants — on ESP32 a compile produces both ``firmware.factory.bin``
(the full flash image, stored as variant ``factory``) and
``firmware.bin`` (OTA-safe / legacy upload shape, stored as variant
``ota``). ESP8266 only produces the latter.

Lifecycle is coupled to the queue entry: when a job is removed from the
queue (user Clear, bulk clear, per-target coalescing cleanup, startup
orphan sweep), every variant binary for that job id is deleted. No
time-based cleanup — consistent with bug #18's "users clear explicitly"
stance.

Legacy path ``/data/firmware/{job_id}.bin`` (no variant segment) from
pre-#69 builds is kept **read-only**: ``list_variants`` reports it as
``variant="firmware"`` so the UI's Download dropdown still offers the
old binary for in-flight pre-rename jobs. New writes always go through
the ``{variant}`` path.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


# Default storage root — `/data/` is persisted by HA across add-on
# updates/restarts/rebuilds. Override via the argument to each helper
# so tests can use tmp_path.
DEFAULT_FIRMWARE_DIR = Path("/data/firmware")


# Variant name → human-readable label. Authoritative ordering used by
# the UI's dropdown so "factory" (first-flash image) appears before
# "ota" (update-only image) when both are available.
VARIANT_ORDER = ("factory", "ota")

# Legacy synthetic variant name surfaced for pre-#69 on-disk blobs.
LEGACY_VARIANT = "firmware"


def _resolve_root(root: Optional[Path]) -> Path:
    """Resolve the storage root, honoring a runtime override of
    ``DEFAULT_FIRMWARE_DIR`` via monkeypatch (used by pytest).

    Reading the module attribute at call time (instead of binding the
    default at function-definition time) lets tests flip the root
    without touching each helper signature.
    """
    import firmware_storage as _fs  # noqa: PLC0415 — self-import is deliberate
    return root if root is not None else _fs.DEFAULT_FIRMWARE_DIR


def firmware_path(job_id: str, variant: str = "factory", root: Optional[Path] = None) -> Path:
    """Return the canonical `.bin` path for *job_id*/*variant* under *root*.

    ``variant == "firmware"`` resolves to the pre-#69 legacy shape
    (no variant segment) so reads from upgraded installs keep working.
    """
    r = _resolve_root(root)
    if variant == LEGACY_VARIANT:
        return r / f"{job_id}.bin"
    return r / f"{job_id}.{variant}.bin"


def save_firmware(
    job_id: str,
    data: bytes,
    variant: str = "factory",
    root: Optional[Path] = None,
) -> Path:
    """Persist *data* as the binary for *job_id*/*variant*. Returns the written path.

    Overwrites in place — retry of the same job re-uploads atop the
    previous binary (acceptable; the server's ``has_firmware`` flag is
    already True and the variant list just gets re-sorted to stable order).
    """
    r = _resolve_root(root)
    r.mkdir(parents=True, exist_ok=True)
    path = firmware_path(job_id, variant, r)
    path.write_bytes(data)
    logger.info(
        "Stored firmware for job %s (variant=%s) at %s (%d bytes)",
        job_id, variant, path, len(data),
    )
    return path


def list_variants(job_id: str, root: Optional[Path] = None) -> list[str]:
    """Return the variant names currently stored for *job_id*.

    Variants are ordered by ``VARIANT_ORDER`` first (factory before ota)
    with any unrecognized names appended lexicographically. Pre-#69
    legacy blobs (``{job_id}.bin``) surface as ``"firmware"`` so the UI
    still offers them for download after an add-on upgrade.
    """
    r = _resolve_root(root)
    try:
        if not r.is_dir():
            return []
    except Exception:
        return []
    found: set[str] = set()
    legacy = r / f"{job_id}.bin"
    if legacy.is_file():
        found.add(LEGACY_VARIANT)
    for entry in r.iterdir():
        if not entry.is_file() or not entry.name.startswith(f"{job_id}."):
            continue
        # Expect "{job_id}.{variant}.bin"; skip legacy (handled above) + unrelated.
        stem = entry.name[len(job_id) + 1:]  # strip "{job_id}."
        if not stem.endswith(".bin"):
            continue
        variant = stem[:-len(".bin")]
        if not variant or variant == LEGACY_VARIANT:
            continue
        found.add(variant)
    # Stable, UI-friendly order.
    ordered: list[str] = [v for v in VARIANT_ORDER if v in found]
    ordered.extend(sorted(v for v in found if v not in VARIANT_ORDER))
    return ordered


def delete_firmware(job_id: str, root: Optional[Path] = None) -> bool:
    """Remove **every** stored variant for *job_id*. Returns True if any
    file was deleted.
    """
    r = _resolve_root(root)
    any_deleted = False
    # Legacy + modern variants — walk the full set so we don't leave
    # orphaned bytes behind after a user Clear.
    for variant in (*list_variants(job_id, r), LEGACY_VARIANT):
        path = firmware_path(job_id, variant, r)
        try:
            path.unlink()
            logger.info(
                "Deleted firmware for job %s (variant=%s, %s)",
                job_id, variant, path,
            )
            any_deleted = True
        except FileNotFoundError:
            continue
        except Exception:
            logger.exception(
                "Failed to delete firmware for job %s (variant=%s) at %s",
                job_id, variant, path,
            )
    return any_deleted


def read_firmware(
    job_id: str,
    variant: str = "factory",
    root: Optional[Path] = None,
) -> Optional[bytes]:
    """Return the stored binary for *job_id*/*variant*, or None if missing.

    When the requested variant is absent, callers get ``None`` — they
    should surface 404 rather than silently substituting another variant.
    """
    path = firmware_path(job_id, variant, _resolve_root(root))
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def reconcile_orphans(active_job_ids: Iterable[str], root: Optional[Path] = None) -> int:
    """Delete any `.bin` in *root* whose job is no longer active.

    Called once at server startup: the queue file is the source of
    truth for what's alive, so anything on disk not in that set is
    stale (e.g. add-on was killed mid-cleanup on a previous run).
    Returns the number of files removed. Covers both the pre-#69
    ``{job_id}.bin`` layout and the ``{job_id}.{variant}.bin`` layout.
    """
    r = _resolve_root(root)
    try:
        if not r.is_dir():
            return 0
    except Exception:
        return 0
    active = set(active_job_ids)
    removed = 0
    for entry in r.iterdir():
        if not entry.is_file() or entry.suffix != ".bin":
            continue
        # Strip ".bin" then peel off any trailing ".{variant}" segment
        # to recover the job id. Works for both new (foo.factory.bin →
        # "foo") and legacy (foo.bin → "foo") layouts.
        base = entry.name[:-len(".bin")]
        job_id = base.split(".", 1)[0]
        if job_id in active:
            continue
        try:
            entry.unlink()
            removed += 1
        except Exception:
            logger.debug("Couldn't remove orphan firmware %s", entry, exc_info=True)
    if removed:
        logger.info("Reconciled %d orphan firmware file(s) in %s", removed, r)
    return removed
