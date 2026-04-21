"""Tests for the MAC→IP fallback reader (Bug #7)."""

from __future__ import annotations

from pathlib import Path

import arp


_SAMPLE_ARP = (
    "IP address       HW type     Flags       HW address            Mask     Device\n"
    "192.168.1.10     0x1         0x2         aa:bb:cc:dd:ee:01     *        eth0\n"
    "192.168.1.11     0x1         0x2         aa:bb:cc:dd:ee:02     *        eth0\n"
    # Incomplete row — kernel never resolved this neighbour. Must be skipped.
    "192.168.1.99     0x1         0x0         00:00:00:00:00:00     *        eth0\n"
    # Malformed row — should be silently dropped without crashing.
    "broken row\n"
)


def _write_arp(monkeypatch, tmp_path: Path, content: str) -> None:
    path = tmp_path / "arp"
    path.write_text(content)
    monkeypatch.setattr(arp, "_ARP_PATH", path)
    arp.invalidate_cache()


def test_lookup_returns_ip_for_known_mac(monkeypatch, tmp_path: Path) -> None:
    _write_arp(monkeypatch, tmp_path, _SAMPLE_ARP)
    assert arp.lookup("AA:BB:CC:DD:EE:01") == "192.168.1.10"
    # Case-insensitive — aioesphomeapi returns upper-case.
    assert arp.lookup("aa:bb:cc:dd:ee:02") == "192.168.1.11"


def test_lookup_skips_incomplete_entries(monkeypatch, tmp_path: Path) -> None:
    _write_arp(monkeypatch, tmp_path, _SAMPLE_ARP)
    # The 00:00:00:00:00:00 row must not surface as a stale IP.
    assert arp.lookup("00:00:00:00:00:00") is None


def test_lookup_returns_none_for_unknown_mac(monkeypatch, tmp_path: Path) -> None:
    _write_arp(monkeypatch, tmp_path, _SAMPLE_ARP)
    assert arp.lookup("ff:ff:ff:ff:ff:ff") is None


def test_lookup_handles_missing_file(monkeypatch, tmp_path: Path) -> None:
    """Dev hosts don't have /proc/net/arp — lookup must not raise."""
    ghost = tmp_path / "does-not-exist"
    monkeypatch.setattr(arp, "_ARP_PATH", ghost)
    arp.invalidate_cache()
    assert arp.lookup("aa:bb:cc:dd:ee:01") is None


def test_lookup_empty_mac(monkeypatch, tmp_path: Path) -> None:
    _write_arp(monkeypatch, tmp_path, _SAMPLE_ARP)
    assert arp.lookup("") is None
