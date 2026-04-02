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

- [ ] **1.1a Load ESPHome JSON schema** — fetch from json.esphome.io, cache in sessionStorage
- [ ] **1.1b Monaco YAML autocomplete** — integrate monaco-yaml or custom CompletionItemProvider with schema
- [ ] **1.1c Inline validation** — red squiggles for schema errors as you type
- [ ] **1.1d Support !include, !secret, !lambda** — custom YAML tag handling in editor

---

## Config Validation

- [ ] **1.2a Server endpoint** — `POST /ui/api/validate` dispatches validation job
- [ ] **1.2b Job type: validate_only** — add field to Job dataclass, worker runs `esphome config` instead of compile
- [ ] **1.2c Validate button in editor** — triggers validation, shows results in terminal or inline

---

## Device Lifecycle

- [ ] **2.3 Delete device** — `DELETE /ui/api/targets/{f}` with archive option, confirmation dialog
- [ ] **2.2 Rename device** — `POST /ui/api/targets/{f}/rename`, update esphome.name + filename
- [ ] **2.1a Create device: empty template** — wizard modal with name, platform, board, WiFi from secrets
- [ ] **2.1b Create device: clone existing** — duplicate a config with new name
- [ ] **2.1c Create device: import from URL** — fetch config from GitHub/project URL

---

## Live Device Logs

- [ ] **4.1a Server endpoint** — `GET /ui/api/targets/{f}/logs/ws` WebSocket, connects via aioesphomeapi
- [ ] **4.1b Handle encryption** — pass noise_psk from extracted keys
- [ ] **4.1c Logs button on device row** — opens log modal connected to device (not job) log stream
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

- [ ] **4.2a Background task** — poll HA REST API for ESPHome device entity status
- [ ] **4.2b Device status in UI** — show "In HA" badge (configured/connected) in Devices tab
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
- [ ] **CI: add npm build** — run `npm run build` in CI pipeline alongside Python tests
