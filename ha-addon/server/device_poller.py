"""mDNS device discovery and aioesphomeapi version polling."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

logger = logging.getLogger(__name__)

try:
    from zeroconf import ServiceBrowser, Zeroconf
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

try:
    import icmplib  # noqa: F401
    _PING_AVAILABLE = True
except ImportError:
    logger.warning("icmplib not available; ping-based liveness fallback disabled")
    _PING_AVAILABLE = False

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
    mac_address: Optional[str] = None  # e.g. "AA:BB:CC:DD:EE:FF"
    # How was the IP resolved? One of: "mdns", "wifi_use_address",
    # "ethernet_use_address", "openthread_use_address", "wifi_static_ip",
    # "ethernet_static_ip", "mdns_default" (the {name}.local fallback).
    # Surfaced in the UI under the IP so users can see how each device's
    # address was determined (#184).
    address_source: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "ip_address": self.ip_address,
            "online": self.online,
            "running_version": self.running_version,
            "compilation_time": self.compilation_time,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "compile_target": self.compile_target,
            "mac_address": self.mac_address,
            "address_source": self.address_source,
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
        self._address_sources: dict[str, str] = {}  # device_name → e.g. "wifi_use_address"
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
            # C.8: get_running_loop is the modern equivalent of get_event_loop
            # when we're already inside a coroutine — and is the only one that
            # works in 3.12+.
            info = await asyncio.get_running_loop().run_in_executor(
                None, zeroconf.get_service_info, service_type, name
            )
            if info is None:
                return

            device_name = info.name.replace(f".{service_type}", "").strip()
            # ESPHome device names may have the service suffix embedded
            if "." in device_name:
                device_name = device_name.split(".")[0]

            ip = self._extract_address(info)

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
                    existing_key = self._find_existing_device_key(device_name)
                    if existing_key:
                        self._devices[existing_key].online = False
                    return

                # Look up an existing device by normalized name (handles
                # hyphen/underscore differences between YAML's esphome.name
                # and the mDNS-advertised name) so mDNS discovery merges
                # into the YAML-derived row instead of creating a duplicate
                # (bug #179).
                existing_key = self._find_existing_device_key(device_name)
                if existing_key is None:
                    compile_target = self._map_target(device_name)
                    self._devices[device_name] = Device(
                        name=device_name,
                        ip_address=ip or "",
                        compile_target=compile_target,
                        address_source="mdns" if ip else None,
                    )
                    existing_key = device_name

                dev = self._devices[existing_key]
                dev.online = True
                dev.last_seen = _utcnow()
                if ip:
                    dev.ip_address = ip
                    # mDNS only "wins" over the YAML-derived source if the
                    # YAML had no explicit address (was just {name}.local).
                    # Explicit user choices like wifi.use_address /
                    # wifi.manual_ip.static_ip stay authoritative — that
                    # mismatch is itself useful information.
                    if dev.address_source in (None, "mdns_default"):
                        dev.address_source = "mdns"
                if txt_version:
                    dev.running_version = txt_version
                self._save_cache()

            # Trigger an immediate API query for the full version.
            # Prefer use_address from config over mDNS IP. The address override
            # may be keyed under either the normalized or original name; check
            # both. Use existing_key (the merged-into device) for the query so
            # ping/API results land on the right Device row.
            query_addr = (
                self._address_overrides.get(existing_key)
                or self._address_overrides.get(device_name)
                or ip
            )
            if query_addr:
                # C.8: create_task is the modern equivalent of ensure_future
                # when we're scheduling a coroutine on the running loop.
                asyncio.create_task(self._query_device(existing_key, query_addr))

        except Exception:
            logger.exception("Error handling mDNS service change for %s", name)

    @staticmethod
    def _extract_address(info: object) -> Optional[str]:
        """Extract a single human-readable IP address from a zeroconf ServiceInfo.

        Handles both IPv4 (4-byte) and IPv6 (16-byte) packed addresses, which
        is required for Thread devices that advertise via SRP/mDNS over IPv6
        AAAA records (bug #179). Prefers IPv4 when both are present.
        """
        # python-zeroconf provides parsed_addresses() in modern versions —
        # try it first since it handles both families.
        try:
            parsed = info.parsed_addresses()  # type: ignore[attr-defined]
        except Exception:
            parsed = None

        if parsed:
            v4 = [a for a in parsed if "." in a]
            if v4:
                return v4[0]
            return parsed[0]

        # Fall back to manual parsing of the packed bytes
        addrs = getattr(info, "addresses", None) or []
        if not addrs:
            return None
        import socket  # noqa: PLC0415
        v4 = [a for a in addrs if len(a) == 4]
        if v4:
            try:
                return socket.inet_ntoa(v4[0])
            except OSError:
                pass
        v6 = [a for a in addrs if len(a) == 16]
        if v6:
            try:
                return socket.inet_ntop(socket.AF_INET6, v6[0])
            except (OSError, ValueError):
                pass
        return None

    def _find_existing_device_key(self, device_name: str) -> Optional[str]:
        """Return the key under which *device_name* is already stored, or None.

        Matches by hyphen/underscore-normalized name so an mDNS-discovered
        ``my_device`` (mDNS replaces hyphens) merges with a YAML-derived
        ``my-device`` row instead of creating a duplicate (bug #179).
        """
        if device_name in self._devices:
            return device_name
        norm = self._normalize(device_name)
        for key in self._devices:
            if self._normalize(key) == norm:
                return key
        return None

    # ------------------------------------------------------------------
    # Ping liveness check
    # ------------------------------------------------------------------

    async def _ping_device(self, name: str, ip: str) -> bool:
        """Ping a device to check if it is reachable. Returns True if alive.

        Uses UDP-based ICMP (privileged=False) so no root or CAP_NET_RAW is
        required.  Only called when the API connection fails and icmplib is
        installed; guarded by _PING_AVAILABLE at the call site.
        """
        try:
            from icmplib import async_ping  # noqa: PLC0415
            host = await async_ping(ip, count=1, timeout=2, privileged=False)
            return host.is_alive
        except Exception:
            logger.debug("Ping failed for device %s at %s", name, ip, exc_info=True)
            return False

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

            # Query all devices concurrently for fast initial status
            tasks = []
            for name, dev in snapshot.items():
                addr = self._address_overrides.get(name) or dev.ip_address
                if addr:
                    tasks.append(self._query_device(name, addr))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

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
                        dev.mac_address = getattr(info, "mac_address", None) or None
                        dev.online = True
                        dev.last_seen = _utcnow()
                        self._save_cache()
            finally:
                await client.disconnect()
        except Exception as exc:
            exc_str = str(exc).lower()
            if "encryption" in exc_str:
                # Device is reachable but requires encryption and we don't have
                # the key (or the key is wrong). No need to ping — mark online.
                async with self._lock:
                    dev = self._devices.get(name)
                    if dev:
                        dev.online = True
                        dev.last_seen = _utcnow()
                        self._save_cache()
                logger.debug("Device %s at %s requires encryption — marked online", name, ip)
                return

            # API failed for a non-encryption reason — fall back to ping so we
            # can still report liveness even when the native API is unavailable.
            ping_alive = await self._ping_device(name, ip) if _PING_AVAILABLE else False
            async with self._lock:
                dev = self._devices.get(name)
                if dev:
                    if ping_alive:
                        dev.online = True
                        dev.last_seen = _utcnow()
                        self._save_cache()
                        logger.debug(
                            "Device %s at %s: API failed (%s), ping succeeded — marked online",
                            name, ip, exc,
                        )
                    else:
                        dev.online = False
                        logger.debug("Could not reach device %s at %s: %s", name, ip, exc)

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _load_cache(self) -> None:
        """Populate _devices from last-known state so UI has data before mDNS fires.

        Only the STABLE bits are cached: running_version, compilation_time,
        mac_address. The IP address and address_source are deliberately NOT
        cached because they can change between restarts (DHCP lease renewal,
        WiFi reconfiguration, etc.). Stale cached IPs would point at the
        wrong device. Both are repopulated by update_compile_targets at
        startup (from the YAML's get_device_address) and then overridden
        by mDNS discovery as devices come back online (#187).
        """
        try:
            if not DEVICE_CACHE_FILE.exists():
                return
            data = json.loads(DEVICE_CACHE_FILE.read_text())
            for name, info in data.items():
                compile_target = self._map_target(name)
                self._devices[name] = Device(
                    name=name,
                    ip_address="",  # NOT from cache — see docstring
                    online=False,  # unknown until mDNS confirms
                    running_version=info.get("running_version"),
                    compilation_time=info.get("compilation_time"),
                    compile_target=compile_target,
                    mac_address=info.get("mac_address"),
                    # address_source intentionally not cached
                )
            logger.info("Loaded %d devices from cache", len(data))
        except Exception:
            logger.debug("Failed to load device cache", exc_info=True)

    def _save_cache(self) -> None:
        """Persist current device versions and MAC addresses to disk.

        Does NOT persist ip_address or address_source — see _load_cache
        docstring for why.
        """
        try:
            data = {
                name: {
                    "running_version": dev.running_version,
                    "compilation_time": dev.compilation_time,
                    "mac_address": dev.mac_address,
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
        address_sources: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Inform the poller about known YAML targets so it can map device
        names to compile targets.  Also re-maps existing devices.

        *name_to_target* maps ESPHome device names (and filename stems) to
        YAML filenames, handling cases where ``esphome.name`` differs from
        the filename.

        *encryption_keys* maps device names to base64-encoded noise PSK keys
        for devices that require API encryption.

        *address_overrides* maps device names to the canonical address from
        ``scanner.get_device_address`` (always populated, may be ``{name}.local``).

        *address_sources* maps device names to where the address came from
        (e.g. ``wifi_use_address``, ``ethernet_static_ip``, ``mdns_default``).
        Surfaced under the IP in the UI (#184).
        """
        self._compile_targets = list(targets)
        self._name_to_target = name_to_target or {}
        self._encryption_keys = encryption_keys or {}
        self._address_overrides = address_overrides or {}
        self._address_sources = address_sources or {}
        for dev in self._devices.values():
            dev.compile_target = self._map_target(dev.name)

        # Proactively create Device entries for every YAML target. Now that
        # build_name_to_target_map populates address_overrides for ALL targets
        # (via get_device_address, which falls back to {name}.local), every
        # YAML row exists before mDNS discovery — so the mDNS handler merges
        # into it instead of creating a duplicate (bug #179).
        for device_name, addr in self._address_overrides.items():
            source = self._address_sources.get(device_name)
            existing_key = self._find_existing_device_key(device_name)
            if existing_key is None:
                compile_target = self._map_target(device_name)
                self._devices[device_name] = Device(
                    name=device_name,
                    ip_address=addr,
                    online=False,
                    compile_target=compile_target,
                    address_source=source,
                )
                logger.debug("Created device %s from address %s (%s, no mDNS yet)",
                             device_name, addr, source)
            else:
                dev = self._devices[existing_key]
                # Update IP from address override if not already set from mDNS
                if not dev.ip_address:
                    dev.ip_address = addr
                # ALWAYS fill in the address source if it's missing — this
                # covers cached devices loaded from /data/device_cache.json
                # (which were saved before address_source was a field) where
                # the IP is already populated but the source is None (#187).
                if dev.address_source is None and source:
                    dev.address_source = source

    @staticmethod
    def _normalize(name: str) -> str:
        """Normalize a device name for comparison (hyphens ↔ underscores).

        ESPHome normalizes device names for mDNS — hyphens become underscores.
        """
        return name.replace("-", "_")

    def _map_target(self, device_name: str) -> Optional[str]:
        """Return the YAML filename matching *device_name*, or None.

        Checks the name-to-target map first (covers both explicit
        ``esphome.name`` overrides and filename stems), then falls back
        to a direct filename-stem comparison.  Comparisons are
        hyphen/underscore-insensitive because ESPHome normalizes hyphens
        to underscores in mDNS advertisements.
        """
        norm = self._normalize(device_name)
        if device_name in self._name_to_target:
            return self._name_to_target[device_name]
        # Try normalized lookup
        for key, target in self._name_to_target.items():
            if self._normalize(key) == norm:
                return target
        for target in self._compile_targets:
            stem = Path(target).stem
            if self._normalize(stem) == norm:
                return target
        return None

    def get_devices(self) -> list[Device]:
        return list(self._devices.values())

    async def refresh_target(self, compile_target: str) -> bool:
        """Force an immediate device-info refresh for the device whose
        ``compile_target`` matches *compile_target*.

        Used by the API to push fresh ``running_version``/``compilation_time``
        into the UI right after a successful OTA, instead of waiting up to
        ``poll_interval`` seconds for the next mDNS poll cycle (#11).

        Returns True if a refresh was attempted, False if no matching
        device was found or it has no IP yet.
        """
        async with self._lock:
            target_dev: Optional[Device] = None
            for dev in self._devices.values():
                if dev.compile_target == compile_target:
                    target_dev = dev
                    break
            if target_dev is None or not target_dev.ip_address:
                return False
            name = target_dev.name
            ip = self._address_overrides.get(name) or target_dev.ip_address
        # Run the query OUTSIDE the lock — it does network I/O.
        await self._query_device(name, ip)
        return True
