"""FD.5/FD.6/FD.7 + #69 unit tests — firmware storage lifecycle."""

from __future__ import annotations

from pathlib import Path

from firmware_storage import (
    delete_firmware,
    firmware_path,
    list_variants,
    read_firmware,
    reconcile_orphans,
    save_firmware,
)


def test_save_creates_directory_and_writes_file(tmp_path: Path) -> None:
    dest = tmp_path / "firmware"
    assert not dest.exists()
    # Default variant is "factory" post-#69 — on ESP32 this is the
    # full flash image written at `{job_id}.factory.bin`.
    path = save_firmware("job-1", b"hello", root=dest)
    assert path.read_bytes() == b"hello"
    assert path == dest / "job-1.factory.bin"


def test_save_overwrites_existing(tmp_path: Path) -> None:
    dest = tmp_path / "firmware"
    save_firmware("job-1", b"first", root=dest)
    save_firmware("job-1", b"second", root=dest)
    assert (dest / "job-1.factory.bin").read_bytes() == b"second"


def test_save_writes_each_variant_independently(tmp_path: Path) -> None:
    """#69 — factory + ota live side by side under the same job id."""
    save_firmware("job-1", b"factory-blob", variant="factory", root=tmp_path)
    save_firmware("job-1", b"ota-blob", variant="ota", root=tmp_path)
    assert (tmp_path / "job-1.factory.bin").read_bytes() == b"factory-blob"
    assert (tmp_path / "job-1.ota.bin").read_bytes() == b"ota-blob"


def test_delete_removes_all_variants(tmp_path: Path) -> None:
    """#69 — user Clear must wipe every variant, not just one."""
    save_firmware("job-1", b"a", variant="factory", root=tmp_path)
    save_firmware("job-1", b"b", variant="ota", root=tmp_path)
    assert delete_firmware("job-1", root=tmp_path) is True
    assert not (tmp_path / "job-1.factory.bin").exists()
    assert not (tmp_path / "job-1.ota.bin").exists()


def test_delete_returns_false_when_missing(tmp_path: Path) -> None:
    assert delete_firmware("never-existed", root=tmp_path) is False


def test_delete_cleans_up_legacy_pre_69_blob(tmp_path: Path) -> None:
    """Pre-#69 installs have ``{job_id}.bin`` on disk; upgrade Clear
    must still remove those rather than stranding bytes forever."""
    legacy = tmp_path / "legacy-job.bin"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"old")
    assert delete_firmware("legacy-job", root=tmp_path) is True
    assert not legacy.exists()


def test_read_returns_none_when_missing(tmp_path: Path) -> None:
    assert read_firmware("missing", root=tmp_path) is None


def test_read_returns_bytes_when_present(tmp_path: Path) -> None:
    save_firmware("job-1", b"bytes", variant="ota", root=tmp_path)
    assert read_firmware("job-1", variant="ota", root=tmp_path) == b"bytes"
    # Unmatched variant returns None — callers should 404, not silently
    # swap in another variant.
    assert read_firmware("job-1", variant="factory", root=tmp_path) is None


def test_firmware_path_uses_variant_suffix(tmp_path: Path) -> None:
    # Default (factory) — post-#69 shape.
    assert firmware_path("abc-123", root=tmp_path) == tmp_path / "abc-123.factory.bin"
    assert (
        firmware_path("abc-123", variant="ota", root=tmp_path)
        == tmp_path / "abc-123.ota.bin"
    )
    # Synthetic "firmware" variant resolves back to the pre-#69 layout
    # so upgraded installs keep reading old blobs.
    assert (
        firmware_path("abc-123", variant="firmware", root=tmp_path)
        == tmp_path / "abc-123.bin"
    )


def test_list_variants_orders_factory_before_ota(tmp_path: Path) -> None:
    save_firmware("job-1", b"o", variant="ota", root=tmp_path)
    save_firmware("job-1", b"f", variant="factory", root=tmp_path)
    assert list_variants("job-1", root=tmp_path) == ["factory", "ota"]


def test_list_variants_empty_when_none_stored(tmp_path: Path) -> None:
    assert list_variants("nobody-home", root=tmp_path) == []


def test_list_variants_exposes_legacy_blob_as_firmware(tmp_path: Path) -> None:
    """Pre-#69 on-disk `{job_id}.bin` surfaces as variant "firmware"
    so the UI's Download dropdown still offers it after an upgrade."""
    (tmp_path / "legacy-job.bin").write_bytes(b"old")
    assert list_variants("legacy-job", root=tmp_path) == ["firmware"]


def test_reconcile_removes_orphans_keeps_active(tmp_path: Path) -> None:
    save_firmware("keep", b"a", variant="factory", root=tmp_path)
    save_firmware("keep", b"b", variant="ota", root=tmp_path)
    save_firmware("drop1", b"c", variant="factory", root=tmp_path)
    save_firmware("drop2", b"d", variant="ota", root=tmp_path)
    removed = reconcile_orphans(["keep"], root=tmp_path)
    assert removed == 2  # drop1.factory.bin, drop2.ota.bin
    assert (tmp_path / "keep.factory.bin").exists()
    assert (tmp_path / "keep.ota.bin").exists()
    assert not (tmp_path / "drop1.factory.bin").exists()
    assert not (tmp_path / "drop2.ota.bin").exists()


def test_reconcile_sweeps_pre_69_legacy_layout(tmp_path: Path) -> None:
    """Pre-#69 `{job_id}.bin` files are still swept by reconcile_orphans."""
    (tmp_path / "keep.bin").write_bytes(b"keep-me")
    (tmp_path / "drop.bin").write_bytes(b"drop-me")
    removed = reconcile_orphans(["keep"], root=tmp_path)
    assert removed == 1
    assert (tmp_path / "keep.bin").exists()
    assert not (tmp_path / "drop.bin").exists()


def test_reconcile_no_op_when_directory_missing(tmp_path: Path) -> None:
    assert reconcile_orphans(["x"], root=tmp_path / "nope") == 0


def test_reconcile_ignores_non_bin_files(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    save_firmware("keep", b"a", variant="factory", root=tmp_path)
    (tmp_path / "readme.txt").write_text("don't delete me")
    removed = reconcile_orphans(["keep"], root=tmp_path)
    assert removed == 0
    assert (tmp_path / "readme.txt").exists()
