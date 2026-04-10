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
from dataclasses import dataclass
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
    worker_offline_threshold: int = 30
    device_poll_interval: int = 60
    config_dir: str = "/config/esphome"
    port: int = 8765

    # Set of keys we recognise from options.json. Anything else gets logged
    # at WARNING on startup so a typo (``worker_ofline_threshold``) is
    # immediately visible instead of being silently ignored. C.4.
    _KNOWN_OPTION_KEYS: frozenset = frozenset({
        "token",
        "job_timeout",
        "ota_timeout",
        "worker_offline_threshold",
        "client_offline_threshold",  # legacy alias
        "device_poll_interval",
    })

    @classmethod
    def load(cls) -> "AppConfig":
        """Build config from options file → env vars → defaults (in that order).

        C.4: every fallback path and every malformed/unknown options.json key
        is logged at startup. Silent fallback was hiding misconfigurations
        (typo'd keys, malformed JSON falling through to all defaults) until
        a user noticed something behaved unexpectedly hours later.
        """
        file_opts: dict = {}
        if OPTIONS_FILE.exists():
            try:
                raw = OPTIONS_FILE.read_text()
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    logger.error(
                        "%s is not a JSON object (got %s); ignoring and using defaults",
                        OPTIONS_FILE, type(parsed).__name__,
                    )
                else:
                    file_opts = parsed
            except Exception:
                logger.exception(
                    "Failed to parse %s; ALL options will fall back to env vars + defaults",
                    OPTIONS_FILE,
                )
        else:
            logger.info(
                "%s not present; using env vars + defaults (this is normal outside HA add-on context)",
                OPTIONS_FILE,
            )

        # Surface unknown keys loud and early so typos are immediately visible.
        unknown_keys = set(file_opts) - cls._KNOWN_OPTION_KEYS
        for key in sorted(unknown_keys):
            logger.warning(
                "Unknown key in %s: %r — typo or stale option? Will be ignored.",
                OPTIONS_FILE, key,
            )

        def _val(key: str, env_key: str, default, typ=int):
            # options.json wins, then env var, then dataclass default
            if key in file_opts:
                try:
                    return typ(file_opts[key])
                except (ValueError, TypeError):
                    logger.error(
                        "options.json[%r] = %r is not a valid %s; using env/default",
                        key, file_opts[key], typ.__name__,
                    )
            env = os.environ.get(env_key)
            if env is not None:
                try:
                    return typ(env)
                except (ValueError, TypeError):
                    logger.error(
                        "Env var %s=%r is not a valid %s; using default %r",
                        env_key, env, typ.__name__, default,
                    )
                    return default
            logger.debug("Config %s: using default %r (no options.json or env override)", key, default)
            return default

        raw_token = file_opts.get("token", "") or os.environ.get("SERVER_TOKEN", "")
        if not raw_token:
            logger.warning(
                "No token configured in options.json or SERVER_TOKEN env var — "
                "will generate a random one and persist it to %s", TOKEN_FILE,
            )
        token = _get_or_create_token(raw_token)

        # Support both old key (client_offline_threshold) and new key (worker_offline_threshold)
        # in options.json for backwards compatibility during upgrades.
        threshold_default = cls.worker_offline_threshold
        if "worker_offline_threshold" in file_opts:
            threshold = int(file_opts["worker_offline_threshold"])
        elif "client_offline_threshold" in file_opts:
            logger.warning(
                "options.json uses legacy key 'client_offline_threshold'; "
                "rename to 'worker_offline_threshold' before the legacy alias is removed."
            )
            threshold = int(file_opts["client_offline_threshold"])
        else:
            env = os.environ.get("WORKER_OFFLINE_THRESHOLD") or os.environ.get("CLIENT_OFFLINE_THRESHOLD")
            threshold = int(env) if env is not None else threshold_default

        return cls(
            token=token,
            job_timeout=_val("job_timeout", "JOB_TIMEOUT", cls.job_timeout),
            ota_timeout=_val("ota_timeout", "OTA_TIMEOUT", cls.ota_timeout),
            worker_offline_threshold=threshold,
            device_poll_interval=_val("device_poll_interval", "DEVICE_POLL_INTERVAL", cls.device_poll_interval),
            config_dir=os.environ.get("ESPHOME_CONFIG_DIR", cls.config_dir),
            port=int(os.environ.get("PORT", str(cls.port))),
        )
