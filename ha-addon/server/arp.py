"""Tiny /proc/net/arp reader used as a MAC→IP fallback.

Bug #7 (1.6.1): the Devices tab's IP column can be empty for devices
whose mDNS broadcast was missed (re-joined the network while the add-on
wasn't listening, a chatty neighbor drowned the packet, …) even when
the device is live and reachable. The add-on runs with
``host_network: true`` so it can read the host's ARP cache via
``/proc/net/arp``; when we've previously seen the device's MAC (cached
on the :class:`device_poller.Device` row from a native-API poll), a
quick ARP lookup fills in the IP without waiting for the next mDNS
broadcast.

Kept deliberately small:

- No subprocess (``ip neigh``, ``arp -n``) — those would need a binary
  from the AppArmor profile. ``/proc/net/arp`` is a cheap read already
  permitted by the profile.
- Results cache for 30 seconds so a 1 Hz UI poll doesn't re-read the
  file on every request.
- Returns ``None`` when the file is missing (development on a non-Linux
  host, container without host networking) or a MAC isn't in the cache;
  callers fall through to whatever they had before.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


_ARP_PATH = Path("/proc/net/arp")
_CACHE_TTL_SECONDS = 30.0
# ARP entries whose ``HW address`` field equals the all-zero sentinel
# are "incomplete" — the kernel never resolved the neighbour. Skip them
# so we don't accidentally report a stale IP whose MAC hasn't been
# confirmed.
_INCOMPLETE_MAC = "00:00:00:00:00:00"


_cache: tuple[float, dict[str, str]] | None = None


def _normalize_mac(mac: str) -> str:
    """Lower-case + colon-separated canonical form."""
    return mac.strip().lower()


def _parse() -> dict[str, str]:
    """Return a fresh ``mac → ip`` mapping from ``/proc/net/arp``.

    Columns: ``IP address  HW type  Flags  HW address  Mask  Device``.
    The header row always starts with ``IP address`` so it's easy to
    skip. Malformed rows are dropped — this helper never raises from
    parsing failures because a half-readable ARP table is still useful.
    """
    result: dict[str, str] = {}
    try:
        lines = _ARP_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except (FileNotFoundError, PermissionError):
        return result
    except OSError:
        logger.debug("Couldn't read %s", _ARP_PATH, exc_info=True)
        return result
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        ip, _hw_type, _flags, mac = parts[0], parts[1], parts[2], parts[3]
        mac_lc = _normalize_mac(mac)
        if mac_lc == _INCOMPLETE_MAC:
            continue
        result[mac_lc] = ip
    return result


def lookup(mac: str) -> str | None:
    """Return the IP most recently associated with *mac*, or ``None``.

    Normalises *mac* to lower-case so a caller passing the aioesphomeapi
    upper-case form still hits the cache. Cached for 30s to keep the
    typical per-render path zero-cost.
    """
    if not mac:
        return None
    global _cache  # noqa: PLW0603 — module-level memoisation is fine
    now = time.monotonic()
    if _cache is None or (now - _cache[0]) > _CACHE_TTL_SECONDS:
        _cache = (now, _parse())
    return _cache[1].get(_normalize_mac(mac))


def invalidate_cache() -> None:
    """Force a re-read on the next :func:`lookup`. Used by tests."""
    global _cache  # noqa: PLW0603
    _cache = None
