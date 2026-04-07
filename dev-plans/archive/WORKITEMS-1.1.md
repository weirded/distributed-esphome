# Work Items — 1.1.0

Major update: React UI rewrite, ESPHome dashboard-grade features, Home Assistant integration.

## React UI Rewrite

- [x] Complete rewrite from vanilla JS to React + Vite + TypeScript
- [x] Port existing UI to React components (Devices, Queue, Workers tabs)
- [x] Port all modals (Log, Editor, Connect Worker)
- [x] Port polling, WebSocket log streaming, toast notifications
- [x] **1.1a–d Monaco YAML autocomplete** — ESPHome schema (697 components from installed package), per-component config var suggestions from schema.esphome.io, `!include`/`!secret`/`!lambda` support, inline syntax validation
- [x] **1.3 Secrets editor** — "Secrets" button in header opens secrets.yaml in Monaco editor
- [x] **6.1 Device search/filter bar** — client-side filter across all columns
- [x] **6.2 Dark/light theme toggle** — CSS variables for both themes, persist in localStorage
- [x] **6.4 Export logs** — download button in log modal saves terminal content as .txt

## Device Lifecycle

- [x] **2.2 Rename device** — `POST /ui/api/targets/{f}/rename`, updates esphome.name + filename, triggers compile+OTA to flash new name
- [x] **2.3 Delete device** — `DELETE /ui/api/targets/{f}` with archive (`.archive/`) or permanent delete, confirmation dialog
- [x] Restart device via native ESPHome API (aioesphomeapi `button_command`) with HA REST fallback

## Live Device Logs

- [x] **4.1a–c Live device logs** — WebSocket endpoint, encryption (noise_psk) handling, DeviceLogModal with xterm.js
- [x] Boot log included (`dump_config=True`)
- [x] Timestamps on each log line `[HH:MM:SS]`
- [x] Full ANSI color support

## Compile Improvements

- [x] Switched to `esphome run --no-logs` (single process compile+OTA, matches native ESPHome UI)
- [x] Colorized compile logs: INFO=green, WARNING=yellow, ERROR=red
- [x] OTA retry with 5s delay on failure (keeps job in WORKING state for proper re-queuing)
- [x] Server timezone passed to workers (prevents config_hash mismatch and unnecessary clean rebuilds)
- [x] OTA always uses explicit `--device` with known IP address
- [x] ESPHome install errors visible in streaming job log

## Home Assistant Integration

- [x] **4.2a–c HA integration** — background poller detects ESPHome devices via template API + /api/states
- [x] MAC-based device matching (queries HA device connections) — most reliable method
- [x] Name-based fallback: friendly_name, esphome.name, filename stem, MAC fragment matching
- [x] HA column in Devices tab shows configured status (Yes/—)
- [x] HA connectivity (`_status` binary_sensor) feeds into online/offline column
- [x] Device restart via HA REST API as fallback when native API unavailable

## Config Validation

- [x] **1.2a–c Config validation** — server endpoint, `validate_only` job type, Validate button in editor
- [x] Validate button saves editor content first, then runs `esphome config`
- [x] Validation opens streaming log modal directly (no toast intermediary)
- [x] Badge shows Validating/Valid/Failed status in queue

## Performance

- [x] Concurrent device polling via `asyncio.gather` (all devices checked in parallel)
- [x] HA entity poller runs immediately on startup (no 30s delay)
- [x] Config resolution caches git clones (`skip_update=True` after first resolution)
- [x] PyPI version list increased from 10 to 50

## UI Polish

- [x] **4.3 Device web server links** — make IP clickable when device has `web_server` and is online
- [x] **4.4 Show API encryption key** — copy-to-clipboard button per device
- [x] Per-row Clear button in queue tab
- [x] Edit buttons in queue rows and log modal header
- [x] Hamburger menu redesigned: vertical ellipsis icon, plain text styling
- [x] Live Logs and Restart moved to hamburger menu (never grayed out)
- [x] Light mode: dark header for ESPHome logo readability, themed form inputs
- [x] "Checking..." state with pulsing dot on startup (instead of showing offline)
- [x] Copy API Key, Rename, Delete in device hamburger menu

## Operations

- [x] Suppressed `aioesphomeapi.connection` warnings (expected when devices offline)
- [x] ESPHome add-on version detection at DEBUG level (no log spam)
- [x] Debug endpoint `GET /ui/api/debug/ha-status` for HA matching troubleshooting
- [x] Queue remove-by-ID endpoint for per-job clearing

---

## Bug Fixes (1–89)

<details>
<summary>Expand 89 bug fixes from 1.1.0</summary>

- [x] **#1** *(1.1.0-dev.4)* — In the queue, we aren't correctly handling some of the states.
- [x] **#2** *(1.1.0-dev.4)* — Colors - Upgrade Outdated should be green.
- [x] **#3** *(1.1.0-dev.4)* — Button states for disabled buttons.
- [x] **#4** *(1.1.0-dev.6)* — Disabled button styling inconsistent.
- [x] **#5** *(1.1.0-dev.6)* — API key option in hamburger menu.
- [x] **#6** *(1.1.0-dev.6)* — IP address link styling.
- [x] **#7** *(1.1.0-dev.6)* — Only link IP if web_server configured.
- [x] **#8** *(1.1.0-dev.7)* — PowerShell docker command.
- [x] **#9** *(1.1.0-dev.7)* — Button disabled mechanics.
- [x] **#10** *(1.1.0-dev.7)* — Sortable table columns.
- [x] **#11** *(1.1.0-dev.7)* — Workers tab alphabetical sort.
- [x] **#12** *(1.1.0-dev.7)* — Queue entry time instead of ID.
- [x] **#13** *(1.1.0-dev.7)* — Singular/plural toast messages.
- [x] **#14** *(1.1.0-dev.8)* — Duplicate device when filename != esphome.name.
- [x] **#15** *(1.1.0-dev.8)* — Disabled buttons + header pill styling.
- [x] **#16** *(1.1.0-dev.11)* — Toast "0 jobs" messages.
- [x] **#17** *(1.1.0-dev.11)* — Disabled buttons with !important.
- [x] **#18** *(1.1.0-dev.11)* — Editor content wiped on poll cycle.
- [x] **#19** *(1.1.0-dev.12)* — No validate button for secrets.yaml.
- [x] **#20** *(1.1.0-dev.12)* — Validate stays in editor.
- [x] **#21** *(1.1.0-dev.13)* — Save closes editor.
- [x] **#22** *(1.1.0-dev.13)* — Autocomplete from real ESPHome components.
- [x] **#23** *(1.1.0-dev.14)* — Toast auto-dismiss timing.
- [x] **#24** *(1.1.0-dev.14)* — Validation result toasts.
- [x] **#25** *(1.1.0-dev.15)* — Per-component autocomplete from schema.esphome.io.
- [x] **#26** *(1.1.0-dev.15)* — CI mypy types-PyYAML.
- [x] **#27** *(1.1.0-dev.16)* — Root-level autocomplete triggering.
- [x] **#28** *(1.1.0-dev.18)* — Rename React modal.
- [x] **#29** *(1.1.0-dev.18)* — Delete React modal with Archive/Permanent.
- [x] **#30** *(1.1.0-dev.18)* — Modal drag-select closing.
- [x] **#31** *(1.1.0-dev.18)* — Rename OTA targets old device address.
- [x] **#32** *(1.1.0-dev.19)* — Device list doesn't refresh after rename/edit. Server forces config rescan after rename. Config cache invalidated after save.
- [x] **#33** *(1.1.0-dev.19)* — Device logs "asyncio not defined". Stale Docker image. Forced clean rebuild.
- [x] **#34** *(1.1.0-dev.19)* — Live Logs modal drag-select close issue. Applied same mousedown tracking fix as #30.
- [x] **#35** *(1.1.0-dev.19)* — Edit buttons in Queue rows and log modal header.
- [x] **#36** *(1.1.0-dev.19)* — "Save & Upgrade" button in YAML editor — saves, triggers compile, switches to Queue tab.
- [x] **#37** *(1.1.0-dev.19)* — Duplicate device after rename. Old device entry explicitly removed from poller on rename.
- [x] **#38** *(1.1.0-dev.19)* — Same IP = same device filter in unmanaged device list.
- [x] **#39** *(1.1.0-dev.19)* — Light mode editor modals. CSS variables for modal themes, button color adjustments.
- [x] **#40** *(1.1.0-dev.19)* — "Checking..." state with pulsing dot instead of showing offline on startup.
- [x] **#41** *(1.1.0-dev.20)* — Rename button says "Rename and Flash" → "Rename & Upgrade" for consistency.
- [x] **#42** *(1.1.0-dev.20)* — Rename button added to Editor modal header.
- [x] **#43** *(1.1.0-dev.20)* — Editor hover tooltips for validation errors. Enabled hover + glyphMargin in Monaco options.
- [x] **#44** *(1.1.0-dev.20)* — Editor highlights unsaved changes with background color on modified lines.
- [x] **#45** *(1.1.0-dev.20)* — HA status as dedicated column in devices table. Implemented 4.2c: HA connected state used as additional online signal.
- [x] **#46** *(1.1.0-dev.20)* — Light mode header kept dark so ESPHome logo stays readable.
- [x] **#47** *(1.1.0-dev.21)* — Validation failure opens log modal automatically. Improved toast message.
- [x] **#48** *(1.1.0-dev.21)* — Validate button saves editor content first, then validates against current text.
- [x] **#49** *(1.1.0-dev.21)* — Dirty line highlight color made more visible (0.08 → 0.15 opacity).
- [x] **#50** *(1.1.0-dev.21)* — Editor footer shows "n lines changed" when there are unsaved changes.
- [x] **#51** *(1.1.0-dev.21)* — Clear button on each finished job row in Queue tab.
- [x] **#52** *(1.1.0-dev.21)* — HA status not populating. Entity registry REST API doesn't exist; switched to /api/states with binary_sensor device_class=connectivity filter.
- [x] **#53** *(1.1.0-dev.21)* — Dark mode checkboxes use color-scheme: dark.
- [x] **#54** *(1.1.0-dev.22)* — aioesphomeapi.connection log level set to ERROR (expected when devices offline).
- [x] **#55** *(1.1.0-dev.22)* — "Detected HA ESPHome add-on version" changed to DEBUG level.
- [x] **#56** *(1.1.0-dev.22)* — PyPI version limit increased from 10 to 50.
- [x] **#57** *(1.1.0-dev.22)* — Validate opens streaming log modal directly. No more toasts for validation flow.
- [x] **#58** *(1.1.0-dev.22)* — Diagnostic INFO log on first HA poll cycle. Led to fix in #59.
- [x] **#59** *(1.1.0-dev.23)* — HA state slow to populate. First poll was delayed 30s; now polls immediately on startup.
- [x] **#60** *(1.1.0-dev.23)* — Restart device button in hamburger menu. Calls HA REST API button.press on button.<name>_restart entity.
- [x] **#61** *(1.1.0-dev.23)* — Logs button moved to hamburger menu as "Live Logs".
- [x] **#62** *(1.1.0-dev.23)* — Hamburger menu icon changed to vertical ellipsis, styled as plain text not button.
- [x] **#63** *(1.1.0-dev.23)* — Device polling now uses asyncio.gather for concurrent status checks instead of sequential.
- [x] **#64** *(1.1.0-dev.24)* — Restart button uses friendly_name for HA entity matching (was using esphome.name which doesn't match HA's naming).
- [x] **#65** *(1.1.0-dev.24)* — Live logs now include boot log (dump_config=True in subscribe_logs).
- [x] **#66** *(1.1.0-dev.24)* — Git clone caching regression. Config resolver now uses skip_update=True after first resolution per target.
- [x] **#67** *(1.1.0-dev.24)* — HA status matching now tries friendly_name first, then esphome.name, then filename stem. Should match most devices.
- [x] **#68** *(1.1.0-dev.24)* — Live Logs and Restart no longer disabled when device appears offline.
- [x] **#69** *(1.1.0-dev.24)* — "esphome:" marked unknown. Added core keys (esphome, substitutions, packages, external_components) to component list.
- [x] **#70** *(1.1.0-dev.24)* — DeprecationWarning on app state. Changed to clear()+update() on existing dict instead of reassigning.
- [x] **#71** *(1.1.0-dev.24)* — HA entity matching uses friendly_name (e.g. "Nespresso Machine" → "nespresso_machine") instead of esphome.name.
- [x] **#72** *(1.1.0-dev.25)* — HA device detection without _status sensor. Now uses template API (integration_entities('esphome')) to find ALL ESPHome entities, then cross-references with _status sensors for connectivity. Devices without _status show as "Configured" instead of "—".
- [x] **#73** *(1.1.0-dev.26)* — Template API logging upgraded to WARNING level. Led to investigations resolved in subsequent fixes.
- [x] **#74** *(1.1.0-dev.26)* — Editor diff uses Monaco's built-in diff computation with common prefix/suffix fallback. Shifted lines no longer marked as changed.
- [x] **#75** *(1.1.0-dev.26)* — Restart uses native API first (aioesphomeapi: list entities → find restart button → button_command), falls back to HA REST API.
- [x] **#76** *(1.1.0-dev.26)* — Live log lines include [HH:MM:SS] timestamps.
- [x] **#77** *(1.1.0-dev.26)* — Compile logs colorized via ANSI escapes: INFO=green, WARNING=yellow, ERROR=red.
- [x] **#78** *(1.1.0-dev.26)* — OTA always passes --device with known IP. Server populates ota_address from device poller for all compile jobs.
- [x] **#79** *(1.1.0-dev.26)* — Editor diff uses Monaco's diff API with prefix/suffix fallback (replaced custom LCS).
- [x] **#80** *(1.1.0-dev.26)* — Switched from separate compile+upload to `esphome run --no-logs` (single process, same as native ESPHome UI).
- [x] **#81** *(1.1.0-dev.27)* — Terminal default text color changed from green to white (#e2e8f0).
- [x] **#82** *(1.1.0-dev.27)* — HA column now shows only "Yes" / "—" (configured or not). _status connectivity still feeds into online/offline column via 4.2c.
- [x] **#83** *(1.1.0-dev.30)* — HA matching for devices with non-standard HA entity names. Root cause: Screek sensors register with firmware names containing MAC fragments. Fix: added MAC fragment match + fixed _normalize_for_ha to strip special chars.
- [x] **#84** *(1.1.0-dev.28)* — Light mode connect worker form inputs. Changed hardcoded #0d1117 to var(--bg).
- [x] **#85** *(1.1.0-dev.28)* — Timezone mismatch causing different config_hash. Server now sends its TZ in job response; worker sets TZ in subprocess env.
- [x] **#86** *(1.1.0-dev.28)* — OTA retry restored. If esphome run fails after compile success, retries with esphome upload after 5s delay.
- [x] **#87** *(1.1.0-dev.29)* — OTA retry keeps job in WORKING state until final result. If worker dies during retry, timeout checker re-queues to another worker.
- [x] **#88** *(1.1.0-dev.29)* — MAC address matching for HA devices. Device poller captures MAC from device_info(). HA entity poller queries device identifiers via template API. Matching tries MAC first, then name fallback.
- [x] **#89** *(1.1.0-dev.32)* — ESPHome install errors now streamed to job log in real time (red ANSI). pip stderr included in error detail.

</details>
