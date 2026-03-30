"""Centralised application configuration.

Loads values from ``/data/options.json`` (HA add-on) with environment-variable
overrides and sensible defaults.  All other modules should import the singleton
``config`` instance rather than reading env vars or ``request.app["config"]``
directly.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

OPTIONS_FILE = Path("/data/options.json")
TOKEN_FILE = Path("/data/auth_token")


def _get_or_create_token(explicit: str) -> str:
    """Return *explicit* if non-empty, otherwise load/generate a persisted token."""
    if explicit:
        return explicit
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
        if token:
            return token
    token = secrets.token_hex(16)
    try:
        TOKEN_FILE.write_text(token)
        logger.info("Generated new auth token and saved to %s", TOKEN_FILE)
    except Exception:
        logger.exception("Failed to save generated token to %s", TOKEN_FILE)
    return token


@dataclass
class AppConfig:
    """Immutable-ish application configuration — created once at startup."""

    token: str = ""
    job_timeout: int = 600
    ota_timeout: int = 120
    client_offline_threshold: int = 30
    device_poll_interval: int = 60
    config_dir: str = "/config/esphome"
    port: int = 8765

    @classmethod
    def load(cls) -> "AppConfig":
        """Build config from options file → env vars → defaults (in that order)."""
        file_opts: dict = {}
        if OPTIONS_FILE.exists():
            try:
                file_opts = json.loads(OPTIONS_FILE.read_text())
            except Exception:
                logger.exception("Failed to read %s; using defaults", OPTIONS_FILE)

        def _val(key: str, env_key: str, default, typ=int):
            # options.json wins, then env var, then dataclass default
            if key in file_opts:
                return typ(file_opts[key])
            env = os.environ.get(env_key)
            if env is not None:
                return typ(env)
            return default

        raw_token = file_opts.get("token", "") or os.environ.get("SERVER_TOKEN", "")
        token = _get_or_create_token(raw_token)

        return cls(
            token=token,
            job_timeout=_val("job_timeout", "JOB_TIMEOUT", cls.job_timeout),
            ota_timeout=_val("ota_timeout", "OTA_TIMEOUT", cls.ota_timeout),
            client_offline_threshold=_val("client_offline_threshold", "CLIENT_OFFLINE_THRESHOLD", cls.client_offline_threshold),
            device_poll_interval=_val("device_poll_interval", "DEVICE_POLL_INTERVAL", cls.device_poll_interval),
            config_dir=os.environ.get("ESPHOME_CONFIG_DIR", cls.config_dir),
            port=int(os.environ.get("PORT", str(cls.port))),
        )
