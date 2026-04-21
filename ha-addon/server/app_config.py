"""Deployment-level application configuration.

Post-SP.8 (1.6), this module only holds the fields that genuinely must
come from the environment at startup time:

- ``config_dir`` — where ESPHome YAML configs live (env-driven; used by
  scanner, git_versioning, every path-resolving API handler).
- ``port`` — the HTTP listen port (env-driven).

Everything else — ``server_token``, ``job_timeout``, ``ota_timeout``,
``worker_offline_threshold``, ``device_poll_interval``, ``require_ha_auth``
— now lives in the Settings store (``settings.py``, persisted to
``/data/settings.json``) and is edited via the in-app Settings drawer
with live-effect. See ``dev-plans/WORKITEMS-1.6.md`` §Settings.

The ``options.json`` file is still read once at first boot as the
one-shot import source for the migrated fields (handled by
``settings.init_settings``); after that it's effectively unused.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AppConfig:
    """Deployment-level config, frozen at startup.

    Product settings (timeouts, thresholds, tokens, auth flags) moved
    to the Settings store in 1.6 (SP.8). This type only holds the
    env-driven fields that the runtime needs before Settings are
    loaded, or that Settings shouldn't be expected to reconfigure
    (changing `config_dir` or `port` requires a full restart anyway).
    """

    config_dir: str = "/config/esphome"
    port: int = 8765

    @classmethod
    def load(cls) -> "AppConfig":
        """Build config from env vars, falling back to the dataclass defaults.

        PR #64 review: ``int(os.environ.get("PORT", ...))`` used to run
        unguarded, which raised ``ValueError`` (and took the add-on
        down at startup) when ``PORT`` was set but not numeric —
        "80a", empty string from a partial interpolation, etc. Now
        logs a WARNING and falls back to the dataclass default so a
        typo in the env doesn't block boot. ``ESPHOME_CONFIG_DIR``
        is a string so it needs no parsing.
        """
        port_raw = os.environ.get("PORT")
        if port_raw is None or port_raw == "":
            port = cls.port
        else:
            try:
                port = int(port_raw)
            except ValueError:
                logger.warning(
                    "PORT env var %r is not an integer; falling back to default %d",
                    port_raw, cls.port,
                )
                port = cls.port
        return cls(
            config_dir=os.environ.get("ESPHOME_CONFIG_DIR", cls.config_dir),
            port=port,
        )
