"""Centralised application configuration.

All other modules should read the singleton ``config`` instance rather
than reaching for env vars or ``request.app["config"]`` directly.

## Precedence (CR.21)

Per-field precedence, highest wins:

  1. **Environment variable** — `SERVER_TOKEN`, `SERVER_PORT`, etc. Wins
     over everything else. Used for local development (non-Supervisor
     runs) and for overriding a value on a per-container basis.
  2. **``/data/options.json``** — the HA add-on's user-configurable
     options persisted by Supervisor across restarts / upgrades. This
     is the normal path for HA deployments.
  3. **Built-in defaults** — the fallback hard-coded in this module
     (token auto-generated and persisted to ``/data/auth_token`` if
     nothing else supplies it; port defaults to 8765; etc.).

The single legacy alias (`client_offline_threshold` → renamed to
`worker_offline_threshold` as part of the Client→Worker terminology
rewrite) is mapped on read with a one-time WARNING asking the user to
rename the key. New aliases should not be added without a deprecation
plan and a removal-version target.

There is **no third config source** and no YAML/TOML config file — the
server is meant to be configured entirely through Supervisor's options
UI (or env vars in non-Supervisor deployments). If a new config field
isn't going through this module, it's a bug.
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
        # SA.2 / F-14: lock down file mode immediately after write so
        # the token doesn't inherit the container umask. Least-privilege
        # for secret material — owner-read-write only.
        try:
            TOKEN_FILE.chmod(0o600)
        except OSError:
            logger.debug("chmod 0o600 on %s failed; continuing", TOKEN_FILE, exc_info=True)
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
    # AU.3/AU.7: when true, direct-port /ui/api/* calls must carry a
    # valid HA Bearer token. Ingress-tunneled access is unaffected.
    # Default flipped to `true` in 1.5.0 (AU.7) — the add-on's own
    # shared token now works as a system Bearer (ha_auth.py Path 2),
    # so the native HA integration's coordinator authenticates
    # transparently. Left as a config option for test harnesses and
    # for deliberate pre-1.4.1 opt-out.
    require_ha_auth: bool = True

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
        "require_ha_auth",
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

        # AU.3: require_ha_auth — bool, defaults to False. options.json
        # may send either a bool or a string like "true"/"false".
        raw_require_ha_auth = file_opts.get(
            "require_ha_auth",
            os.environ.get("REQUIRE_HA_AUTH", ""),
        )
        if isinstance(raw_require_ha_auth, bool):
            require_ha_auth = raw_require_ha_auth
        else:
            require_ha_auth = str(raw_require_ha_auth).strip().lower() in ("1", "true", "yes", "on")

        return cls(
            token=token,
            job_timeout=_val("job_timeout", "JOB_TIMEOUT", cls.job_timeout),
            ota_timeout=_val("ota_timeout", "OTA_TIMEOUT", cls.ota_timeout),
            worker_offline_threshold=threshold,
            device_poll_interval=_val("device_poll_interval", "DEVICE_POLL_INTERVAL", cls.device_poll_interval),
            config_dir=os.environ.get("ESPHOME_CONFIG_DIR", cls.config_dir),
            port=int(os.environ.get("PORT", str(cls.port))),
            require_ha_auth=require_ha_auth,
        )
