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
        # PR #80 review: skip advertising entirely when we don't have a
        # primary IPv4. Prior code shipped ``http://:<port>`` in the
        # ``base_url`` property when ``ip is None`` — the integration's
        # config flow would then try to connect to an empty-host URL
        # and surface a confusing error. If we have no IP, the
        # integration can't reach us; better to not advertise at all
        # than advertise a malformed URL. Logged at WARNING so an
        # operator on an IPv6-only stack or mid-boot sees the signal.
        if ip is None:
            logger.warning(
                "mDNS advertise skipped — no primary IPv4 available yet. "
                "The integration's zeroconf discovery won't find this "
                "add-on until a restart picks up a routable IP.",
            )
            return
        addresses = [socket.inet_aton(ip)]
        base_url = f"http://{ip}:{self._port}"

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

        # PR #80 review: ``socket.gethostname()`` is POSIX-guaranteed
        # to return a non-empty string, so the old ``if gethostname()
        # else None`` guard was dead — the else branch was unreachable.
        # The failure mode the old guard probably meant to cover is
        # ``localhost`` (can't be resolved by peers), which needs an
        # explicit check.
        hostname = socket.gethostname()
        server = (
            f"{hostname}.local."
            if hostname and hostname.lower() != "localhost"
            else None
        )

        self._info = ServiceInfo(
            type_=SERVICE_TYPE,
            name=full_name,
            addresses=addresses,
            port=self._port,
            properties=properties,
            server=server,
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
