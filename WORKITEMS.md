# Work Items — ESPHome Dashboard Replacement

Organized by release. Each item is independently shippable within its release.
Mark items `[x]` when complete.

---

## Completed (1.0.0 + 1.1.0)

<details>
<summary>Foundation, quick wins, editor, validation, device lifecycle, live logs, HA integration</summary>

- [x] React + Vite + TypeScript scaffolding
- [x] Port existing UI to React components (Devices, Queue, Workers tabs)
- [x] Port all modals (Log, Editor, Connect Worker)
- [x] Port polling, WebSocket log streaming, toast notifications
- [x] Fix polling interval explosion bug
- [x] Fix queue state handling (success = compile + OTA both done)
- [x] Fix button disabled states
- [x] **6.1 Device search/filter bar** — client-side filter across all columns
- [x] **4.3 Device web server links** — make IP clickable when device is online
- [x] **4.4 Show API encryption key** — copy-to-clipboard button per device
- [x] **6.4 Export logs** — download button in log modal saves terminal content as .txt
- [x] **1.3 Secrets editor** — "Secrets" button in header opens secrets.yaml in Monaco editor
- [x] **6.2 Dark/light theme toggle** — CSS variables for both themes, persist in localStorage
- [x] **1.1a–d Monaco YAML autocomplete** — ESPHome schema, completions, inline validation, !include/!secret/!lambda
- [x] **1.2a–c Config validation** — server endpoint, validate_only job type, Validate button in editor
- [x] **2.2 Rename device** — `POST /ui/api/targets/{f}/rename`, updates esphome.name + filename
- [x] **2.3 Delete device** — `DELETE /ui/api/targets/{f}` with archive, confirmation dialog
- [x] **4.1a–c Live device logs** — WebSocket endpoint, encryption handling, DeviceLogModal with xterm.js
- [x] **4.2a–c HA integration** — poll entity registry, status badges, connected state as online signal

</details>

---

## Completed in 1.2.0 (so far)

<details>
<summary>Worker UX, metadata, disk management, shadcn foundation, UI polish</summary>

- [x] Configurable parallel job slots from UI (+/- controls, pushed via heartbeat)
- [x] Queue shows friendly device names with filename and timestamp
- [x] Upgrade All skips known-offline devices
- [x] Pin jobs to specific worker ("Upgrade on..." submenu)
- [x] Docker Compose worker file
- [x] Configurable device columns (area, project, comment) with column picker
- [x] Disk space management — workers report usage, version manager auto-evicts when low
- [x] **DS.0** Install Tailwind v4 + shadcn init, map CSS variables
- [x] **DS.1** New components use shadcn (DropdownMenu for column picker, hamburger, upgrade)
- [x] Toast migrated to Sonner
- [x] ESPHome version selector migrated to shadcn DropdownMenu
- [x] Search boxes added to Queue and Workers tabs
- [x] Queue buttons grouped into shadcn dropdowns (Retry, Clear)
- [x] Validation jobs filtered from queue display

</details>

---

## Completed in 1.2.0

<details>
<summary>shadcn/ui design system, TanStack Table, SWR, local worker, 65+ bug fixes</summary>

- [x] shadcn/ui design system: Dialog, Button, DropdownMenu, Sonner toast, Tailwind preflight
- [x] TanStack Table for all three tabs (sorting, column visibility, row selection)
- [x] SWR data fetching (replaced manual setInterval polling)
- [x] Built-in local worker (python:3.11-slim base for PlatformIO compatibility)
- [x] Configurable device columns (Area, Comment, Project) with gear icon picker
- [x] Streamer mode (blur sensitive data)
- [x] Worker management: 0-slot pause, disk reporting, debounced controls
- [x] Archive management API (list, restore, permanent delete)
- [x] Copy to Clipboard on log modals
- [x] Unsaved changes warning in editor (shadcn Dialog)
- [x] 65+ bug fixes (#90-#158)

</details>

---

## 1.3.0 — Quality + Testing (current release)

Theme: **Harden the codebase.** Fill test coverage gaps, add CI, clean up Python code, add Playwright browser tests, and add ESPHome build integration tests. No new user features — focus on reliability and preventing regressions.

### ESPHome Build Integration Tests

Fixture YAML configs that cover every supported ESPHome platform/framework combination. Run actual `esphome compile` in CI and on the local worker to catch toolchain/dependency regressions early (like the Alpine glibc issues in 1.2.0).

- [ ] **BT.1 Fixture configs** — minimal compilable YAML for each platform:
  - ESP8266 (Arduino) — e.g. `d1_mini`
  - ESP32 (Arduino) — e.g. `esp32dev`
  - ESP32 (ESP-IDF) — e.g. `esp32dev` with `framework: esp-idf`
  - ESP32-S2 (ESP-IDF) — e.g. `esp32-s2-saola-1`
  - ESP32-S3 (ESP-IDF) — e.g. `esp32-s3-devkitc-1`
  - ESP32-C3 (ESP-IDF, RISC-V) — e.g. `esp32-c3-devkitm-1`
  - ESP32-C6 (ESP-IDF, RISC-V) — e.g. `esp32-c6-devkitc-1`
  - RP2040 (Arduino) — e.g. `rpipicow`
  - ESP32-H2 (ESP-IDF) — if supported
  - BK72xx (LibreTiny) — e.g. `generic-bk7231n-qfn32-tuya`
  - RTL87xx (LibreTiny) — e.g. `generic-rtl8710bn-2mb-788k`
- [ ] **BT.2 Docker compile test script** — `scripts/test-compile.sh` that builds each fixture in the client Docker image (`esphome-dist-client`), exits non-zero on any failure
- [ ] **BT.3 Local worker compile test** — same fixtures compiled via the local worker (server add-on image) to validate the python:3.11-slim base
- [ ] **BT.4 CI integration** — run `test-compile.sh` in GitHub Actions on push to `develop` (can be slow — use matrix or sequential, cache ESPHome venvs)

### Python Test Suite

117 existing tests. Main gaps: api.py, ui_api.py, main.py have low coverage.

- [ ] **T.0 Fix test anti-patterns** — redundant sys.path, hardcoded /tmp, sync async wrappers, module-level mocking
- [ ] **T.1 Auth middleware tests** (~6) — security critical
- [ ] **T.2 Worker API tests** (~21) — registration, job scheduling algorithm, result submission
- [ ] **T.3 UI API tests** (~23) — targets, compile, config CRUD, rename, queue management
- [ ] **T.4 Extend existing module tests** (~15) — scanner metadata, queue pinning, poller cache

### Playwright Browser Tests

End-to-end testing of the web UI using Playwright.

- [ ] **PW.1 Playwright setup** — install Playwright, configure test runner, add to CI. Test against a mock server or the real server with fixture data.
- [ ] **PW.2 Smoke tests** — page loads, all three tabs render, header elements present
- [ ] **PW.3 Device tab interactions** — search/filter, column picker, sort, multi-select, upgrade button states
- [ ] **PW.4 Queue tab interactions** — job badges, retry/cancel/clear actions, log modal opens
- [ ] **PW.5 Workers tab interactions** — slot controls, enable/disable, connect worker modal
- [ ] **PW.6 Editor modal** — open, edit YAML, save, validate, dirty state warning
- [ ] **PW.7 Theme and responsiveness** — dark/light toggle, narrow viewport behavior

### CI / GitHub Actions

- [ ] **CI.1 Run E2E tests in CI** — they use fake server/binary, no reason to skip
- [ ] **CI.2 Add test coverage reporting** — `pytest-cov`
- [ ] **CI.3 Add ruff linting**
- [ ] **CI.4 Add frontend build+lint job**
- [ ] **CI.5 Run Playwright tests in CI** — headless browser in GitHub Actions

### Python Codebase Cleanup

- [ ] **PY.1 Server DRY cleanup** — extract helpers.py, consolidate auth logic, DevicePoller public accessors
- [ ] **PY.2 Client cleanup** — heartbeat helper, run_job() cleanup, env var validation, logging for silent exceptions
- [ ] **PY.3 Version manager thread safety** — wait timeout, error propagation to waiters
- [ ] **PY.4 Consistency & polish** — standardize error handling, type hints, CLAUDE.md updates
- [ ] **PY.5 Extract magic strings to constants** — consolidate hardcoded values (URLs, paths, config keys, status strings, header names, etc.) into named constants in server and client Python code
- [ ] **PY.6 Extract magic strings to constants (UI)** — consolidate hardcoded API paths, localStorage keys, polling intervals, status strings, etc. into named constants in the TypeScript frontend

### Client Library Adoption

LIB.1–3 require a new Docker image (`psutil` needs C compilation). LIB.0 adds detection so the server/UI warns when the worker image is too old.

- [ ] **LIB.0 Client image version detection** — `IMAGE_VERSION` baked into Docker image, `MIN_IMAGE_VERSION` on server, heartbeat gates auto-update, UI warning badge
- [ ] **LIB.1 `psutil` for client system info** — replace ~200 lines of /proc/cpuinfo parsing with cross-platform API
- [ ] **LIB.2 `tenacity` for client retry logic** — decorator-based retries + exponential backoff
- [ ] **LIB.3 `pyyaml` for client network diagnostics** — replace fragile regex YAML parsing

### Security Hardening

- [ ] **SEC.1 Timing-safe token comparison** — `api.py` uses `==` for Bearer token check; replace with `secrets.compare_digest()` to prevent timing attacks. ESPHome uses `hmac.compare_digest` — we should match.
- [ ] **SEC.2 Bounded log storage** — workers can stream unlimited log data via `POST /api/v1/jobs/{id}/log`, risking OOM. Add a max log size (e.g. 512KB per job), truncate with a marker.
- [ ] **SEC.3 Validate max_parallel_jobs on registration** — UI validates 0-32 but `api.py` worker registration accepts any integer. Add bounds check to match.

### Quality Gates (CLAUDE.md)

Capstone for the 1.3 release: codify the standards established by all the above work into CLAUDE.md so future releases don't regress.

- [ ] **QG.1 Codify quality standards in CLAUDE.md** — document enforceable rules covering: constants over magic strings, test coverage requirements for new code, ruff/lint compliance, error handling patterns, naming conventions, frontend TypeScript standards, and any other conventions established during 1.3 cleanup. This is the last 1.3 task — written after everything else lands so it reflects the actual state of the codebase.

---

## 1.4.0 — ESPHome Dashboard Parity

Theme: **Full replacement for the stock ESPHome dashboard.** Every feature the built-in UI has, this has too — plus everything we've already added on top. After this release, there's no reason to use the stock dashboard.

### Create Device

- [ ] **2.1a Create device: empty template** — wizard modal with name, platform, board, WiFi from secrets
- [ ] **2.1b Create device: clone existing** — duplicate a config with new name

### Firmware Download & Flashing

- [ ] **3.1a Worker extracts firmware binary** — read .bin after compile, POST to server
- [ ] **3.1b Server stores firmware** — `/data/firmware/<target>/`, metadata endpoint
- [ ] **3.1c Download button on device row** — `GET /ui/api/targets/{f}/firmware`
- [ ] **3.2a Web Serial flashing** — esp-web-tools integration, manifest endpoint
- [ ] **3.2b Server serial flashing** — list ports on HA host, esptool.py flash endpoint

### Web Serial Logs

- [ ] **4.1d Web Serial logs** — browser-side USB serial log viewer (Web Serial API)

### Live Log Tail After Update

- [ ] **4.5 Auto-connect device logs after OTA** — when viewing a job's log modal, automatically connect to the device's native API log stream after OTA completes, like `esphome run` does (compile → upload → tail logs)

### Build Management

- [ ] **5.1 Clean build artifacts** — dispatch `esphome clean` to worker, per-device and clean-all

### Thread / IPv6 Support

- [ ] **4.6 Thread device IP display** (GitHub #17) — Thread devices use IPv6 and don't show an IP address in the dashboard. Display IPv6 addresses and add a wifi/thread indicator to the device row.

### Unmanaged Devices

- [ ] **6.8 Hide/remove unmanaged devices** (GitHub #18) — add ability to dismiss or hide mDNS-discovered devices that have no config file. Also extend streamer mode to blur unmanaged device info.

### Queue UX

- [ ] **6.7 Default queue sort by time** (GitHub #16) — sort queue tab by compile time (most recent first) by default, so latest jobs are always on top

### Device Adoption

- [ ] **2.4 Device adoption/import** — discover unconfigured devices, adopt with project URL

---

## 1.5.0 — Organization + Intelligence

Theme: **Power-user features that go beyond stock ESPHome.** Better ways to manage large device fleets, track config changes, and get AI assistance.

### File Tree Editor

Browse and edit any file in the ESPHome config directory, including subdirectories. VS Code-style file tree sidebar in the editor modal.

- [ ] **FT.1 `GET /ui/api/files`** — recursive directory listing, returns flat `[{path, size, binary}]`
- [ ] **FT.2 `GET /ui/api/files/{path:.+}`** — read file by relative path (path traversal prevention)
- [ ] **FT.3 `POST /ui/api/files/{path:.+}`** — write file (invalidates config cache for .yaml)
- [ ] **FT.4 Install `@headless-tree/core` + `@headless-tree/react`** — headless tree library
- [ ] **FT.5 `FileTree.tsx` component** — flat list → tree, expand/collapse, active highlight, binary grayed out
- [ ] **FT.6 Sidebar layout** — editor body flex row: `[file tree 240px] | [monaco flex-1]`, sidebar toggle
- [ ] **FT.7 File switching** — dirty check → load/save, language detection by extension
- [ ] **FT.8 Conditional buttons** — Save & Upgrade/Validate/Rename only for entry-point YAML; includes get Save only
- [ ] **FT.9 API functions** — `listFiles()`, `readFile()`, `writeFile()` in client.ts

### Device Organization

- [ ] **6.3 Device groups/tags** — JSON sidecar metadata, filter/group UI in Devices tab
- [ ] **6.6 Bulk operations** — extend multi-select: bulk delete, bulk validate, bulk tag

### Config Diff

- [ ] **1.5a Store config snapshot** — save YAML at compile time to `/data/config_snapshots/`
- [ ] **1.5b Diff endpoint** — return unified diff between current and last-compiled
- [ ] **1.5c Diff viewer in editor** — Monaco diff editor or inline diff display

### Import

- [ ] **2.1c Create device: import from URL** — fetch config from GitHub/project URL

### AI/LLM Editor

- [ ] **1.4a Server config** — add-on options for LLM provider, API key, model, endpoint
- [ ] **1.4b Completion endpoint** — `POST /ui/api/ai/complete` proxies to LLM with YAML context
- [ ] **1.4c Inline ghost text** — display LLM suggestions as Monaco inline completions
- [ ] **1.4d Chat endpoint** — `POST /ui/api/ai/chat` for natural language → YAML
- [ ] **1.4e Chat panel in editor** — side panel for prompting, accept/reject generated changes

---

## Future — Advanced Features

Items with less certainty on scope or priority. Will be shaped into a release when the time comes.

### Build Operations

- [ ] **5.2 Build cache status** — workers report cache stats, display in UI
- [ ] **5.4 Notification hooks** — webhook URL for job success/failure (Slack/Discord)

### Remote Compilation (Backlog #1)

- [ ] Allow compiling on VPS servers not on the local network (firmware download + separate OTA step)
- [ ] Possibly GitHub Actions integration for builds

### Git Integration (Backlog #2)

- [ ] Git functionality for configs — version history, commit, push/pull
