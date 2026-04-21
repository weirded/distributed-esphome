# External Review — `heffneil/esphome-enhanced-dashboard`

**Review type:** Feature-gap analysis against an adjacent project.
**Date:** 2026-04-21.
**Sources:**
- https://github.com/heffneil/esphome-enhanced-dashboard-addon (HA add-on wrapper)
- https://github.com/heffneil/esphome-enhanced-dashboard (the overlay itself)
- Local clones at `/tmp/heffneil-addon` and `/tmp/heffneil-dashboard`.

**Scope:** Identify features heffneil has that we don't, ranked by novelty. Skip anything that's just cosmetic styling of something we already do equivalently.

---

## Overall impression

heffneil's project is much narrower than ours: a six-file overlay (`const.py`, `core.py`, `models.py`, `web_server.py`, `status/ping.py`, one 1667-line self-contained HTML template) that `COPY`s over the stock ESPHome dashboard files inside the `esphome/esphome:latest` Docker image. Every backend capability — compile, OTA, PlatformIO, mDNS discovery, `api/v1/*` routes — is stock ESPHome. The project's value is **entirely in the UX of the single device list**: replaces the card grid with a compact, sortable, searchable table-style UI plus a right-side panel for per-device actions.

Target audience: someone with 10–60 devices on one host who found the card grid unwieldy. In exchange for scope, heffneil delivers several thoughtful per-device features we haven't built (Install to Specific Address, Ping Device, Mark Inactive, tag pool) and a few UX patterns worth lifting (side panel, floating batch bar, tag filter pills with counts).

**What's NOT a gap:** he has no distributed workers, no version pinning per device, no scheduled upgrades, no job queue, no archive viewer, no real-compile CI, no worker registry, no Home Assistant Supervisor integration beyond the basic add-on wrapper, no git-based YAML versioning. Everything we built beyond "a better device list" is unique to us.

---

## Important correction: the `ignored_devices` feature

My initial report listed "ignore device" as a heffneil feature. **It is not.** It's stock ESPHome (verified against `esphome==2026.3.3` locally):

- `storage_json.py:31` — `ignored_devices_storage_path()` → `/data/ignored-devices.json`
- `dashboard/core.py:102, 110-126` — `dashboard.ignored_devices: set[str]`, `load_ignored_devices`, `save_ignored_devices`
- `dashboard/web_server.py:933-968` — `IgnoreDeviceRequestHandler`, route wired at `:1599` as `/ignore-device`

The feature only applies to **importable** devices (mDNS-discovered devices with `package_import_url` and no local YAML). Stock ESPHome Builder 2026.4.x renders the ignore control only when at least one importable device is present — so a fleet with no importable devices never sees the UI control. The visible UI lives in the separate `@esphome/dashboard` frontend repo (https://github.com/esphome/dashboard), not in the Python package.

**Implication for us:** if/when we build device adoption (WORKITEMS-1.8 §2.4), we get `ignored_devices` essentially for free by calling the upstream handlers. Don't reinvent.

---

## Tags: how heffneil stores them

Worth calling out because it's the opposite of our approach:

- **Storage:** `/data/device-tags.json`, shape `{"tags": {<device>: [<tag>, ...]}}`.
- **In-memory:** `dashboard.device_tags: dict[str, list[str]]`, keyed by device name (YAML filename stem).
- **Lifecycle:** loaded at boot (`core.py:141-148`), saved on every mutation (`core.py:150-157`).
- **Rename/archive paths** explicitly keep the JSON in sync.

**Trade-offs vs our YAML-comment tags:**

| | Heffneil (sidecar JSON) | Ours (YAML comments) |
|---|---|---|
| Edit touches user YAML | No | Yes (git churn) |
| Survives config migration/copy | No (tags left behind) | Yes |
| Risk of mangling YAML | None | Non-zero (regex parse, PY-1) |
| Tag pool lookup | Single dict union | Scan every YAML |

His complete custom persistence layer is only **two files**: `device-tags.json` and `inactive-devices.json`. Everything else (`ignored-devices.json`, per-device `StorageJSON`, comments, platform, address, `loaded_integrations`, `esphome_version`, `friendly_name`) comes from stock ESPHome.

---

## ★★★ Substantial gaps — genuine features worth considering

### 1. Side panel as the primary per-device action surface
Clicking a device row slides a right-side panel in with **every** per-device action (Install, Install to Address, Edit, Validate, Compile, Logs, Visit, Show API Key, Mark Inactive, Archive) plus a Utilities section (Ping, Clean Build, Clean MQTT), and shows rich device info (status, IP, platform, version, comment, tags) alongside. Scales far better than our hamburger dropdown when the action count grows.
**Source:** `template:489-510` (markup), `:766-847` (openPanel).
**Our equivalent:** `DeviceContextMenu.tsx` hamburger — same actions, but squeezed into a popover with no room for context.

### 2. Install to Specific Address
Modal prompts for any IP/hostname, validated against `^[a-zA-Z0-9.\-_:]+$`, then runs `esphome run --device <addr>`. Confirmation warning if the address differs from the known one. Use cases: device moved to a new IP, flashing a spare board with a known config, recovery after a failed rename.
**Source:** `template:1360-1383`.
**Our equivalent:** None. We always use the address from the YAML / mDNS.

### 3. Ping Device diagnostic
Side-panel button opens a modal, calls `POST /ping-host`, which uses `icmplib.async_ping` and returns `is_alive`, `packets_sent/received`, `packet_loss`, `min/avg/max RTT`, `jitter`. Monospace table output. Answers "is it packet loss, DNS, or just offline?" in one click.
**Source:** `web_server.py:1052-1163` (`PingHostHandler`); `template:1460-1510`.
**Our equivalent:** None. We know online/offline via mDNS + aioesphomeapi, but no latency/loss diagnostic.

### 4. Mark Inactive
Per-device toggle. Inactive devices dim to 40% opacity, sort to the bottom of the list (above archived), and the ping loop **skips** polling them. Distinct from Archive — the config stays, the device stays visible, just doesn't churn the status UI. Fits our "disable, don't fail" design principle.
**Source:** `core.py:159-181` (storage), `web_server.py:1024-1049` (handler), `status/ping.py` (skip logic).
**Our equivalent:** None. We always poll; a known-unplugged battery device shows offline forever.
**Storage note:** sidecar JSON at `/data/inactive-devices.json` — trivial to replicate.

### 5. New Device wizard with platform picker
Two-step dialog: name → platform list (ESP32 / C3 / C6 / S2 / S3 / 8266 / RP2040-PicoW / BK72xx / LN882x / RTL87xx) with a default board per platform. Backend uses `esphome.wizard` to auto-generate API encryption key + OTA password, writes a stub YAML with `!secret wifi_ssid` / `!secret wifi_password`, then shows the generated key in a copy-on-select box and an "Install" button that kicks off the compile immediately.
**Source:** `web_server.py:803-890` (`WizardRequestHandler`); `template:1241-1358`.
**Our equivalent:** `NewDeviceModal.tsx` — filename-only, no platform, no secrets scaffolding, no encryption key generation. Significantly weaker.

### 6. Device adoption / import (already scheduled in 1.8)
ESPHome's `importable` device list — mDNS-discovered devices with `package_import_url` but no local YAML — surfaced as a dedicated section with "Import" and "Ignore" buttons. Import synthesizes local YAML with `!include <url>` + `api.encryption.key`. This is the core "flash-once, adopt-via-mDNS, never-touch-USB-again" ESPHome story.
**Source:** `web_server.py:893-986` (heffneil's version — but most of it is stock).
**Our status:** listed in `WORKITEMS-1.8.md:33` as §2.4. **Most of the backend is stock ESPHome** — we mostly need to expose the UI + wire `POST /import-device`, `POST /ignore-device` to the dashboard entries API we already have.

---

## ★★ Meaningful polish

### UI/UX
- **User-facing column show/hide** — `☰` button in topbar opens column-visibility menu; saved to localStorage. Our TanStack Table has the capability but no user control. `template:897-938`.
- **Tag filter pills with counts** — always-visible bar below topbar, one button per tag with `(N)` count, OR-logic on click, "All" clears. Faster than search-box typing. `template:673-685`.
- **Tag pool in editor** — when editing a device's tags, a panel below the input shows every tag that exists elsewhere as clickable pills (dimmed if already applied). Prevents "basement" vs "Basement" typos. `template:1541-1577`.
- **Batch selection with floating action bar** — "N selected" bar appears when rows are checked; indeterminate checkbox in header. Makes bulk a visible mode, not a checkbox dance. `template:1067-1237`.
- **Batch progress modal + per-device summary** — single modal tails the current compile, auto-advances when it detects `successfully uploaded`/`OTA successful` in the log, ends with a success/failure summary dialog. Auto-advance heuristic is clever given `esphome run` never self-exits. `template:1153-1237`.
- **Inline collapsible Archived section** — `▶ Archived [N]` at bottom of the main table; expand inline, 45% opacity rows. Keeps archive one click away vs navigating to a separate view. `template:410-416, 701-707`.
- **BT Proxy column** — ✓ for devices whose `loaded_integrations` contains `bluetooth_proxy`. Hideable, sortable. Answers "which devices are proxying?" instantly. Generalizable: one column per relevant integration (`api`, `mqtt`, `web_server`, `bluetooth_proxy`). `template:82-86, 474, 654-656`.
- **Download Logs button in command modal** — client-side blob download of current log buffer as `<device>-logs.txt`. Easy to add, handy for pasting into bug reports. `template:971, 1385-1393`.
- **`+ add` affordance on empty tags cell** — teaches the feature instead of showing blank space. `template:664-667`.

### Compile / Build
- **`clean-mqtt` per-device** — removes MQTT discovery entries from broker. Runs `esphome clean-mqtt <config>`. Niche but 20-line wrapper. `web_server.py:499-503`.
- **Per-device `clean` (build cache nuke)** — runs `esphome clean <config>`. Our existing "Clean" is worker-wide — hostile when only one target is misbehaving. `web_server.py:513-516`.
- **Install (Upload OTA only) — skip compile** — runs `esphome upload` against the last-built binary. 5s recovery after a hiccupped OTA vs ~95s full rebuild. We already persist firmware in the job archive, so wiring this up is mostly a UI + one-endpoint change. `web_server.py:468-471`.
- **`--mdns-address-cache` / `--dns-address-cache` CLI flags** — server pre-resolves host → IP and passes it to the ESPHome CLI, eliminating a 2–10s resolve stall per OTA. `web_server.py:340-404`.

### Integrations
- **Prometheus file-SD endpoint (`/prometheus-sd`)** — returns scrape targets in Prometheus file-SD JSON for every `web_server`-enabled device, with labels for platform/version/integrations. Single URL wires a whole fleet into Grafana. `web_server.py:1371-1397`.
- **`/json-config` — fully-resolved config as JSON** — after secrets, `!include`, packages. Unlocks scripting ("which devices have a temperature sensor?", "list all GPIOs in use"). `web_server.py:1681-1702`.
- **MQTT-based ping status (`status_use_mqtt`)** — option to use the MQTT online topic as truth instead of ICMP. Matters on VLAN-split networks. `core.py:208-212`.

### Device Management
- **Archive reclaims build directory** — `shutil.rmtree(build_path, ignore_errors=True)` on archive. Verify we do this; if not, we leak ~100 MB per archive. `web_server.py:1533-1552`.

### Configuration
- **`backup_exclude: ['*/*/']` on add-on config** — excludes build/cache dirs from HA snapshots. Worth verifying ours. `config.yaml:38-39`.

### Monitoring
- **WebSocket event bus with reference-counted sleep** — a single `/events` channel publishes typed events (`entry_state_changed`, `entry_added/removed/updated`, `importable_device_added/removed`, `entry_archived/unarchived`, `initial_state`); the background poll loop only runs while ≥1 subscriber is connected. Matches our "idle is the default state" doctrine. Worth confirming our `/ui/api/ws/events` does reference-counted sleep. `web_server.py:542-780`, `const.py:8-25`.

---

## ★ Minor / already have / N/A

- Classic dashboard fallback at `/classic` — unique to their overlay architecture; N/A for us.
- `streamer_mode` — we already have it.
- "Show API Key" reveal — we have Copy API Key, equivalent.
- ANSI color log streaming — we have full ANSI via xterm.js.
- `POST /rename` — we already have it (`/ui/api/targets/{filename}/rename`).
- `/secret_keys` — we already have it (`/ui/api/secret-keys`).
- Esc / backdrop-click dismissal — shadcn dialogs handle this.
- `--only-generate` compile flag — very niche (ESPHome → VSCode flow).
- Direct-port HTTPS — N/A for ingress-first architecture.
- Serial-port listing — N/A for distributed-worker architecture (workers don't share USB with user).
- Dashboard DNS cache — low priority, distributed workers do their own resolution.
- "Update to X" inline label — copywriting polish.
- "Visit Device" panel button — we already link IP cell when `has_web_server`.
- `ignored_devices` — **stock ESPHome, not heffneil's** (see correction above).

---

## Recommended follow-up

Do not pull any of this into a scheduled release without explicit approval (per CLAUDE.md "Never reshuffle workitems between releases without an explicit ask"). The table below is a **suggestion surface**, not a plan.

| Candidate | Bucket | Rough effort | Rationale |
|---|---|---|---|
| Side panel for per-device actions | 1.8 or 1.9 | L | Changes core UX pattern; unlocks 4–5 other ★★★ items by giving them a home |
| Install to Specific Address | 1.8 | S | Real recovery workflow; one modal + CLI flag pass-through |
| Ping Device diagnostic | 1.8 | S | `icmplib` dep + one endpoint + one modal |
| Mark Inactive | 1.8 | S | Sidecar JSON + one column state + skip in poller |
| New Device wizard with platforms | 1.8 | M | Wraps `esphome.wizard`; big UX win for onboarding |
| Device adoption / import | 1.8 | M | Already §2.4 in WORKITEMS-1.8; stock backend, just UI |
| Tag filter pills + tag pool | 1.9 | S | Copies cleanly into Devices tab |
| Floating batch action bar | 1.9 | S | Upgrade on top of existing bulk-select |
| Archive reclaims build dir | Bug | XS | One-liner verification; file a bug if missing |
| `backup_exclude` on add-on config | Bug | XS | Verify current config; file a bug if missing |
| Column show/hide menu | 1.9 | S | TanStack supports it; add a menu |
| Install (Upload OTA only) | 1.9 | S | We already have the binaries in job archive |
| BT Proxy column | 1.9 | XS | Read `loaded_integrations`, add one column |
| Download logs button | 1.9 | XS | Blob download from existing xterm buffer |
| Prometheus SD endpoint | Future | S | Niche but high-leverage for the subset of users who run Grafana |
| MQTT-based ping | Future | M | Only matters if a user asks |
| `/json-config` endpoint | Future | XS | Useful for scripting; low demand signal |

---

## Files to reference when building

Everything below is in the cloned repo at `/tmp/heffneil-dashboard/overrides/` (may be garbage-collected — clone again from https://github.com/heffneil/esphome-enhanced-dashboard if needed).

- Side panel: `templates/index.template.html:489-510, 766-847`
- Ping backend: `web_server.py:1052-1163`
- Install-to-address: `templates/index.template.html:1360-1383`
- Mark Inactive: `core.py:159-181`, `web_server.py:1024-1049`, `status/ping.py:58-71`
- Wizard: `web_server.py:803-890`, `templates/index.template.html:1241-1358`
- Importable / adopt (stock-backed): `web_server.py:893-986`, `models.py:18-28, 68-80`
- Tags storage: `core.py:106, 135-157`
- Tag pool UI: `templates/index.template.html:1541-1577`
- Batch sequential runner: `templates/index.template.html:1067-1237`
- Clean MQTT: `web_server.py:499-503`
- DNS/mDNS cache → CLI flags: `web_server.py:340-404`
- Prometheus SD: `web_server.py:1371-1397`
- `/json-config`: `web_server.py:1681-1702`
- WebSocket event bus (ref-counted): `web_server.py:542-780`
- Archive build-dir cleanup: `web_server.py:1533-1552`
- Event enum: `const.py:8-25`
