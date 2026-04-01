"""mDNS device discovery and aioesphomeapi version polling."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

logger = logging.getLogger(__name__)

try:
    from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf
    from zeroconf.asyncio import AsyncZeroconf
    ZEROCONF_AVAILABLE = True
except ImportError:
    logger.warning("zeroconf not available; mDNS discovery disabled")
    ZEROCONF_AVAILABLE = False

try:
    import aioesphomeapi
    AIOESPHOMEAPI_AVAILABLE = True
except ImportError:
    logger.warning("aioesphomeapi not available; device version polling disabled")
    AIOESPHOMEAPI_AVAILABLE = False

if TYPE_CHECKING:
    from zeroconf import ServiceBrowser, Zeroconf  # noqa: F811
    from zeroconf.asyncio import AsyncZeroconf  # noqa: F811

ESPHOME_SERVICE = "_esphomelib._tcp.local."
DEVICE_CACHE_FILE = Path("/data/device_cache.json")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Device:
    name: str
    ip_address: str
    online: bool = False
    running_version: Optional[str] = None
    compilation_time: Optional[str] = None  # e.g. "Mar 29 2026, 17:00:00"
    last_seen: Optional[datetime] = None
    compile_target: Optional[str] = None  # e.g. "living_room.yaml"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "ip_address": self.ip_address,
            "online": self.online,
            "running_version": self.running_version,
            "compilation_time": self.compilation_time,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "compile_target": self.compile_target,
        }


class DevicePoller:
    """
    Discovers ESPHome devices via mDNS and polls their firmware version
    via the native API.
    """

    def __init__(self, poll_interval: int = 60) -> None:
        self._poll_interval = poll_interval
        self._devices: dict[str, Device] = {}  # keyed by device name
        self._compile_targets: list[str] = []
        self._name_to_target: dict[str, str] = {}
        self._encryption_keys: dict[str, str] = {}  # device_name → noise_psk (base64)
        self._address_overrides: dict[str, str] = {}  # device_name → use_address
        self._lock = asyncio.Lock()
        self._zeroconf: Optional[AsyncZeroconf] = None
        self._browser: Optional[ServiceBrowser] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, app: object = None) -> None:
        """Start mDNS listener and background polling task."""
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._load_cache()
        if ZEROCONF_AVAILABLE:
            await self._start_mdns()
        else:
            logger.warning("Skipping mDNS discovery (zeroconf unavailable)")

        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("DevicePoller started (poll_interval=%ds)", self._poll_interval)

    async def stop(self) -> None:
        """Stop background tasks and release resources."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        if self._zeroconf is not None:
            try:
                await self._zeroconf.async_close()
            except Exception:
                logger.exception("Error closing zeroconf")
        logger.info("DevicePoller stopped")

    # ------------------------------------------------------------------
    # mDNS
    # ------------------------------------------------------------------

    async def _start_mdns(self) -> None:
        try:
            self._zeroconf = AsyncZeroconf()
            self._browser = ServiceBrowser(
                self._zeroconf.zeroconf,
                ESPHOME_SERVICE,
                handlers=[self._on_service_state_change],
            )
            logger.info("mDNS ServiceBrowser started for %s", ESPHOME_SERVICE)
        except Exception:
            logger.exception("Failed to start mDNS browser")

    def _on_service_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: object,
    ) -> None:
        """Callback invoked by zeroconf on service add/remove/update."""
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(
            self._loop.create_task,
            self._handle_service_change(zeroconf, service_type, name, state_change),
        )

    async def _handle_service_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: object,
    ) -> None:
        try:
            from zeroconf import ServiceStateChange  # noqa: PLC0415
            info = await asyncio.get_event_loop().run_in_executor(
                None, zeroconf.get_service_info, service_type, name
            )
            if info is None:
                return

            device_name = info.name.replace(f".{service_type}", "").strip()
            # ESPHome device names may have the service suffix embedded
            if "." in device_name:
                device_name = device_name.split(".")[0]

            ip = None
            if info.addresses:
                import socket  # noqa: PLC0415
                ip = socket.inet_ntoa(info.addresses[0])

            # Extract version from TXT record
            txt_version: Optional[str] = None
            if info.properties:
                for key, val in info.properties.items():
                    k = key.decode() if isinstance(key, bytes) else key
                    if k == "version":
                        txt_version = val.decode() if isinstance(val, bytes) else val
                        break

            async with self._lock:
                if state_change == ServiceStateChange.Removed:
                    if device_name in self._devices:
                        self._devices[device_name].online = False
                    return

                if device_name not in self._devices:
                    compile_target = self._map_target(device_name)
                    self._devices[device_name] = Device(
                        name=device_name,
                        ip_address=ip or "",
                        compile_target=compile_target,
                    )

                dev = self._devices[device_name]
                dev.online = True
                dev.last_seen = _utcnow()
                if ip:
                    dev.ip_address = ip
                if txt_version:
                    dev.running_version = txt_version
                self._save_cache()

            # Trigger an immediate API query for the full version
            # Prefer use_address from config over mDNS IP
            query_addr = self._address_overrides.get(device_name) or ip
            if query_addr:
                asyncio.ensure_future(self._query_device(device_name, query_addr))

        except Exception:
            logger.exception("Error handling mDNS service change for %s", name)

    # ------------------------------------------------------------------
    # API polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Periodically poll each known device via the native API."""
        # Poll immediately on startup so cached devices (loaded from disk) get
        # a live status check right away.  For fresh installs (empty cache) this
        # is a no-op; mDNS will trigger _query_device as devices are discovered.
        while self._running:
            async with self._lock:
                snapshot = dict(self._devices)

            for name, dev in snapshot.items():
                # Prefer use_address from config, fall back to mDNS IP
                addr = self._address_overrides.get(name) or dev.ip_address
                if addr:
                    await self._query_device(name, addr)

            await asyncio.sleep(self._poll_interval)

    async def _query_device(self, name: str, ip: str) -> None:
        """Connect to device, fetch device_info, disconnect."""
        if not AIOESPHOMEAPI_AVAILABLE:
            return
        try:
            noise_psk = self._encryption_keys.get(name)
            client = aioesphomeapi.APIClient(ip, 6053, password=None, noise_psk=noise_psk)
            await client.connect(login=True)
            try:
                info = await client.device_info()
                async with self._lock:
                    dev = self._devices.get(name)
                    if dev:
                        dev.running_version = info.esphome_version
                        dev.compilation_time = getattr(info, "compilation_time", None) or None
                        dev.online = True
                        dev.last_seen = _utcnow()
                        self._save_cache()
            finally:
                await client.disconnect()
        except Exception as exc:
            exc_str = str(exc).lower()
            async with self._lock:
                dev = self._devices.get(name)
                if dev:
                    if "encryption" in exc_str:
                        # Device is online but requires encryption and we don't
                        # have the key (or the key is wrong). Mark as online.
                        dev.online = True
                        dev.last_seen = _utcnow()
                        self._save_cache()
                        logger.debug("Device %s at %s requires encryption — marked online", name, ip)
                    else:
                        dev.online = False
                        logger.debug("Could not query device %s at %s: %s", name, ip, str(exc))

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _load_cache(self) -> None:
        """Populate _devices from last-known state so UI has data before mDNS fires."""
        try:
            if not DEVICE_CACHE_FILE.exists():
                return
            data = json.loads(DEVICE_CACHE_FILE.read_text())
            for name, info in data.items():
                compile_target = self._map_target(name)
                self._devices[name] = Device(
                    name=name,
                    ip_address=info.get("ip_address", ""),
                    online=False,  # unknown until mDNS confirms
                    running_version=info.get("running_version"),
                    compilation_time=info.get("compilation_time"),
                    compile_target=compile_target,
                )
            logger.info("Loaded %d devices from cache", len(data))
        except Exception:
            logger.debug("Failed to load device cache", exc_info=True)

    def _save_cache(self) -> None:
        """Persist current device IPs and versions to disk."""
        try:
            data = {
                name: {
                    "ip_address": dev.ip_address,
                    "running_version": dev.running_version,
                    "compilation_time": dev.compilation_time,
                }
                for name, dev in self._devices.items()
            }
            DEVICE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = DEVICE_CACHE_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(DEVICE_CACHE_FILE)
        except Exception:
            logger.debug("Failed to save device cache", exc_info=True)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def update_compile_targets(
        self,
        targets: list[str],
        name_to_target: Optional[dict[str, str]] = None,
        encryption_keys: Optional[dict[str, str]] = None,
        address_overrides: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Inform the poller about known YAML targets so it can map device
        names to compile targets.  Also re-maps existing devices.

        *name_to_target* maps ESPHome device names (and filename stems) to
        YAML filenames, handling cases where ``esphome.name`` differs from
        the filename.

        *encryption_keys* maps device names to base64-encoded noise PSK keys
        for devices that require API encryption.

        *address_overrides* maps device names to ``wifi.use_address`` values.
        """
        self._compile_targets = list(targets)
        self._name_to_target = name_to_target or {}
        self._encryption_keys = encryption_keys or {}
        self._address_overrides = address_overrides or {}
        for dev in self._devices.values():
            dev.compile_target = self._map_target(dev.name)

    def _map_target(self, device_name: str) -> Optional[str]:
        """Return the YAML filename matching *device_name*, or None.

        Checks the name-to-target map first (covers both explicit
        ``esphome.name`` overrides and filename stems), then falls back
        to a direct filename-stem comparison.
        """
        if device_name in self._name_to_target:
            return self._name_to_target[device_name]
        for target in self._compile_targets:
            stem = Path(target).stem
            if stem == device_name:
                return target
        return None

    def get_devices(self) -> list[Device]:
        return list(self._devices.values())
