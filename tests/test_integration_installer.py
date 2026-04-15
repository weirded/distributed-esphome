"""Unit tests for the HA custom-integration auto-installer (HI.8)."""

from __future__ import annotations

import json
from pathlib import Path

from integration_installer import install_integration


def _write_manifest(directory: Path, version: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(
        json.dumps({"domain": "esphome_fleet", "name": "ESPHome Fleet", "version": version})
    )
    (directory / "__init__.py").write_text("# stub\n")


def test_skips_when_source_missing(tmp_path: Path) -> None:
    dest = tmp_path / "config" / "custom_components" / "esphome_fleet"
    result = install_integration(
        source_dir=tmp_path / "does_not_exist",
        destination_dir=dest,
    )
    assert result == "skipped_no_source"
    assert not dest.exists()


def test_fresh_install_copies_all_files(tmp_path: Path) -> None:
    src = tmp_path / "src" / "esphome_fleet"
    _write_manifest(src, "0.1.0")
    (src / "sensor.py").write_text("# stub sensor\n")

    dest = tmp_path / "config" / "custom_components" / "esphome_fleet"
    result = install_integration(source_dir=src, destination_dir=dest)

    assert result == "installed"
    assert (dest / "manifest.json").exists()
    assert (dest / "__init__.py").exists()
    assert (dest / "sensor.py").exists()
    assert json.loads((dest / "manifest.json").read_text())["version"] == "0.1.0"


def test_unchanged_when_versions_match(tmp_path: Path) -> None:
    src = tmp_path / "src" / "esphome_fleet"
    _write_manifest(src, "0.2.0")
    dest = tmp_path / "config" / "custom_components" / "esphome_fleet"
    _write_manifest(dest, "0.2.0")
    # Mark the destination so we can detect a rewrite.
    (dest / "marker.txt").write_text("preserved")

    result = install_integration(source_dir=src, destination_dir=dest)
    assert result == "unchanged"
    # Marker file not wiped → destination wasn't touched.
    assert (dest / "marker.txt").read_text() == "preserved"


def test_update_replaces_old_version(tmp_path: Path) -> None:
    src = tmp_path / "src" / "esphome_fleet"
    _write_manifest(src, "0.3.0")
    (src / "new_file.py").write_text("# added in 0.3.0\n")

    dest = tmp_path / "config" / "custom_components" / "esphome_fleet"
    _write_manifest(dest, "0.2.0")
    (dest / "marker.txt").write_text("should-be-gone")

    result = install_integration(source_dir=src, destination_dir=dest)
    assert result == "updated"
    assert json.loads((dest / "manifest.json").read_text())["version"] == "0.3.0"
    assert (dest / "new_file.py").exists()
    # Old files cleared in the replacement.
    assert not (dest / "marker.txt").exists()


def test_failed_when_source_manifest_unparseable(tmp_path: Path) -> None:
    src = tmp_path / "src" / "esphome_fleet"
    src.mkdir(parents=True)
    (src / "manifest.json").write_text("not valid json {{{")

    dest = tmp_path / "config" / "custom_components" / "esphome_fleet"
    result = install_integration(source_dir=src, destination_dir=dest)
    assert result == "failed"
    assert not dest.exists()
