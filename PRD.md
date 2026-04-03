# PRD: Distributed ESPHome → Full ESPHome Dashboard Replacement

## Problem Statement

Users managing 50+ ESPHome devices need a single UI that handles both distributed compilation (our strength) and day-to-day device management (currently requires switching to the official ESPHome dashboard). The goal is to make distributed-esphome the only ESPHome UI users need.

## Current State (v0.0.72)

**What we have:**
- Distributed compilation across remote Docker workers
- Web UI with Devices, Queue, Workers tabs
- Basic Monaco YAML editor (30 hardcoded keywords)
- xterm.js live compile log viewer via WebSocket
- Device discovery (mDNS + ping + use_address)
- ESPHome version management (detect from HA, select from PyPI)
- OTA firmware upload from workers
- Performance-based job scheduling with CPU utilization awareness

**What the official ESPHome dashboard has that we don't:**
See feature list below.

## Technology Decision

**Frontend: React + Vite + TypeScript**
- Replaces the current single-file 2000-line `index.html`
- Component-based architecture for maintainability
- Massive ecosystem (react-monaco-editor, xterm-for-react, etc.)
- Vite for fast dev server + production builds
- Output: static files served by existing aiohttp backend
- Structure: `ha-addon/ui/` (source) → `ha-addon/server/static/` (build output)

**Backend: Existing aiohttp server (unchanged)**
- New API endpoints added as needed
- WebSocket endpoints for log streaming, real-time updates

---

## Feature Requirements

### Category 1: Editor & Config Management

**1.1 Rich Monaco Editor with ESPHome YAML Schema**
- Load ESPHome JSON schema from `https://json.esphome.io/esphome.json`
- Full autocomplete with documentation hovers
- Inline validation (red squiggles for errors)
- Support for `!include`, `!secret`, `!lambda` syntax
- Go-to-definition for includes
- Use `monaco-yaml` package or custom CompletionItemProvider walking the schema

**1.2 Config Validation (without compiling)**
- "Validate" button runs `esphome config <target>` on a worker (2-5 seconds vs 60-300s compile)
- Add `validate_only: bool` to Job — worker runs config check instead of compile
- Client-side schema validation from 1.1 for instant feedback as you type

**1.3 Secrets Editor**
- Edit `secrets.yaml` via the editor
- List secret key names (for reference when editing device configs)
- Endpoint: `GET /ui/api/secret-keys` returns key names without values

**1.4 LLM/AI-Powered Editor**
- Inline autocomplete: send YAML context to LLM, display as ghost text suggestions
- Chat panel: natural language → YAML generation ("Add a BME280 on I2C")
- Accept/reject UI for AI-generated changes
- Configurable provider: Anthropic Claude, OpenAI, local Ollama
- Add-on config options for API key, model, endpoint
- Endpoints: `POST /ui/api/ai/complete`, `POST /ui/api/ai/chat`

**1.5 Config Diff Since Last Compile**
- Store config snapshot at compile time in `/data/config_snapshots/`
- Show unified diff between current and last-compiled config
- Visual diff viewer in the editor modal

### Category 2: Device Lifecycle

**2.1 Create New Device**
- Wizard modal: device name, platform (ESP32/ESP8266/RP2040), board selection, WiFi from secrets
- Three modes: empty template, clone existing device, import from URL
- Board dropdown populated from ESPHome schema
- Endpoint: `POST /ui/api/targets/create`

**2.2 Rename Device**
- Update `esphome.name`, `esphome.friendly_name`, and filename
- Clear caches, update device poller mappings
- Endpoint: `POST /ui/api/targets/{filename}/rename`

**2.3 Delete Device**
- Soft delete: move to `.archive/` folder (reversible)
- Hard delete option
- Warn if device is online or configured in HA
- Clear queued jobs for the target
- Endpoint: `DELETE /ui/api/targets/{filename}`

**2.4 Device Adoption/Import**
- Discover unconfigured ESPHome devices via mDNS
- "Adopt" button creates config from the device's project URL
- Support for ignoring discovered devices

### Category 3: Firmware & Flashing

**3.1 Firmware Binary Download**
- Worker reads `.bin` from build output after compile, uploads to server
- Server stores in `/data/firmware/<target>/`
- Download button on device row (both legacy and modern OTA format)
- Endpoints: `GET /ui/api/targets/{filename}/firmware`, `POST /api/v1/jobs/{id}/firmware`

**3.2 Serial Flashing via Web Serial API**
- Browser-direct: `esp-web-tools` custom element for USB flashing from user's computer
- Server serial: list ports on HA host, flash via esptool.py
- Improv WiFi protocol for initial device setup
- Requires firmware binary from 3.1
- Endpoints: `GET /ui/api/serial-ports`, `GET /ui/api/targets/{filename}/manifest.json`

**3.3 Firmware Rollback**
- Keep previous firmware version alongside current
- "Rollback" button OTAs the previous firmware

### Category 4: Device Monitoring & Logs

**4.1 Live Device Log Tailing**
- Stream runtime logs from devices via aioesphomeapi `subscribe_logs()`
- Reuse xterm.js terminal component
- Handle encrypted devices (keys already extracted)
- "Logs" button on device row
- WiFi API logs + Web Serial API for USB-connected devices
- Endpoint: `GET /ui/api/targets/{filename}/logs/ws` (WebSocket)

**4.2 HA Entity Status**
- Query HA REST API for ESPHome device entities
- Show in Devices tab: configured in HA (yes/no), connected (yes/no)
- Use HA status to supplement online/offline detection
- Background task polls HA states every 30s
- Endpoint addition to `/ui/api/targets` response: `ha_configured`, `ha_connected`

**4.3 Device Web Server Links**
- Clickable IP address linking to `http://{ip}` when device has `web_server` component
- Detect `web_server` presence from resolved config

**4.4 Show API Encryption Key**
- Display/copy the device's API encryption key
- Keys already extracted in `build_name_to_target_map`
- Endpoint: `GET /ui/api/targets/{filename}/api-key`

### Category 5: Build & Maintenance

**5.1 Clean Build Artifacts**
- Per-device: dispatch `esphome clean <target>` to worker
- Clean all: clear entire build cache
- Useful when builds fail due to corrupted cache

**5.2 Build Cache Status**
- Workers report cache hit/miss stats
- Display in job results and worker table

**5.3 Scheduled Compiles**
- Cron-like scheduler in add-on config
- Auto-compile on ESPHome version update

**5.4 Notification Hooks**
- Webhook URL (Slack/Discord) for job success/failure notifications

### Category 6: UI & UX

**6.1 Device Search/Filter**
- Search bar above the Devices table that filters rows in real-time
- Matches against all visible columns: device name, friendly name, filename, status, IP, running version
- Client-side filtering (no API call) — instant results as you type
- Filter state persists across background poll refreshes (same pattern as checkbox retention)
- Clear button to reset the filter

**6.2 Dark/Light Theme Toggle**
- CSS custom properties for both themes
- Persist preference in localStorage
- Default: dark (current)

**6.3 Device Groups/Tags**
- Organize devices by room, type, or custom tags
- Filter/group in Devices tab
- Stored in JSON sidecar metadata

**6.4 Export Logs**
- Download compile or device logs as .txt file from log modal

**6.5 Streamer Mode**
- Toggle that masks IPs, API keys, tokens in the UI
- CSS-based blur on sensitive elements

**6.6 Bulk Operations**
- Extend existing multi-select: bulk delete, bulk validate, bulk tag

**6.7 Prometheus Metrics Endpoint**
- Service discovery format for monitoring
- Device metadata labels

---

## Migration Plan: Single HTML → React

The React migration is a prerequisite for all new features. Approach:

1. **Scaffold React + Vite project** in `ha-addon/ui/`
2. **Port existing UI** component by component (Devices, Queue, Workers tabs)
3. **Replace CDN libs** with npm packages (monaco-editor, xterm, etc.)
4. **Build output** goes to `ha-addon/server/static/` — aiohttp serves as before
5. **API layer unchanged** — React fetches same `/ui/api/*` endpoints
6. **CI integration** — add `npm run build` to the build pipeline

No backend changes needed for the migration itself.

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Frontend framework | React + Vite + TypeScript | Largest ecosystem, best LLM support, industry standard |
| Editor | monaco-editor (npm) + monaco-yaml | Schema-aware YAML editing with full autocomplete |
| Terminal | @xterm/xterm (npm) | Already proven in our UI |
| Device logs | aioesphomeapi subscribe_logs() | Library already installed on server |
| Serial flash | esp-web-tools (browser) + esptool.py (server) | Dual path: local USB + remote serial |
| LLM integration | Server-side proxy | Keeps API keys on server, works through Ingress |
| Firmware transfer | Separate binary POST (not base64 in JSON) | Avoids 33% size overhead |
| Config validation | Worker-dispatched `esphome config` | Reuses existing job infrastructure |

---

## API Endpoints (New)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/ui/api/validate` | POST | Dispatch validation job |
| `/ui/api/secret-keys` | GET | List secret key names |
| `/ui/api/targets/create` | POST | Create new device config |
| `/ui/api/targets/{f}/rename` | POST | Rename device |
| `/ui/api/targets/{f}` | DELETE | Delete/archive device |
| `/ui/api/targets/{f}/api-key` | GET | Get encryption key |
| `/ui/api/targets/{f}/firmware` | GET | Download firmware binary |
| `/ui/api/targets/{f}/firmware/info` | GET | Firmware metadata |
| `/ui/api/targets/{f}/manifest.json` | GET | esp-web-tools manifest |
| `/ui/api/targets/{f}/logs/ws` | WS | Device log streaming |
| `/ui/api/serial-ports` | GET | List serial ports |
| `/ui/api/ai/complete` | POST | LLM autocomplete |
| `/ui/api/ai/chat` | POST | LLM chat/prompt |
| `/api/v1/jobs/{id}/firmware` | POST | Worker uploads firmware binary |
