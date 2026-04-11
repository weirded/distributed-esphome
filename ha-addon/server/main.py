"""aiohttp application entry point for the ESPHome Distributed Build Server."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import aiohttp
from aiohttp import web

import api as api_module
import ui_api as ui_api_module
from app_config import AppConfig
from device_poller import DevicePoller
from job_queue import JobQueue
from registry import WorkerRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Suppress noisy per-request access logs (heartbeats, polls, UI refreshes)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
# Suppress aioesphomeapi connection warnings (expected when devices are offline)
logging.getLogger("aioesphomeapi.connection").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

@web.middleware
async def version_header_middleware(request: web.Request, handler):
    """Attach X-Server-Version header to every response for UI change detection."""
    response = await handler(request)
    from api import _get_server_client_version  # noqa: PLC0415
    from constants import HEADER_X_SERVER_VERSION  # noqa: PLC0415
    response.headers[HEADER_X_SERVER_VERSION] = _get_server_client_version()
    return response


# E.9: defence-in-depth security headers on every UI-tier response. Applied
# to ``/``, ``/index.html``, ``/assets/*``, and every ``/ui/api/*`` endpoint
# (the browser-facing surface). NOT applied to ``/api/v1/*`` since those are
# consumed programmatically by build workers and the headers add no value.
#
# CSP design notes:
# - script-src needs 'unsafe-inline' because Monaco's @monaco-editor/react
#   loader injects inline script elements for worker bootstrap. Tailwind v4
#   also generates inline styles at runtime.
# - style-src needs 'unsafe-inline' for the same Tailwind + Monaco reason.
# - connect-src must allow wss: for the live-log WebSocket and
#   https://schema.esphome.io for the editor schema fetcher (api/esphomeSchema.ts).
# - worker-src 'self' blob: covers Monaco's editor worker.
# - frame-ancestors 'self' enforces clickjacking protection without breaking
#   HA Ingress (which loads us in an iframe served from the same origin).
# NOTE: ``cdn.jsdelivr.net`` is allowed in script-src + connect-src because
# the @monaco-editor/react wrapper loads Monaco's runtime from jsDelivr by
# default. Bundling Monaco locally (via vite-plugin-monaco-editor) would let
# us drop this origin entirely and ship a fully self-hosted UI; tracked as a
# follow-up after #15 was found mid-1.3.1 (the editor was breaking because
# the CSP from E.9 blocked the CDN). For now we allow it explicitly so the
# editor works in all install topologies.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https:; "
    "font-src 'self' data: https://cdn.jsdelivr.net; "
    "connect-src 'self' ws: wss: https://schema.esphome.io https://cdn.jsdelivr.net; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'self'; "
    "base-uri 'self'; "
    "form-action 'self'"
)
_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "accelerometer=(), camera=(), geolocation=(), microphone=(), payment=(), usb=()",
    "X-Frame-Options": "SAMEORIGIN",  # legacy fallback for browsers that ignore CSP frame-ancestors
}


@web.middleware
async def security_headers_middleware(request: web.Request, handler):
    """Attach defence-in-depth security headers to UI-tier responses (E.9)."""
    response = await handler(request)
    path = request.path
    if path.startswith("/api/v1/"):
        # Worker tier — no benefit, skip.
        return response
    # Everything else (UI HTML, static assets, /ui/api/*, /, /index.html)
    # gets the headers. WebSocket upgrades (101 Switching Protocols) inherit
    # them too, which is harmless.
    for k, v in _SECURITY_HEADERS.items():
        # Don't clobber a header an inner handler explicitly set.
        if k not in response.headers:
            response.headers[k] = v
    return response


def _normalize_peer_ip(raw: str) -> str:
    """Canonicalize a peer IP string for comparison against HA_SUPERVISOR_IP.

    Strips IPv4-mapped IPv6 prefixes (``::ffff:172.30.32.2`` → ``172.30.32.2``)
    and zone identifiers (``fe80::1%eth0`` → ``fe80::1``), so an IPv4 string
    in HA_SUPERVISOR_IP still matches the same supervisor coming in over a
    dual-stack socket. Falls back to the raw string if parsing fails — that
    way an unparseable address simply won't match the supervisor (which is
    safer than crashing the request).
    """
    if not raw:
        return ""
    # Strip IPv6 zone id (e.g. ``fe80::1%eth0``)
    raw = raw.split("%", 1)[0]
    try:
        import ipaddress  # noqa: PLC0415
        addr = ipaddress.ip_address(raw)
        # IPv4-mapped IPv6 → unwrap to plain IPv4 string
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return str(addr)
    except (ValueError, ImportError):
        return raw


@web.middleware
async def auth_middleware(request: web.Request, handler):
    path = request.path

    # /ui/api/* — no auth; HA handles ingress authentication
    if path.startswith("/ui/api/") or path in ("/", "/index.html"):
        return await handler(request)

    # /api/v1/* — require Bearer token UNLESS from HA supervisor address
    if path.startswith("/api/v1/"):
        # ``transport`` may be None during tests or for some edge-case
        # transports; ``peername`` may also be None even on a real transport
        # (e.g. unix-socket connections, closed streams). Handle both without
        # crashing — fall through to token auth in either case. C.2.
        peer_ip = ""
        try:
            peer = request.transport.get_extra_info("peername") if request.transport else None
        except Exception:
            peer = None
        if peer:
            raw_ip = peer[0] if isinstance(peer, tuple) else str(peer)
            peer_ip = _normalize_peer_ip(raw_ip)

        from constants import HA_SUPERVISOR_IP, HEADER_AUTHORIZATION  # noqa: PLC0415
        # Normalize the configured Supervisor IP too so an IPv6-mapped form
        # like ``::ffff:172.30.32.2`` from a dual-stack Docker network still
        # matches the canonical IPv4 string. Compare canonicalized forms.
        if peer_ip and peer_ip == _normalize_peer_ip(HA_SUPERVISOR_IP):
            return await handler(request)

        cfg: AppConfig = request.app["config"]
        if cfg.token:
            from helpers import constant_time_compare  # noqa: PLC0415
            auth_header = request.headers.get(HEADER_AUTHORIZATION, "")
            if auth_header.startswith("Bearer ") and constant_time_compare(auth_header[7:], cfg.token):
                return await handler(request)

            # Diagnose the refusal. Each branch logs a distinct structured
            # reason so operators can tell "wrong token" from "missing header"
            # from "non-supervisor peer IP" without enabling debug logging.
            if not auth_header:
                reason = "missing_authorization_header"
            elif not auth_header.startswith("Bearer "):
                reason = "authorization_not_bearer_scheme"
            else:
                reason = "bearer_token_mismatch"
            logger.warning(
                "401 on %s: reason=%s peer_ip=%s (expected supervisor=%s)",
                path, reason, peer_ip or "<unknown>", HA_SUPERVISOR_IP,
            )
        else:
            # No token configured — allow all (development mode)
            logger.warning("No auth token configured; allowing unauthenticated request to %s", path)
            return await handler(request)

        return web.json_response({"error": "Unauthorized"}, status=401)

    # Everything else — pass through
    return await handler(request)


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def timeout_checker(app: web.Application) -> None:
    """Background task: check for timed-out jobs every 30 seconds.
    Also prunes terminal jobs older than 1 hour to keep the queue tidy."""
    queue: JobQueue = app["queue"]
    prune_counter = 0
    while True:
        await asyncio.sleep(30)
        try:
            timed_out = await queue.check_timeouts()
            if timed_out:
                logger.info("Timeout checker: processed %d timed-out jobs", len(timed_out))
            # Prune old finished jobs every ~5 minutes (every 10th cycle)
            prune_counter += 1
            if prune_counter >= 10:
                prune_counter = 0
                pruned = await queue.prune_old_terminal(max_age_seconds=3600)
                if pruned:
                    logger.info("Pruned %d old terminal jobs", pruned)
        except Exception:
            logger.exception("Error in timeout checker")


async def ha_entity_poller(app: web.Application) -> None:
    """Background task: poll HA entity registry every 30s to determine which
    ESPHome devices are configured in Home Assistant and whether they are
    currently connected.

    Requires SUPERVISOR_TOKEN (injected automatically when hassio_api: true).
    Stores results in app["ha_entity_status"]: dict[str, {configured, connected}]
    keyed by normalised device name (hyphens replaced with underscores, lowercase).
    """
    import os  # noqa: PLC0415

    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        logger.info("No SUPERVISOR_TOKEN — HA entity status polling disabled")
        return

    headers = {"Authorization": f"Bearer {token}"}
    timeout = aiohttp.ClientTimeout(total=10)
    first_poll = True

    # Repeated identical failures are demoted to DEBUG after the second
    # occurrence of the same fingerprint, so a persistent outage (HA down,
    # network blip) doesn't drown the log and mask unrelated problems. A
    # single iteration can emit multiple warnings with different fingerprints
    # (e.g. both "template_exception" and "poll_exception") and each is
    # counted independently. Any successful poll clears all counts.
    warning_counts: dict[str, int] = {}

    def _log_poll_warning(fingerprint: str, message: str, *args: object, exc_info: bool = False) -> None:
        count = warning_counts.get(fingerprint, 0) + 1
        warning_counts[fingerprint] = count
        if count <= 2:
            logger.warning(message, *args, exc_info=exc_info)
            if count == 2:
                logger.warning(
                    "Above warning is repeating; further identical failures "
                    "will be logged at DEBUG level until the next success."
                )
        else:
            logger.debug(message, *args, exc_info=exc_info)

    def _reset_poll_warnings() -> None:
        warning_counts.clear()

    while True:
        # Poll immediately on first iteration, then every 30s
        if not first_poll:
            await asyncio.sleep(30)
        try:
            import json as _json  # noqa: PLC0415

            async with aiohttp.ClientSession() as session:
                # 1. Use the template API to get ALL ESPHome entity IDs.
                #    This works even for devices without a _status sensor.
                esphome_entity_ids: list[str] = []
                try:
                    async with session.post(
                        "http://supervisor/core/api/template",
                        headers={**headers, "Content-Type": "application/json"},
                        json={"template": "{{ integration_entities('esphome') | list | tojson }}"},
                        timeout=timeout,
                    ) as resp:
                        if resp.status == 200:
                            raw = await resp.text()
                            try:
                                parsed = _json.loads(raw)
                                esphome_entity_ids = parsed if isinstance(parsed, list) else []
                            except (_json.JSONDecodeError, TypeError):
                                _log_poll_warning(
                                    "template_unparseable",
                                    "HA template API returned unparseable response: %.200s", raw,
                                )
                        else:
                            body = await resp.text()
                            _log_poll_warning(
                                f"template_http_{resp.status}",
                                "HA template API returned HTTP %d: %.200s", resp.status, body,
                            )
                except Exception:
                    _log_poll_warning(
                        "template_exception",
                        "Template API call failed", exc_info=True,
                    )

                # 1b. Get MAC addresses for ESPHome devices via template API.
                # ESPHome devices store MACs in device connections (not identifiers):
                #   connections = [["mac", "50:02:91:3c:11:43"]]
                ha_mac_set: set[str] = set()
                if esphome_entity_ids:
                    try:
                        tmpl = (
                            "{%- set ns = namespace(macs=[], seen=[]) -%}"
                            "{%- for eid in integration_entities('esphome') -%}"
                            "  {%- set did = device_id(eid) -%}"
                            "  {%- if did and did not in ns.seen -%}"
                            "    {%- set ns.seen = ns.seen + [did] -%}"
                            "    {%- set conns = device_attr(did, 'connections') -%}"
                            "    {%- if conns -%}"
                            "      {%- for conn in conns -%}"
                            "        {%- if conn[0] == 'mac' -%}"
                            "          {%- set ns.macs = ns.macs + [conn[1]] -%}"
                            "        {%- endif -%}"
                            "      {%- endfor -%}"
                            "    {%- endif -%}"
                            "  {%- endif -%}"
                            "{%- endfor -%}"
                            "{{ ns.macs | unique | list | tojson }}"
                        )
                        async with session.post(
                            "http://supervisor/core/api/template",
                            headers={**headers, "Content-Type": "application/json"},
                            json={"template": tmpl},
                            timeout=timeout,
                        ) as resp:
                            if resp.status == 200:
                                raw_macs = await resp.text()
                                try:
                                    parsed_macs = _json.loads(raw_macs)
                                    if isinstance(parsed_macs, list):
                                        ha_mac_set = {str(m).lower() for m in parsed_macs}
                                except (_json.JSONDecodeError, TypeError):
                                    pass
                    except Exception:
                        logger.debug("MAC template query failed", exc_info=True)

                # 2. Fetch states for connectivity info
                async with session.get(
                    "http://supervisor/core/api/states",
                    headers=headers,
                    timeout=timeout,
                ) as resp:
                    if resp.status != 200:
                        _log_poll_warning(
                            f"states_http_{resp.status}",
                            "HA states returned HTTP %d — check homeassistant_api: true in config.yaml",
                            resp.status,
                        )
                        continue
                    states: list[dict] = await resp.json()

            # Build connectivity map from binary_sensor.*_status with device_class=connectivity
            connectivity: dict[str, bool] = {}  # norm_name → connected
            for entity in states:
                entity_id: str = entity.get("entity_id", "")
                if not entity_id.startswith("binary_sensor.") or not entity_id.endswith("_status"):
                    continue
                attrs = entity.get("attributes") or {}
                if attrs.get("device_class") != "connectivity":
                    continue
                norm_name = entity_id[len("binary_sensor."):-len("_status")]
                connectivity[norm_name] = entity.get("state") == "on"

            # Build ha_status from ESPHome entity IDs (configured) + connectivity
            ha_status: dict[str, dict] = {}

            # Extract unique device name prefixes from entity IDs.
            # ESPHome entities follow the pattern: <domain>.<device_name>_<entity_suffix>
            # We collect all unique prefixes by stripping the domain and finding the
            # longest prefix that matches a connectivity key, or the full local part.
            esphome_device_names: set[str] = set()
            for eid in esphome_entity_ids:
                if "." not in eid:
                    continue
                local = eid.split(".", 1)[1]  # e.g. "nespresso_machine_temperature"
                # Check if any connectivity key is a prefix of this entity
                for conn_name in connectivity:
                    if local == conn_name or local.startswith(conn_name + "_"):
                        esphome_device_names.add(conn_name)
                        break
                else:
                    # No connectivity match — try to derive device name from entity ID.
                    # The _status entity would be the definitive prefix, but it may not
                    # exist. Store the full local as a candidate; _ha_status_for_target
                    # will match by prefix.
                    esphome_device_names.add(local)

            # All connectivity-matched devices get configured=True + connected state
            for name in connectivity:
                ha_status[name] = {"configured": True, "connected": connectivity[name]}

            # All other ESPHome entities mark their device as configured (connected unknown)
            for name in esphome_device_names:
                if name not in ha_status:
                    ha_status[name] = {"configured": True, "connected": None}

            app["ha_entity_status"].clear()
            app["ha_entity_status"].update(ha_status)
            app["ha_mac_set"] = ha_mac_set

            # A full successful poll resets the suppression state so the next
            # transient failure gets its warning re-promoted.
            _reset_poll_warnings()

            if first_poll:
                first_poll = False
                configured_count = len(ha_status)
                connected_count = sum(1 for v in ha_status.values() if v.get("connected") is not None)
                logger.info(
                    "HA entity poller: %d ESPHome entities from template API, "
                    "%d devices configured, %d with connectivity status",
                    len(esphome_entity_ids),
                    configured_count,
                    connected_count,
                )
            else:
                logger.debug(
                    "HA entity status updated: %d ESPHome devices",
                    len(ha_status),
                )

        except Exception:
            _log_poll_warning(
                "poll_exception",
                "Error polling HA entity status", exc_info=True,
            )
        finally:
            # Always clear first_poll so subsequent retries sleep 30s,
            # even when the first attempt fails with an exception or a
            # non-200 status (which uses `continue` to restart the loop).
            first_poll = False


async def config_scanner(app: web.Application) -> None:
    """Background task: re-scan config dir every 30s and update device poller targets."""
    from scanner import scan_configs, build_name_to_target_map  # noqa: PLC0415

    cfg: AppConfig = app["config"]
    device_poller = app.get("device_poller")
    prev_targets: list[str] = []

    while True:
        await asyncio.sleep(30)
        try:
            targets = scan_configs(cfg.config_dir)
            if targets != prev_targets:
                logger.info("Config change detected: %d targets (was %d)", len(targets), len(prev_targets))
                if device_poller:
                    name_map, enc_keys, addr_overrides, addr_sources = build_name_to_target_map(cfg.config_dir, targets)
                    device_poller.update_compile_targets(targets, name_map, enc_keys, addr_overrides, addr_sources)
                prev_targets = targets
        except Exception:
            logger.exception("Error in config scanner")


async def schedule_checker(app: web.Application) -> None:
    """Background task: check per-device cron schedules every 60s.

    For each target that has a ``schedule`` + ``schedule_enabled: true`` in its
    ``# distributed-esphome:`` comment block, compute whether the next cron tick
    has passed since the last run. If so, enqueue a compile+OTA job (same path
    as clicking Upgrade) and write ``schedule_last_run`` back to the comment.
    """
    import uuid as _uuid  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415

    from scanner import scan_configs, read_device_meta, write_device_meta, get_esphome_version  # noqa: PLC0415

    try:
        from croniter import croniter  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError:
        logger.warning("croniter not installed — per-device scheduling disabled")
        return

    cfg: AppConfig = app["config"]
    queue: JobQueue = app["queue"]

    app["schedule_checker_started_at"] = datetime.now(timezone.utc).isoformat()
    app["schedule_checker_tick_count"] = 0
    app["schedule_checker_last_tick"] = None
    app["schedule_checker_last_error"] = None
    app["schedule_checker_seen_once"] = {}

    logger.info("schedule_checker started (config_dir=%s)", cfg.config_dir)
    while True:
        await asyncio.sleep(60)
        try:
            targets = scan_configs(cfg.config_dir)
            now = datetime.now(timezone.utc)
            app["schedule_checker_tick_count"] += 1
            app["schedule_checker_last_tick"] = now.isoformat()
            logger.info("schedule_checker tick at %s — %d targets", now.isoformat(), len(targets))

            for target in targets:
                try:
                    meta = read_device_meta(cfg.config_dir, target)

                    # #17: one-time schedule — fires once then auto-clears.
                    once_str = meta.get("schedule_once")
                    if once_str:
                        app["schedule_checker_seen_once"][target] = once_str
                        logger.info("schedule_checker: %s has schedule_once=%s", target, once_str)
                        try:
                            once_dt = datetime.fromisoformat(once_str)
                            if once_dt.tzinfo is None:
                                once_dt = once_dt.replace(tzinfo=timezone.utc)
                            logger.info("schedule_checker: %s once_dt=%s now=%s due=%s", target, once_dt.isoformat(), now.isoformat(), once_dt <= now)
                            if once_dt <= now:
                                version = meta.get("pin_version") or get_esphome_version()
                                device_poller = app.get("device_poller")
                                ota_address = None
                                if device_poller:
                                    for dev in device_poller.get_devices():
                                        if dev.compile_target == target and dev.ip_address:
                                            ota_address = (
                                                device_poller._address_overrides.get(dev.name)
                                                or dev.ip_address
                                            )
                                            break
                                run_id = str(_uuid.uuid4())
                                job = await queue.enqueue(
                                    target=target,
                                    esphome_version=version,
                                    run_id=run_id,
                                    timeout_seconds=cfg.job_timeout,
                                    ota_address=ota_address,
                                )
                                if job is not None:
                                    job.scheduled = True
                                    logger.info(
                                        "One-time schedule fired for %s (at=%s): enqueued job %s",
                                        target, once_str, job.id,
                                    )
                                # Auto-clear the one-time schedule.
                                fresh_meta = read_device_meta(cfg.config_dir, target)
                                fresh_meta.pop("schedule_once", None)
                                write_device_meta(cfg.config_dir, target, fresh_meta)
                                continue  # don't also check recurring schedule
                        except Exception:
                            logger.exception("One-time schedule parse failed for %s", target)

                    cron_expr = meta.get("schedule")
                    enabled = meta.get("schedule_enabled", False)
                    if not cron_expr or not enabled:
                        continue

                    # Determine last_run. If absent, use epoch so the first
                    # cron tick after the schedule is set fires immediately.
                    last_run_str = meta.get("schedule_last_run")
                    if last_run_str:
                        last_run = datetime.fromisoformat(last_run_str)
                        if last_run.tzinfo is None:
                            last_run = last_run.replace(tzinfo=timezone.utc)
                    else:
                        last_run = datetime(2000, 1, 1, tzinfo=timezone.utc)

                    cron = croniter(cron_expr, last_run)
                    next_run = cron.get_next(datetime)
                    if next_run.tzinfo is None:
                        next_run = next_run.replace(tzinfo=timezone.utc)

                    if next_run > now:
                        continue  # not yet due

                    # Determine compile version: pinned or global.
                    version = meta.get("pin_version") or get_esphome_version()

                    # Get OTA address if available.
                    device_poller = app.get("device_poller")
                    ota_address = None
                    if device_poller:
                        for dev in device_poller.get_devices():
                            if dev.compile_target == target and dev.ip_address:
                                ota_address = (
                                    device_poller._address_overrides.get(dev.name)
                                    or dev.ip_address
                                )
                                break

                    run_id = str(_uuid.uuid4())
                    job = await queue.enqueue(
                        target=target,
                        esphome_version=version,
                        run_id=run_id,
                        timeout_seconds=cfg.job_timeout,
                        ota_address=ota_address,
                    )
                    if job is not None:
                        job.scheduled = True
                        logger.info(
                            "Schedule fired for %s (cron=%s): enqueued job %s (version=%s)",
                            target, cron_expr, job.id, version,
                        )

                    # Persist last_run. Re-read meta to avoid overwriting a
                    # concurrent user edit (small window, but safe).
                    fresh_meta = read_device_meta(cfg.config_dir, target)
                    fresh_meta["schedule_last_run"] = now.isoformat()
                    write_device_meta(cfg.config_dir, target, fresh_meta)

                except Exception:
                    logger.exception("Schedule check failed for %s", target)

        except Exception as e:
            app["schedule_checker_last_error"] = f"{type(e).__name__}: {e}"
            logger.exception("Error in schedule checker")


# ---------------------------------------------------------------------------
# ESPHome version detection and PyPI version list
# ---------------------------------------------------------------------------

_PYPI_CACHE_TTL = 3600  # seconds


async def _fetch_ha_esphome_version(session: aiohttp.ClientSession) -> Optional[str]:
    """Query the HA Supervisor for the installed ESPHome add-on version.

    Returns the version string, or None if not running inside an HA add-on or
    if the request fails for any reason.
    """
    import os  # noqa: PLC0415
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None

    # Two-tier discovery:
    #
    # 1. Preferred: list all installed add-ons via ``GET /addons`` and pick
    #    the ESPHome one. This works for any slug, including the hashed forms
    #    that confused the original hardcoded list. BUT it requires
    #    ``hassio_role: manager`` — plain ``hassio_api: true`` only grants
    #    access to ``/addons/<slug>/info``, and the listing returns 403.
    #    We do NOT escalate the role just for version detection; instead we
    #    silently fall back to step 2 on any non-200.
    #
    # 2. Fallback: probe a known list of slug patterns against
    #    ``/addons/<slug>/info``. This is the pre-1.3.1 mechanism plus the
    #    community-repo hash ``a0d7b954_esphome`` (added per bug #4 triage).
    #    It still misses fully-custom hashed slugs but covers ~all real
    #    installs without requiring an elevated role.
    auth = {"Authorization": f"Bearer {token}"}

    # --- Tier 1: listing
    listing_failed = False
    try:
        async with session.get(
            "http://supervisor/addons",
            headers=auth,
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                addons: list[dict] = data.get("data", {}).get("addons", []) or []

                def _is_esphome_addon(a: dict) -> bool:
                    slug = str(a.get("slug", "")).lower()
                    name = str(a.get("name", "")).lower()
                    if slug in ("core_esphome", "local_esphome") or slug.endswith("_esphome"):
                        return True
                    return name == "esphome" or name.startswith("esphome ")

                matches = [a for a in addons if _is_esphome_addon(a)]
                for addon in matches:
                    version = addon.get("version")
                    slug = addon.get("slug", "")
                    if version:
                        logger.debug(
                            "Detected HA ESPHome add-on version %s (slug: %s, via /addons listing)",
                            version, slug,
                        )
                        return str(version)
                # Listing succeeded but no match — try the fallback anyway in
                # case the name heuristic missed it.
                listing_failed = not matches
            else:
                # 403 is the common case (we don't have hassio_role: manager).
                # Drop to the per-slug fallback silently.
                listing_failed = True
    except Exception as exc:
        logger.debug("Supervisor /addons listing failed (%s); using slug fallback", exc)
        listing_failed = True

    if not listing_failed:
        # Listing worked but the matched add-ons had no ``version`` field —
        # fall through to the per-slug probe to fill it in.
        pass

    # --- Tier 2: per-slug probe over known patterns.
    candidate_slugs = (
        "core_esphome",
        "local_esphome",
        "a0d7b954_esphome",  # community repo (default for most users)
        "5c53de3b_esphome",  # alternate community repo hash
    )
    for slug in candidate_slugs:
        try:
            async with session.get(
                f"http://supervisor/addons/{slug}/info",
                headers=auth,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    info = await resp.json()
                    version = info.get("data", {}).get("version")
                    if version:
                        logger.debug(
                            "Detected HA ESPHome add-on version %s (slug: %s, via /info probe)",
                            version, slug,
                        )
                        return str(version)
                # 404 is the expected "not this slug" outcome — keep probing
                # silently. Anything else is unexpected but also not worth
                # spamming the log every 30s.
        except Exception as exc:
            logger.debug("Supervisor /addons/%s/info query failed: %s", slug, exc)

    return None


async def _fetch_pypi_versions(session: aiohttp.ClientSession, limit: int = 50) -> list[str]:
    """Return recent ESPHome versions from PyPI, newest first."""
    try:
        async with session.get(
            "https://pypi.org/pypi/esphome/json",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                releases = list(data.get("releases", {}).keys())

                def _version_key(v: str) -> list[int]:
                    return [int(x) for x in v.split(".") if x.isdigit()]

                releases.sort(key=_version_key, reverse=True)
                return releases[:limit]
    except Exception:
        logger.debug("Failed to fetch PyPI esphome versions", exc_info=True)
    return []


async def pypi_version_refresher(app: web.Application) -> None:
    """Background task: refresh PyPI versions hourly and re-check HA ESPHome add-on every 30s.

    Runs immediately on first iteration so that the HA Supervisor version and
    the PyPI version list are populated shortly after startup, without blocking
    the server startup path.
    """
    check_interval = 30   # check HA add-on version every 30 seconds
    pypi_countdown = 0    # fetch PyPI immediately on first loop
    first_run = True
    while True:
        # Run immediately on first iteration, then every 30s.
        # first_run is set to False before the try block so that a failure on
        # the first attempt still causes subsequent attempts to sleep.
        if not first_run:
            await asyncio.sleep(check_interval)
        first_run = False
        try:
            async with aiohttp.ClientSession() as session:
                # Re-check HA ESPHome add-on version
                new_detected = await _fetch_ha_esphome_version(session)
                old_detected = app.get("esphome_detected_version")
                if new_detected and new_detected != old_detected:
                    logger.info(
                        "ESPHome add-on version changed: %s → %s",
                        old_detected, new_detected,
                    )
                    app["esphome_detected_version"] = new_detected
                    # Auto-update selected version to match
                    from scanner import set_esphome_version  # noqa: PLC0415
                    set_esphome_version(new_detected)
                    logger.info("Auto-selected ESPHome %s (matches updated add-on)", new_detected)

                # Refresh PyPI list periodically
                pypi_countdown -= check_interval
                if pypi_countdown <= 0:
                    pypi_countdown = _PYPI_CACHE_TTL
                    versions = await _fetch_pypi_versions(session)
                    if versions:
                        app["esphome_available_versions"] = versions
                        app["esphome_versions_fetched_at"] = time.monotonic()
                        logger.info("Refreshed PyPI ESPHome version list: %d versions", len(versions))
        except Exception:
            logger.exception("Error in version refresher")


# ---------------------------------------------------------------------------
# Static file serving with ingress path injection
# ---------------------------------------------------------------------------

async def serve_index(request: web.Request) -> web.Response:
    """Serve index.html with X-Ingress-Path base href injection."""
    try:
        html = INDEX_HTML.read_text(encoding="utf-8")
    except FileNotFoundError:
        return web.Response(status=404, text="index.html not found")

    from constants import HEADER_X_INGRESS_PATH  # noqa: PLC0415
    ingress_path = request.headers.get(HEADER_X_INGRESS_PATH, "")
    if ingress_path:
        # Ensure trailing slash for base href
        if not ingress_path.endswith("/"):
            ingress_path += "/"
        html = html.replace(
            '<base href="./">',
            f'<base href="{ingress_path}">',
        )

    return web.Response(
        text=html,
        content_type="text/html",
        charset="utf-8",
    )


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> web.Application:
    cfg = AppConfig.load()

    queue = JobQueue()
    queue.load()

    registry = WorkerRegistry()

    device_poller = DevicePoller(poll_interval=cfg.device_poll_interval)

    app = web.Application(middlewares=[security_headers_middleware, version_header_middleware, auth_middleware])
    app["config"] = cfg
    app["queue"] = queue
    app["registry"] = registry
    app["scanner_config_dir"] = cfg.config_dir
    app["device_poller"] = device_poller
    app["log_subscribers"] = {}

    # Register routes
    app.router.add_routes(api_module.routes)
    app.router.add_routes(ui_api_module.routes)

    # Static file routes
    app.router.add_get("/", serve_index)
    app.router.add_get("/index.html", serve_index)
    if STATIC_DIR.is_dir():
        app.router.add_static("/static/", path=str(STATIC_DIR), name="static")
        # Serve Vite-built assets at /assets/ (referenced by base-relative URLs in index.html)
        assets_dir = STATIC_DIR / "assets"
        if assets_dir.is_dir():
            app.router.add_static("/assets/", path=str(assets_dir), name="assets")

    # ESPHome version state — populated during startup
    app["esphome_detected_version"] = None   # version from HA Supervisor (or None)
    app["esphome_available_versions"] = []   # list of versions from PyPI
    app["esphome_versions_fetched_at"] = 0.0

    # HA entity status — populated by ha_entity_poller background task
    # dict[str, {"configured": bool, "connected": bool | None}]
    app["ha_entity_status"] = {}

    # Startup/shutdown hooks
    async def on_startup(app: web.Application) -> None:
        logger.info("Starting ESPHome Distributed Build Server")
        logger.info("Config dir: %s", cfg.config_dir)
        logger.info("Token configured: %s", bool(cfg.token))

        # Use the locally installed ESPHome package version as the initial
        # active version.  The pypi_version_refresher background task will
        # contact the HA Supervisor API shortly after startup and update the
        # version if it detects a different version in the ESPHome add-on.
        # Doing this at startup (instead of blocking on the Supervisor API
        # here) avoids a 10–15 s startup delay when the Supervisor is slow
        # or the hassio_api permission is not yet granted, which previously
        # caused the web server to refuse connections during that window.
        from scanner import (  # noqa: PLC0415
            scan_configs, build_name_to_target_map,
            set_esphome_version, _get_installed_esphome_version,
        )

        selected = _get_installed_esphome_version()
        set_esphome_version(selected)
        logger.info("Active ESPHome version: %s (background task will refine from HA Supervisor)", selected)

        # Update device poller with known targets
        targets = scan_configs(cfg.config_dir)
        name_map, enc_keys, addr_overrides, addr_sources = build_name_to_target_map(cfg.config_dir, targets)
        device_poller.update_compile_targets(targets, name_map, enc_keys, addr_overrides, addr_sources)

        # Start device poller
        await device_poller.start(app)

        # Start background tasks
        app["timeout_checker_task"] = asyncio.create_task(timeout_checker(app))
        app["config_scanner_task"] = asyncio.create_task(config_scanner(app))
        app["pypi_version_refresher_task"] = asyncio.create_task(pypi_version_refresher(app))
        app["ha_entity_poller_task"] = asyncio.create_task(ha_entity_poller(app))
        app["schedule_checker_task"] = asyncio.create_task(schedule_checker(app))

        # Start local worker if client code is bundled
        local_worker_script = Path("/app/client/client.py")
        if local_worker_script.exists():
            import subprocess as sp  # noqa: PLC0415
            # Restore persisted slot count (default 0 on first run)
            local_slots_file = Path("/data/local_worker_slots")
            local_slots = "0"
            try:
                if local_slots_file.exists():
                    local_slots = local_slots_file.read_text().strip() or "0"
            except Exception:
                pass
            local_env = {
                **os.environ,
                "SERVER_URL": f"http://127.0.0.1:{cfg.port}",
                "SERVER_TOKEN": cfg.token,
                "MAX_PARALLEL_JOBS": local_slots,
                "ESPHOME_VERSIONS_DIR": "/data/esphome-versions",
                "HOSTNAME": "local-worker",
            }
            proc = sp.Popen(
                [sys.executable, str(local_worker_script)],
                env=local_env,
                stdout=sp.DEVNULL,
                stderr=sp.DEVNULL,
            )
            app["local_worker_proc"] = proc
            logger.info("Started local worker (PID %d, %s slots)", proc.pid, local_slots)

    async def on_shutdown(app: web.Application) -> None:
        logger.info("Shutting down ESPHome Distributed Build Server")

        # Stop local worker
        proc = app.get("local_worker_proc")
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            logger.info("Local worker stopped")

        for task_name in ("timeout_checker_task", "config_scanner_task", "pypi_version_refresher_task", "ha_entity_poller_task", "schedule_checker_task"):
            task = app.get(task_name)
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await device_poller.stop()

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    return app


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cfg = AppConfig.load()
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=cfg.port)
