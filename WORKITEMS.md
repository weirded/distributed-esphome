# Work Items — ESPHome Dashboard Replacement

Sequenced for incremental delivery. Each item is independently shippable.
Mark items `[x]` when complete.

---

## Foundation (already done)

- [x] React + Vite + TypeScript scaffolding
- [x] Port existing UI to React components (Devices, Queue, Workers tabs)
- [x] Port all modals (Log, Editor, Connect Worker)
- [x] Port polling, WebSocket log streaming, toast notifications
- [x] Fix polling interval explosion bug
- [x] Fix queue state handling (success = compile + OTA both done)
- [x] Fix button disabled states

---

## Quick Wins (small, high-value, no backend changes)

- [x] **6.1 Device search/filter bar** — client-side filter across all columns, persists across polls
- [x] **4.3 Device web server links** — make IP clickable when device is online
- [x] **4.4 Show API encryption key** — copy-to-clipboard button per device + server endpoint
- [x] **6.4 Export logs** — download button in log modal saves terminal content as .txt
- [x] **1.3 Secrets editor** — "Secrets" button in header opens secrets.yaml in Monaco editor
- [x] **6.2 Dark/light theme toggle** — CSS variables for both themes, persist in localStorage

---

## Editor Improvements

- [x] **1.1a Load ESPHome JSON schema** (1.1.0-dev.9) — fetch from json.esphome.io, cached in module-level variable
- [x] **1.1b Monaco YAML autocomplete** (1.1.0-dev.9) — custom CompletionItemProvider walks schema graph for context-aware completions
- [x] **1.1c Inline validation** (1.1.0-dev.9) — warning markers for unknown top-level keys, debounced 500ms
- [x] **1.1d Support !include, !secret, !lambda** (1.1.0-dev.9) — !secret autocompletes from secrets.yaml, !-prefixed values skip validation

---

## Config Validation

- [x] **1.2a Server endpoint** (1.1.0-dev.10) — `POST /ui/api/validate` dispatches validation job
- [x] **1.2b Job type: validate_only** (1.1.0-dev.10) — worker runs `esphome config` (2-5s) instead of compile+OTA
- [x] **1.2c Validate button in editor** (1.1.0-dev.10) — triggers validation, switches to queue tab, badge shows "Validating"/"Valid"

---

## Device Lifecycle

- [x] **2.3 Delete device** (1.1.0-dev.16) — `DELETE /ui/api/targets/{f}` with archive, confirmation dialog, hamburger menu
- [x] **2.2 Rename device** (1.1.0-dev.16) — `POST /ui/api/targets/{f}/rename`, updates esphome.name + filename
- [ ] **2.1a Create device: empty template** — wizard modal with name, platform, board, WiFi from secrets
- [ ] **2.1b Create device: clone existing** — duplicate a config with new name
- [ ] **2.1c Create device: import from URL** — fetch config from GitHub/project URL

---

## Live Device Logs

- [x] **4.1a Server endpoint** (1.1.0-dev.18) — `GET /ui/api/targets/{f}/logs/ws` WebSocket, connects via aioesphomeapi
- [x] **4.1b Handle encryption** (1.1.0-dev.18) — passes noise_psk from extracted keys
- [x] **4.1c Logs button on device row** (1.1.0-dev.18) — DeviceLogModal with xterm.js, opens for online devices
- [ ] **4.1d Web Serial logs** — browser-side USB serial log viewer (Web Serial API)

---

## Firmware Download & Flashing

- [ ] **3.1a Worker extracts firmware binary** — read .bin after compile, POST to server
- [ ] **3.1b Server stores firmware** — `/data/firmware/<target>/`, metadata endpoint
- [ ] **3.1c Download button on device row** — `GET /ui/api/targets/{f}/firmware`
- [ ] **3.2a Web Serial flashing** — esp-web-tools integration, manifest endpoint
- [ ] **3.2b Server serial flashing** — list ports on HA host, esptool.py flash endpoint
- [ ] **3.3 Firmware rollback** — keep previous version, rollback button

---

## HA Integration

- [x] **4.2a Background task** (1.1.0-dev.19) — poll HA entity registry every 30s for ESPHome device status
- [x] **4.2b Device status in UI** (1.1.0-dev.19) — show "In HA" badge (configured/connected) in Devices tab
- [ ] **4.2c Influence online/offline** — use HA connected state as additional signal

---

## Config Diff

- [ ] **1.5a Store config snapshot** — save YAML at compile time to `/data/config_snapshots/`
- [ ] **1.5b Diff endpoint** — return unified diff between current and last-compiled
- [ ] **1.5c Diff viewer in editor** — Monaco diff editor or inline diff display

---

## AI/LLM Editor

- [ ] **1.4a Server config** — add-on options for LLM provider, API key, model, endpoint
- [ ] **1.4b Completion endpoint** — `POST /ui/api/ai/complete` proxies to LLM with YAML context
- [ ] **1.4c Inline ghost text** — display LLM suggestions as Monaco inline completions
- [ ] **1.4d Chat endpoint** — `POST /ui/api/ai/chat` for natural language → YAML
- [ ] **1.4e Chat panel in editor** — side panel for prompting, accept/reject generated changes

---

## Device Organization

- [ ] **6.3 Device groups/tags** — JSON sidecar metadata, filter/group UI in Devices tab
- [ ] **6.6 Bulk operations** — extend multi-select: bulk delete, bulk validate, bulk tag
- [ ] **2.4 Device adoption/import** — discover unconfigured devices, adopt with project URL

---

## Build Operations

- [ ] **5.1 Clean build artifacts** — dispatch `esphome clean` to worker, per-device and clean-all
- [ ] **5.2 Build cache status** — workers report cache stats, display in UI
- [ ] **5.3 Scheduled compiles** — cron-like scheduler, auto-compile on ESPHome version update
- [ ] **5.4 Notification hooks** — webhook URL for job success/failure (Slack/Discord)

---

## Polish

- [ ] **6.5 Streamer mode** — toggle masks IPs, keys, tokens (CSS blur)
- [ ] **6.7 Prometheus metrics** — service discovery endpoint with device metadata

---

## CI / GitHub Actions

- [ ] **CI.1 Run E2E tests** — remove `--ignore=tests/test_e2e_client.py`, add `-m "not integration"` to skip real-ESPHome tests
- [ ] **CI.2 Add test coverage** — install `pytest-cov`, run with `--cov`, upload coverage artifact
- [ ] **CI.3 Add ruff linting** — `ruff check ha-addon/server/ ha-addon/client/ tests/` + `ruff format --check`
- [ ] **CI.4 Add frontend build+lint job** — parallel job: `npm ci && npm run lint && npm run build` in `ha-addon/ui/`

---

## Test Suite Improvements

Existing tests (126 total) are all genuine and valuable. The main gaps are zero coverage of api.py, ui_api.py, and main.py (1,780 lines combined).

### Test infrastructure & anti-pattern fixes
- [ ] **T.0a Remove redundant `sys.path.insert()`** — conftest.py already handles it; remove from test_queue.py, test_device_poller.py, test_scanner.py, test_registry.py, test_client.py
- [ ] **T.0b Fix hardcoded `/tmp`** — `test_queue.py:test_concurrent_claims_atomic` should use `tmp_path`
- [ ] **T.0c Convert test_queue.py to native async** — replace `run(coro)` wrapper with `async def` tests
- [ ] **T.0d Fix module-level sys.modules patching** — move from test_device_poller.py into session-scoped conftest fixture
- [ ] **T.0e Rename test_client.py** — to `test_version_manager.py` (matches what it actually tests)

### Auth middleware tests (`tests/test_middleware.py`, ~6 tests)
- [ ] **T.1 Auth middleware tests** — security critical: test UI bypass, token validation, wrong token rejection, supervisor IP trust

### Worker API tests (`tests/test_api.py`, ~21 tests)
- [ ] **T.2a Registration & heartbeat tests** — register, re-register, heartbeat, deregister, error cases
- [ ] **T.2b Job scheduling tests** — empty queue, bundle delivery, disabled worker, performance-based deferral, pinned jobs, bundle failure recovery
- [ ] **T.2c Result submission tests** — success/failed results, unknown job, OTA patching, log append

### UI API tests (`tests/test_ui_api.py`, ~23 tests)
- [ ] **T.3a Target & device listing tests** — YAML list, device status, needs-update flag
- [ ] **T.3b Compile & validate tests** — compile all/outdated/specific, deduplication, validate-only
- [ ] **T.3c Config CRUD tests** — read/write content, path traversal security, delete with archive
- [ ] **T.3d Rename tests** — filename+name update, conflict 409, OTA job enqueue
- [ ] **T.3e Queue management tests** — clear by state, retry failed, cancel, worker disable/enable

### Extend existing module tests (~15 tests)
- [ ] **T.4a Scanner extensions** — `get_device_metadata()`, `build_name_to_target_map()` (encryption keys, address overrides)
- [ ] **T.4b Queue extensions** — validate-only jobs, OTA address, pinned job claim, OTA retry pinning
- [ ] **T.4c Device poller extensions** — cache load/save round-trip, address overrides, start/stop lifecycle

---

## UI Audit & Cleanup

### DRY violations
- [ ] **UI.1a Extract `timeAgo()`** — duplicated in DevicesTab.tsx and QueueTab.tsx, move to utils.ts
- [ ] **UI.1b Extract `useTerminal` hook** — duplicated Terminal init in LogModal.tsx and DeviceLogModal.tsx
- [ ] **UI.1c Extract `downloadTerminalLog()`** — duplicated blob-download in LogModal.tsx and DeviceLogModal.tsx
- [ ] **UI.1d Extract `useEscapeKey` hook** — duplicated Escape handler in LogModal, DeviceLogModal, EditorModal
- [ ] **UI.1e Extract overlay click handler** — duplicated `handleOverlayClick` in 4+ modals
- [ ] **UI.1f Merge clear handlers** — combine `handleClearSucceeded`/`handleClearFinished` in App.tsx

### Structural fixes
- [ ] **UI.2a Use or delete `usePolling` hook** — exists but App.tsx uses manual setInterval; recommend delete (App.tsx pattern is more efficient for multi-resource fetches)
- [ ] **UI.2b Use `useWebSocket` hook in DeviceLogModal** — hook exists but DeviceLogModal manages WebSocket manually
- [ ] **UI.2c Add utility CSS classes** — replace repeated inline styles with `.text-xs-muted`, `.font-mono`, `.flex-actions`; clean up App.css boilerplate
- [ ] **UI.2d Document DOM checkbox pattern** — add comment in DevicesTab/QueueTab explaining useRef+DOM approach is intentional for perf

### CLAUDE.md
- [ ] **UI.3 Add frontend section to CLAUDE.md** — dev commands, conventions (hooks in hooks/, CSS tokens, no state library, Monaco global registration)

---

## Python Codebase Cleanup

### Server DRY cleanup
- [ ] **PY.1a Extract `helpers.py`** — shared `_cfg()`, `json_error()`, `parse_json_body()` from api.py and ui_api.py
- [ ] **PY.1b Consolidate auth logic** — extract `HA_SUPERVISOR_IP`, `is_ha_supervisor()`, `check_bearer_token()` to helpers.py (duplicated in main.py and api.py)
- [ ] **PY.1c Add DevicePoller public accessors** — `get_api_key()`, `get_address_override()`, `has_api_key_for_target()` to replace ui_api.py accessing private `_encryption_keys`/`_address_overrides`

### Client cleanup
- [ ] **PY.2a Extract heartbeat thread helper** — copy-pasted 3 times in client.py
- [ ] **PY.2b Fix `run_job()` cleanup duplication** — early returns duplicate finally-block cleanup; restructure so all paths use finally
- [ ] **PY.2c Remove duplicate config reads** — `MAX_ESPHOME_VERSIONS`/`ESPHOME_VERSIONS_DIR` read from env in both client.py and version_manager.py; pass as constructor args instead
- [ ] **PY.2d Add startup env var validation** — validate `POLL_INTERVAL`, `JOB_TIMEOUT`, `MAX_PARALLEL_JOBS` at startup with clear error messages
- [ ] **PY.2e Add logging to silent exception handlers** — ~10 bare `except Exception: pass` blocks; add `logger.debug()`

### Version manager thread safety
- [ ] **PY.3a Add timeout to wait loop** — `wait_event.wait()` has no timeout; add 5-minute timeout with retry/error
- [ ] **PY.3b Fix error propagation to waiters** — if `_install()` raises, waiters retry broken install forever; track and propagate failures

### Consistency & polish
- [ ] **PY.4a Standardize error handling** — use `json_error()` in route handlers, `logger.exception()` in background tasks
- [ ] **PY.4b Fill missing type hints** — focus on function signatures in ui_api.py and client.py
- [ ] **PY.4c CLAUDE.md updates** — document helpers.py, error handling patterns, Python version discrepancy (CI=3.12, Dockerfile.standalone=3.11, build.yaml=3.13)
