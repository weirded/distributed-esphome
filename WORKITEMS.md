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

---

## HA Integration

- [x] **4.2a Background task** (1.1.0-dev.19) — poll HA entity registry every 30s for ESPHome device status
- [x] **4.2b Device status in UI** (1.1.0-dev.19) — show "In HA" badge (configured/connected) in Devices tab
- [x] **4.2c Influence online/offline** (1.1.0-dev.20) — use HA connected state as additional online signal

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
- [ ] **5.4 Notification hooks** — webhook URL for job success/failure (Slack/Discord)

---

## Polish

- [ ] **6.5 Streamer mode** — toggle masks IPs, keys, tokens (CSS blur)

---

## CI / GitHub Actions

- [ ] **CI.1 Run E2E tests in CI** — they use fake server/binary, no reason to skip
- [ ] **CI.2 Add test coverage reporting** — `pytest-cov`
- [ ] **CI.3 Add ruff linting**
- [ ] **CI.4 Add frontend build+lint job**

Details: `~/.claude/plans/hashed-wobbling-firefly.md` (Phase 0A), `~/.claude/plans/wild-bubbling-cat.md` (Phase 6), `~/.claude/plans/happy-munching-moonbeam.md` (Step 6)

---

## Test Suite Improvements

126 existing tests are all genuine and valuable. Main gaps: api.py, ui_api.py, main.py (1,780 lines) have zero coverage.

- [ ] **T.0 Fix test anti-patterns** — redundant sys.path, hardcoded /tmp, sync async wrappers, module-level mocking
- [ ] **T.1 Auth middleware tests** (~6) — security critical
- [ ] **T.2 Worker API tests** (~21) — registration, job scheduling algorithm, result submission
- [ ] **T.3 UI API tests** (~23) — targets, compile, config CRUD, rename, queue management
- [ ] **T.4 Extend existing module tests** (~15) — scanner metadata, queue pinning, poller cache

Details: `~/.claude/plans/hashed-wobbling-firefly.md`

---

## UI Audit & Cleanup

- [ ] **UI.1 Extract shared utilities** — `timeAgo()`, `useTerminal`, `downloadTerminalLog()`, `useEscapeKey`, overlay click handler
- [ ] **UI.2 Structural fixes** — delete unused `usePolling`, use `useWebSocket` in DeviceLogModal, utility CSS classes
- [ ] **UI.3 Add frontend section to CLAUDE.md**

Details: `~/.claude/plans/happy-munching-moonbeam.md`

---

## Python Codebase Cleanup

- [ ] **PY.1 Server DRY cleanup** — extract helpers.py, consolidate auth logic, DevicePoller public accessors
- [ ] **PY.2 Client cleanup** — heartbeat helper, run_job() cleanup, env var validation, logging for silent exceptions
- [ ] **PY.3 Version manager thread safety** — wait timeout, error propagation to waiters
- [ ] **PY.4 Consistency & polish** — standardize error handling, type hints, CLAUDE.md updates

Details: `~/.claude/plans/wild-bubbling-cat.md`

---

## Design System Adoption (shadcn/ui)

- [ ] **DS.0 Foundation** — install Tailwind v4 + shadcn init (zinc theme), map existing CSS variables, no visual changes
- [ ] **DS.1 New components use shadcn** — all new UI features (device wizard, diff viewer, AI chat) built with shadcn
- [ ] **DS.2 Migrate shared primitives** — buttons, badges, dropdowns, toast, dialog
- [ ] **DS.3 Migrate modals** — LogModal, EditorModal, ConnectWorkerModal, DeviceLogModal
- [ ] **DS.4 Migrate tables and tabs** — tab content, search/filter inputs
- [ ] **DS.5 Remove old CSS** — delete migrated classes from theme.css

Details: `~/.claude/plans/hashed-wobbling-firefly.md`
