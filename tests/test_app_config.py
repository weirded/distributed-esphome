"""Tests for AppConfig.load() env-var parsing.

Focused on PR #64 review's defensive-parsing note: a bad ``PORT`` value
must log + fall back to the default, not crash the add-on at startup.
"""

from __future__ import annotations

import logging

import pytest

from app_config import AppConfig


def test_port_default_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORT", raising=False)
    cfg = AppConfig.load()
    assert cfg.port == 8765


def test_port_parsed_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "9000")
    cfg = AppConfig.load()
    assert cfg.port == 9000


def test_port_empty_string_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Partial env interpolation can yield an empty string — don't crash."""
    monkeypatch.setenv("PORT", "")
    cfg = AppConfig.load()
    assert cfg.port == 8765


def test_port_non_numeric_falls_back_with_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """PR #64 review: bad ``PORT`` used to raise ValueError and take the
    add-on down at startup. Now logs a WARNING + falls back."""
    monkeypatch.setenv("PORT", "80a")
    with caplog.at_level(logging.WARNING, logger="app_config"):
        cfg = AppConfig.load()
    assert cfg.port == 8765
    # One WARNING mentioning the offending value.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected a WARNING for non-numeric PORT"
    assert "80a" in warnings[0].getMessage()


def test_config_dir_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ESPHOME_CONFIG_DIR", "/tmp/esphome-test")
    cfg = AppConfig.load()
    assert cfg.config_dir == "/tmp/esphome-test"


def test_config_dir_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ESPHOME_CONFIG_DIR", raising=False)
    cfg = AppConfig.load()
    assert cfg.config_dir == "/config/esphome"
