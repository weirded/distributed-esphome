"""mDNS advertisement for ESPHome Fleet (HI.7).

Registers `_esphome-fleet._tcp.local.` so the HA custom integration's
zeroconf matcher auto-discovers the add-on. Properties carry the
running add-on version + base URL; the integration uses them to pre-fill
the config flow's base-URL field.

Registered once at startup, unregistered at shutdown.
"""

from __future__ import annotations

import logging
import socket
from pathlib import Path
from typing import Optional

from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_esphome-fleet._tcp.local."


def _read_version() -> str:
    """Return the add-on version baked into the container, or 'unknown'."""
    for p in (Path("/app/VERSION"), Path(__file__).parent.parent / "VERSION"):
        try:
            return p.read_text(encoding="utf-8").strip() or "unknown"
        except Exception:
            continue
    return "unknown"


def _primary_ipv4() -> str | None:
    """Best-effort local IPv4 — the address HA will use to reach the add-on."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Non-routable dest; just forces the kernel to pick an
            # outbound interface so `getsockname()` returns our IP.
            s.settimeout(0.1)
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except Exception:
        return None


class FleetAdvertiser:
    """Owns a ServiceInfo registration for the add-on's own mDNS record."""

    def __init__(self, zc: AsyncZeroconf, port: int, service_name: str = "ESPHome Fleet") -> None:
        self._zc = zc
        self._port = port
        self._service_name = service_name
        self._info: Optional[ServiceInfo] = None

    async def start(self) -> None:
        version = _read_version()
        ip = _primary_ipv4()
        addresses = [socket.inet_aton(ip)] if ip else []
        base_url = f"http://{ip}:{self._port}" if ip else f"http://:{self._port}"

        # Sanitize service name — mDNS instance names can't contain
        # dots or be longer than 63 bytes. Keep it short and stable.
        instance = self._service_name.replace(".", " ")[:60]
        full_name = f"{instance}.{SERVICE_TYPE}"

        properties = {
            "version": version,
            "base_url": base_url,
            # protocol handshake version — integration can reject mismatches
            # once we start making breaking changes.
            "protocol": "1",
        }

        self._info = ServiceInfo(
            type_=SERVICE_TYPE,
            name=full_name,
            addresses=addresses,
            port=self._port,
            properties=properties,
            server=(f"{socket.gethostname()}.local." if socket.gethostname() else None),
        )

        try:
            await self._zc.async_register_service(self._info)
            logger.info(
                "mDNS advertising %s on port %d (v%s, %s)",
                SERVICE_TYPE, self._port, version, base_url,
            )
        except Exception:
            logger.exception("Failed to register mDNS service %s", SERVICE_TYPE)
            self._info = None

    async def stop(self) -> None:
        if self._info is None:
            return
        try:
            await self._zc.async_unregister_service(self._info)
            logger.info("mDNS unregistered %s", SERVICE_TYPE)
        except Exception:
            logger.debug("mDNS unregister failed for %s", SERVICE_TYPE, exc_info=True)
        finally:
            self._info = None
