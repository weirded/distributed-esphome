# HA-Coupling Audit — SI.1 (1.6.2)

Audit of every `ha-addon/server/` site that reads HA-specific inputs, classified by how it behaves when Home Assistant is absent (standalone Docker Compose deployment). Produced for SI.1 from `WORKITEMS-1.6.2.md`; input to SI.2's implementation scope.

**Buckets**
- **[A] graceful** — indistinguishable from an HA-absent or HA-present run; no diagnostic needed.
- **[B] degrades cleanly** — feature is disabled or falls back, logs a WARNING/INFO naming the skip, server keeps running.
- **[C] hard failure** — crashes, hangs, or produces an error the user can't diagnose without reading source.

**TL;DR.** 14 distinct HA-coupled sites audited. **13 are [A] or [B]** — the server is already well-designed for standalone; `#83` (HTML 401 page + `require_ha_auth=false` default) closed the last previously-known hard-block for the Web UI. **One borderline [C]** around the device-restart HA fallback response code, plus **three diagnostic-quality polish items** classified B worth tightening in SI.2. The workitem's original concern ("silent no-ops confuse operators") is the real shape of the remaining work — it's log-message polish + a `HA_MODE` label + docs, not broken paths.

---

## Audit by function

### Auth + Ingress

**[A] `ha_auth.ha_auth_middleware` path 1 — Supervisor peer-IP trust.** `ha_auth.py:312–324`. Trusts requests from `HA_SUPERVISOR_IP` (`172.30.32.2`, Docker-internal). In standalone Docker the browser arrives from the host network; path 1 never matches and the request falls through. No diagnostic needed. The IP constant is RFC1918 inside HA's private `hassio` bridge — a standalone operator would have to stand up their own `172.30.32.0/23` bridge AND put a hostile container on `.2` to spoof this; well out of scope for a "standalone hardening" pass.

**[A] `ha_auth._validate_bearer_with_supervisor` — path 3 bearer validation.** `ha_auth.py:248–296`. Returns `None` when `SUPERVISOR_TOKEN` is absent (line 260). Middleware then falls through to path 4. In standalone Docker, path 4's default is `require_ha_auth=false` (flipped back to off in `#83` 1.6.2-dev.6), so the request is served without a bearer. Previously a [C] (hard 401 block before `#83`), closed.

**[A] `main.serve_index` — `X-Ingress-Path` header injection.** `main.py:1222–1260`. Rewrites the React SPA's `<base href>` when the header is present (HA Ingress); returns the HTML unchanged otherwise (`href="./"` default works for direct-port access). Model implementation of "optional HA feature" handling.

### ESPHome version detection + install

**[B] `main._fetch_ha_esphome_version` — query Supervisor for HA's ESPHome add-on version.** `main.py:993–1049`, called from `pypi_version_refresher()` (line 1163+). Returns `None` silently when no `SUPERVISOR_TOKEN` (line 1001). Caller falls back to PyPI's latest-stable (line 1204+, bug #30 fallback). **Polish opportunity:** the no-token path is DEBUG-only; an INFO line on first pass saying "Standalone mode — ESPHome version source: PyPI" would help standalone operators diagnose why their version dropdown differs from an HA install's.

**[B] `scanner.ensure_esphome_installed` + `main._install_esphome_background`.** `main.py:1422–1508`. Multi-tier fallback is explicit and well-commented (bundled → Supervisor-detected → PyPI-latest). Bug #30 is the documented standalone path. Working as designed.

### Options / settings

**[B] `settings._read_supervisor_options` — seed settings.json from Supervisor.** `settings.py:408–452`. SP.8 one-shot migration reading Supervisor's `/addons/self/info` options on first boot. Returns `{}` without `SUPERVISOR_TOKEN` (line 428), falling back to `/data/options.json` or defaults. Logs WARNING on first failure then DEBUG. Working as designed.

**[B] `settings.clear_supervisor_options_if_needed` — clear stale Supervisor options cache.** `settings.py:345–395`. Retries every boot in standalone because the marker file is keyed off a successful Supervisor call; on standalone the marker never writes so the call retries forever. Retry is cheap (one no-op POST every boot that fails at connect), but it's ~one extra network exception in the log every restart. **Polish opportunity:** gate on `SUPERVISOR_TOKEN` presence before attempting and write the marker in that branch too, so standalone boots log zero network exceptions from this path.

### Supervisor discovery

**[B] `supervisor_discovery.register_discovery` — announce ourselves to HA.** `supervisor_discovery.py:43–86` + `main.py:1535–1547`. Silent no-op when `SUPERVISOR_TOKEN` absent. The feature (auto-discovery of our custom integration from the HA sidebar) is simply unavailable in standalone — not broken, just not applicable. **Polish opportunity:** the "skipping — no SUPERVISOR_TOKEN" path logs DEBUG; INFO would be more honest for operators who wonder why HA didn't auto-discover.

**[B] `supervisor_discovery.unregister_discovery` — shutdown cleanup.** `supervisor_discovery.py:89–109` + `main.py:1637–1644`. Symmetric no-op. Edge case flagged by the Explore pass (stale UUID if HA comes and goes) is not reachable in standalone (never registered → nothing to leak); only real failure mode is "HA was online at register time, offline at unregister time" which is on the HA side, not ours. No change needed.

### HA entity poller

**[B] `main.ha_entity_poller` — poll HA's entity registry for ESPHome connectivity.** `main.py:414–700`. Returns early with a clear `INFO: No SUPERVISOR_TOKEN — HA entity status polling disabled` when the token is absent (line 426–428). **Not a spinloop in standalone** — the agent's initial audit was wrong about this; the `while True` only runs if the token-presence check passes. When the token *is* present but HA Core is temporarily down, the loop's built-in warning-demotion (repeat-count → DEBUG after 2 identical failures, `main.py:440–453`) already keeps the log quiet. No polish needed.

### HA Core WebSocket client

**[A] (no such thing).** Despite the workitem listing this as a known candidate, the server does not open a WebSocket to HA Core today. The WebSocket that does exist is server-side for browser/worker clients on `/ui/api/*/log/ws`, not an outbound connection to HA. Striking this from the audit list.

### Custom-integration installer

**[B] `main.install_integration` (via `integration_installer.py`).** `integration_installer.py:102–210`. Copies the custom integration to `/config/custom_components/esphome_fleet/` at boot. Returns `"skipped_no_parent"` when `/config/custom_components/` can't be created (line 150). Logs WARNING. Server continues. Documented exit code. In standalone Docker — assuming the user didn't mount `/config` — this path skips cleanly and the user never sees the HA integration anyway (no HA to install it into). Working as designed.

### Device actions

**[B → polish target] `ui_api.restart_device` — HA fallback after native API failure.** `ui_api.py:2515–2570`. The native-API path is independent of HA and works standalone. The HA fallback (called only when native fails) returns HTTP **500** with a structured body `{"error": "...", "native_api_error": ..., "ha_fallback_error": "no SUPERVISOR_TOKEN", "candidates_tried": []}` when `SUPERVISOR_TOKEN` is absent. The response body *is* diagnostic — operators who look at the JSON see exactly why — but the status code signals "server error" when the accurate signal is "feature unavailable." **Polish opportunity for SI.2:** change the status to **503 Service Unavailable** with the same structured body; semantic match + clearer signal in the UI and to any tooling that treats 5xx as "server broken."

### mDNS advertiser

**[A] `mdns_advertiser`.** `mdns_advertiser.py:36–133` + `main.py:1523–1533`. Standard zeroconf, not HA-specific. `_primary_ipv4()` falls back to skipping advertisement + WARNING if no outbound interface resolves. HA-independent; fine in both modes.

### Local build worker

**[A] `main` local-worker spawn.** `main.py:1599–1607`. Env-configured subprocess; no HA assumption. Any failure is diagnosable from the subprocess's own logs.

---

## SI.2 scope (actionable items)

Based on the audit, SI.2 is a small polish pass, not a rewrite:

1. **Add `HA_MODE` detection + log banner at boot.** Look at `SUPERVISOR_TOKEN` env var plus `/run/s6` or similar Supervisor markers; log one INFO line at startup — `"Running in standalone mode (no HA Supervisor detected)"` or `"Running as HA add-on"` — so operators grep one place instead of reading nine coupling sites. Optional env override: `HA_MODE=standalone` / `HA_MODE=addon` for misdetected environments (e.g. HA running the add-on without its normal token).

2. **Promote "skipped — no SUPERVISOR_TOKEN" logs to INFO** in: `supervisor_discovery.register_discovery`, `supervisor_discovery.unregister_discovery`, and `main._fetch_ha_esphome_version` (first call only). One-line INFO per site, naming the feature that's unavailable. Cost: ~5 LOC total.

3. **Skip `settings.clear_supervisor_options_if_needed` entirely when `SUPERVISOR_TOKEN` is absent**, and write the marker in that branch too so standalone boots aren't retrying + swallowing the network exception on every startup. Cost: ~5 LOC.

4. **`ui_api.restart_device` HA-fallback response: 500 → 503.** Same body, new status code + a top-level `"hint"` string clarifying this path requires HA. Cost: 2 LOC + 1 test update.

5. **No changes needed** to: auth middleware paths, Ingress-path injection, entity poller, custom-integration installer, lazy ESPHome install, options probe, mDNS advertiser. All already graceful.

Total code change for SI.2: ~30 LOC, one new `_ha_mode()` helper in `main.py` or `settings.py`, three log-level bumps, one status-code change. No new settings knob beyond the optional `HA_MODE` env var.

## SI.3 scope

`README.md` gains a "Running standalone" section that lists the SI.2-audited feature matrix:

- **Works without HA** (full feature): compile queue, workers, device poller, mDNS discovery, live device logs, OTA, firmware archive, git versioning, config editor, scheduled upgrades, settings drawer, Web UI.
- **Unavailable in standalone**: HA auto-discovery of the custom integration (obviously), HA-entity-driven device-connectivity column in Devices tab, HA-fallback Restart button, Supervisor-driven ESPHome version auto-detection (server falls back to PyPI latest-stable).
- **Configuration differences**: `/data/settings.json` instead of Supervisor options; `HA_MODE=standalone` optional override; `require_ha_auth=false` default (on-toggle available in Settings drawer for exposed deployments).

Points at `docker-compose.yml` for deployment, `#83`'s HTML 401 page for first-touch UX when auth is enabled.

## Known non-findings (deliberately audited + left alone)

- The `172.30.32.2` Supervisor peer-IP trust. Only a footgun in contrived attacker-controlled Docker networks; default posture is fine.
- The HA custom integration installer in standalone — `"skipped_no_parent"` is the right outcome; user has no HA to install into.
- The lazy ESPHome install's fallback to PyPI — the documented (bug #30) standalone behavior, tested, works.
- The `/data/options.json` loader — already falls through to defaults if absent.
