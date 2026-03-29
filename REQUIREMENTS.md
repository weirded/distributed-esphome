# Distributed ESPHome Build System — Requirements

## Overview

A system to distribute ESPHome firmware compilation across multiple machines. A Home Assistant add-on acts as the server/coordinator; lightweight Docker containers running on other hosts act as build workers (clients).

---

## System Architecture

```
┌─────────────────────────────────────────┐
│         Home Assistant Host             │
│  ┌───────────────────────────────────┐  │
│  │   HA Add-on: esphome-dist-server  │  │
│  │  - Web UI (job management)        │  │
│  │  - REST API (for clients)         │  │
│  │  - Job queue                      │  │
│  │  - ESPHome YAML scanner           │  │
│  │  - Device status poller           │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
         ▲              ▲
         │ HTTP poll    │ HTTP poll
         ▼              ▼
┌──────────────┐  ┌──────────────┐
│ Build Client │  │ Build Client │  ...
│ (Docker)     │  │ (Docker)     │
│ - esphome    │  │ - esphome    │
│ - OTA push   │  │ - OTA push   │
└──────────────┘  └──────────────┘
         │                │
         │ OTA (port 3232)│
         ▼                ▼
  [ESPHome devices on flat LAN]
         │
         │ native API (port 6053)
         ▼
  [server polls device status]
```

---

## Component 1: Server (HA Add-on)

### 1.1 Runtime Environment

- Python 3.11+, `aiohttp` for async HTTP server (handles both REST API and Web UI)
- `aioesphomeapi` for device status polling
- `zeroconf` for mDNS device discovery (pulled in transitively by aioesphomeapi)
- Packaged as a Home Assistant add-on (Docker-based, `config.yaml` + `Dockerfile`)
- Runs as a long-lived process inside HA's add-on infrastructure
- **ESPHome config directory**: mounted at `/config/esphome/` inside the add-on container via `map: config:rw` in `config.yaml`

**Two access paths — same aiohttp process, same port:**
- **Ingress (Web UI)**: HA proxies browser requests through `172.30.32.2` → add-on. HA handles authentication; add-on trusts all requests arriving from `172.30.32.2`. Appears as a sidebar panel in HA.
- **Direct port (Client API)**: External Docker build clients connect to `http://ha-host:8765/api/v1/*` using `Authorization: Bearer <token>`. This port is also exposed in `config.yaml` under `ports:` for direct access.

### 1.2 ESPHome Config Discovery

- On startup and on demand, scan `/config/esphome/*.yaml` (top-level only)
- Exclude files named `secrets.yaml` and files whose name starts with `.` (include fragments)
- Detect the installed ESPHome version via `importlib.metadata.version("esphome")`
- Each discovered YAML file becomes a **compilable target**

### 1.3 Job Model

```
Job {
    id: uuid
    target: str              # YAML filename (e.g. "living_room.yaml")
    esphome_version: str     # e.g. "2024.3.1"
    state: enum(pending, assigned, running, success, failed, timed_out)
    assigned_client_id: str | None
    assigned_at: datetime | None
    timeout_seconds: int     # default 300
    created_at: datetime
    finished_at: datetime | None
    retry_count: int         # max 3 before permanent failure
    log: str | None
    ota_result: str | None   # "success", "skipped", "failed", None
}
```

Note: `yaml_bundle` is not stored in the job model — it is generated on demand when a client claims a job (avoids holding large blobs in memory for all pending jobs).

### 1.4 Job Queue Behavior

- Queue is in-memory; persisted to `/data/queue.json` on every state change
- On server restart: jobs in state `pending` reload as `pending`; jobs in state `assigned`/`running` reset to `pending` (client may have missed the result); `success`/`failed` jobs are retained for display but not re-queued
- A compile run is triggered manually from the UI (all configs, selected configs, or one config)
- Each YAML file = one Job; jobs for a single run share a `run_id`
- Job lifecycle:
  - `pending` → client polls and claims → `assigned`
  - Client begins work → `running` (client sends status update)
  - Client returns result → `success` or `failed`
  - Timeout elapses without result → `timed_out` → re-enqueued as `pending` (up to 3 retries, then permanent `failed`)
- Only one job per target may be `pending`/`assigned`/`running` at a time (deduplicate on enqueue)
- Jobs from completed runs are visible in the queue panel with their final state until a new run starts or they are cleared

### 1.5 YAML Bundle

When a client claims a job, the server generates and returns a bundle containing:
- The entire `/config/esphome/` directory tree, **including** `secrets.yaml`
- `secrets.yaml` is included because ESPHome requires it at compile time for any config using `!secret` references — without it, compilation fails. The bundle is transmitted over an authenticated connection on a trusted internal network.
- If a subdirectory (e.g. `packages/`) contains its own `secrets.yaml`, that is included too
- Bundle format: `tar.gz`, base64-encoded in the JSON job response

### 1.6 REST API (consumed by clients)

All endpoints are under `/api/v1/`. Authentication: shared secret token in `Authorization: Bearer <token>` header. Token configured in add-on options.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/clients/register` | Client announces itself; returns `client_id` |
| `POST` | `/api/v1/clients/heartbeat` | Client signals it is alive; updates `last_seen` |
| `GET`  | `/api/v1/jobs/next` | Claim next pending job (atomic); returns job+bundle or 204 |
| `POST` | `/api/v1/jobs/{id}/result` | Submit success/failure + log |
| `POST` | `/api/v1/jobs/{id}/status` | Report in-progress status text |
| `GET`  | `/api/v1/status` | Server health + ESPHome version info |
| `GET`  | `/ui/api/targets/{filename}/content` | Read YAML config file content |
| `POST` | `/ui/api/targets/{filename}/content` | Write YAML config file content |

**`POST /api/v1/clients/register`**
```json
// Request
{ "hostname": "build-node-1", "platform": "linux/amd64" }
// Response
{ "client_id": "uuid" }
```

**`GET /api/v1/jobs/next`**
```json
// Response (200 — job claimed)
{
  "job_id": "uuid",
  "target": "living_room.yaml",
  "esphome_version": "2024.3.1",
  "bundle_b64": "<base64 tar.gz>",
  "timeout_seconds": 300
}
// Response (204 — no jobs available)
```

**`POST /api/v1/jobs/{id}/result`**
```json
{
  "status": "success",       // or "failed"
  "log": "...",
  "ota_result": "success"    // or "failed", "skipped"
}
```

### 1.7 Client Registry

- Clients register on connect; server tracks `{ client_id, hostname, platform, last_seen, current_job_id }`
- A client is considered **online** if `last_seen` is within 30 seconds (configurable)
- Heartbeat interval: 10 seconds (client side)

### 1.8 Device Status Polling

The server maintains a background task that polls each discovered ESPHome device for its current status and running firmware version. This is independent of the build/compile workflow.

**Discovery:**
- Use `zeroconf` to listen for `_esphomelib._tcp` mDNS advertisements on the local network
- Each advertisement gives: device hostname, IP address, port (default 6053), and TXT record metadata (includes version string)
- The version from the mDNS TXT record is used as a fast path; it is confirmed via the native API when a full connection is made

**Version query:**
- Use `aioesphomeapi.APIClient` to connect to each device and call `device_info()`
- Returns: `esphome_version`, `name`, `mac_address`, `compilation_time`
- Connection is short-lived (connect → query → disconnect); not a persistent subscription
- Devices requiring API password: not supported in v1 (add-on option to configure a global API password may be added in v2)
- Poll each known device every 60 seconds; update immediately on mDNS advertisement change

**Device Model (server-side, in-memory):**
```
Device {
    name: str                  # from YAML filename stem, confirmed by device_info
    ip_address: str
    online: bool
    running_version: str | None
    last_seen: datetime | None
    compile_target: str | None  # which .yaml file maps to this device
}
```

**Mapping device → YAML config:**
- Match on `device.name` (from mDNS/device_info `name` field) against the YAML filename stem (e.g. `living_room.yaml` → `living_room`)
- If no match, device appears in the UI as "discovered but unmanaged"

### 1.9 Web UI

Single-page HTML served by the aiohttp server. Uses vanilla JS + CSS (no build step, no npm, no framework). All data fetched via internal JSON endpoints.

**Ingress path handling:**
- The server reads the `X-Ingress-Path` header (injected by HA, e.g. `/api/hassio_ingress/esphome_dist_server/`) and injects it as `<base href="...">` when serving `index.html`
- All JS `fetch()` calls use **relative paths** (e.g. `fetch('./ui/api/queue')`), resolving correctly through both Ingress and the direct port
- Static assets (`<script>`, `<link>`) also use relative paths — no absolute `/` paths anywhere in the frontend
- No auth logic in the frontend — HA handles authentication upstream for Ingress traffic; Bearer tokens are only used by build clients hitting `/api/v1/*`

**Sections:**

**Clients Panel**
- Table: `Hostname | Platform | Status (online/offline) | Current Job`
- Auto-refreshes every 5 seconds

**Devices Panel**
- Table: `Device Name | IP | Online | Running Version | Server Version | Needs Update`
- "Needs Update" = true when running version ≠ server ESPHome version, or when config has been modified since last compile (future: track config mtime)
- "Force Upgrade" button per row — enqueues a single-target compile job regardless of version match
- Auto-refreshes every 15 seconds

**Targets Panel**
- Lists all discovered YAML configs with their mapped device's online status and running version
- Checkbox per config
- Buttons: `Compile All`, `Compile Selected`, `Upgrade Outdated` (enqueues only targets where running version ≠ server version)
- Disabled while a run is in progress

**Queue Panel** (visible when a run is active or recent jobs exist)
- Table columns: `[ ] | Target | State | Client | Duration | OTA | Actions`
- Checkbox column for multi-select cancel
- `Cancel Selected` button
- State badge color-coding: pending=grey, running=blue, success=green, failed=red, timed_out=orange
- Auto-refreshes every 3 seconds
- Log viewer: click a completed job row to expand inline log output

**Internal UI API endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/ui/api/targets` | List discovered YAML targets with device status |
| `GET`  | `/ui/api/queue` | Current job queue state |
| `GET`  | `/ui/api/clients` | Connected build clients |
| `GET`  | `/ui/api/devices` | Known ESPHome devices with version info |
| `POST` | `/ui/api/compile` | Start a compile run `{ "targets": ["all" \| "outdated" \| ["file.yaml", ...]] }` |
| `POST` | `/ui/api/cancel` | Cancel jobs `{ "job_ids": ["uuid", ...] }` |
| `GET`  | `/ui/api/targets/{filename}/content` | Read YAML config file content |
| `POST` | `/ui/api/targets/{filename}/content` | Write YAML config file content |

### 1.10 UI and Operational Improvements

**Target name display (three-tier):**
- Row shows three tiers: (1) `friendly_name` from config (bold, primary); (2) the YAML filename stem without `.yaml` extension (always shown, secondary); (3) `comment` from `esphome.comment` field (smaller, muted, only if set)
- All `.yaml` extensions are stripped from target/device names throughout the UI (devices panel, queue panel, clients panel)

**Built-in local client:**
- The server add-on container runs a bundled build client so at least one client is always available
- Client starts 5 seconds after the server starts (allows token generation) and uses the system ESPHome binary via `ESPHOME_BIN` env override, skipping virtualenv creation
- Controlled by `disable_local_client` config option (default `false`); when `true`, no background client is spawned
- `ESPHOME_BIN` env var: if set on an external client, that binary is used directly instead of the version-manager virtualenv

**Client hostname:**
- Docker run command shown in UI includes `--hostname $(hostname)` so the container adopts the Docker host's hostname
- Client reads `HOSTNAME` env var set by `--hostname`; falls back to `socket.gethostname()`

**ESPHome version pre-seeding:**
- Docker run command includes `-e ESPHOME_SEED_VERSION=<current-server-version>` so new clients pre-download the required ESPHome version on startup, before any job arrives
- Client reads `ESPHOME_SEED_VERSION` env var and calls `version_manager.ensure_version()` at startup

**Job status reporting:**
- Clients report granular progress via `POST /api/v1/jobs/{id}/status { "status_text": "..." }`
- Status messages: `"Downloading ESPHome <version>"`, `"Compiling"`, `"OTA Upgrade"`
- `status_text` field in Job model; shown below state badge in queue panel; transient (not persisted)

**OTA result fix:**
- `submit_result` allows updating `ota_result` on an already-SUCCESS job (OTA result is reported in a separate call after compile success is already submitted)

**Clients panel — current job:**
- Shows the YAML target filename (without `.yaml`) for the current job, not the job UUID

**Upgrade button coloring:**
- "Upgrade" button is green (`btn-success`) for devices where `needs_update` is true; secondary (gray) otherwise

**Device editor:**
- Each row in the devices panel has an "Edit" button opening a full-screen Monaco editor modal
- Monaco loaded from CDN (`unpkg.com/monaco-editor`) with YAML language mode and dark theme
- Custom ESPHome completion provider suggests top-level component keys
- `GET /ui/api/targets/{filename}/content` — returns file content as `{ "content": "..." }`
- `POST /ui/api/targets/{filename}/content` — writes file content; path validated to stay within config dir
- Config map changed from `config:ro` to `config:rw` to allow writes

**Device status on initial load:**
- Device info cached to `/data/device_cache.json`; loaded on startup so UI has immediate data
- Cached devices show `online: false` until mDNS confirms; mDNS events update status
- Poll loop performs an immediate pass 3 seconds after startup before entering the normal interval

**Disable local client option:**
- `disable_local_client: false` added to add-on config options/schema
- When `true`, `run.sh` skips spawning the background client process

**Add-on sidebar title:** `"ESPH Distributed"`

---

## Component 2: Build Client (Docker)

### 2.1 Runtime Environment

- Python 3.11+ slim image
- Dependencies: `requests` (HTTP polling/results)
- `esphome` is installed at runtime into version-specific virtualenvs (not baked into the image)

### 2.2 ESPHome Version Management

- Versions stored in `/esphome-versions/<version>/` (one virtualenv per version)
- On job claim, client checks if required version is installed; if not, installs it via `pip install esphome==<version>` into a fresh venv
- Maintains at most **3 versions** on disk (configurable via `MAX_ESPHOME_VERSIONS`); evicts least-recently-used when limit exceeded
- Version install happens before the job timeout timer starts

### 2.3 Client Lifecycle

```
startup:
  register with server → get client_id

loop (concurrent):
  heartbeat thread: POST /api/v1/clients/heartbeat every 10s

  main thread:
    poll GET /api/v1/jobs/next every 5s (when idle)

    on job received:
      ensure esphome version installed (install if not present)
      extract bundle to temp dir
      start timeout timer (job.timeout_seconds)
      run: esphome compile <target.yaml> (capture stdout+stderr)

      if completed within timeout and exit code 0:
        POST /api/v1/jobs/{id}/result { status: "success", log }
        run: esphome upload <target.yaml> (OTA)
        POST /api/v1/jobs/{id}/result { ota_result: "success"|"failed"|"skipped" }

      if completed within timeout and exit code != 0:
        POST /api/v1/jobs/{id}/result { status: "failed", log }

      if timeout exceeded:
        kill subprocess
        POST /api/v1/jobs/{id}/result { status: "failed", log: "timed out after Ns" }

      cleanup temp dir (always, via try/finally)
      resume polling
```

### 2.4 OTA Upload

- After successful compile, attempt `esphome upload <target.yaml>` using the same bundle directory
- OTA success/failure is independent from compile result:
  - Compile succeeded + OTA succeeded → `status: success, ota_result: success`
  - Compile succeeded + OTA failed → `status: success, ota_result: failed`
  - Compile failed → no OTA attempted → `status: failed, ota_result: null`
- OTA timeout: separate configurable value (`OTA_TIMEOUT`, default 120s)

### 2.5 Configuration (Environment Variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_URL` | required | e.g. `http://homeassistant.local:8765` |
| `SERVER_TOKEN` | required | Shared auth token |
| `POLL_INTERVAL` | `5` | Seconds between job polls when idle |
| `HEARTBEAT_INTERVAL` | `10` | Seconds between heartbeats |
| `JOB_TIMEOUT` | `300` | Compile timeout in seconds |
| `OTA_TIMEOUT` | `120` | OTA upload timeout in seconds |
| `MAX_ESPHOME_VERSIONS` | `3` | Max cached ESPHome versions on disk |
| `HOSTNAME` | `socket.gethostname()` | Worker name shown in UI |

---

## Component 3: HA Add-on Packaging

### 3.1 Add-on `config.yaml`

```yaml
name: "ESPHome Distributed Build Server"
version: "1.0.0"
slug: "esphome_dist_server"
description: "Distributed ESPHome compilation coordinator"
arch: [aarch64, amd64, armhf, armv7, i386]
startup: application
boot: auto

# Ingress: Web UI embedded in HA sidebar, authenticated by HA
ingress: true
ingress_port: 8765
panel_icon: mdi:progress-wrench
panel_title: "ESPH Distributed"

# Direct port: build clients (Docker) connect here with Bearer token auth
ports:
  8765/tcp: 8765

map:
  - config:rw
options:
  token: ""
  job_timeout: 300
  ota_timeout: 120
  client_offline_threshold: 30
  device_poll_interval: 60
  disable_local_client: false
schema:
  token: str
  job_timeout: int
  ota_timeout: int
  client_offline_threshold: int
  device_poll_interval: int
  disable_local_client: bool
```

Both `ingress_port` and `ports:` point to 8765 — the same aiohttp process serves both. Ingress traffic arrives from `172.30.32.2` (trusted, no auth check needed). Direct port traffic must present `Authorization: Bearer <token>` on `/api/v1/*` routes.

### 3.2 Add-on Directory Layout

```
ha-addon/
├── config.yaml
├── Dockerfile
├── run.sh
└── server/
    ├── main.py           # aiohttp app setup, middleware, startup/shutdown
    ├── api.py            # /api/v1/* handlers (client-facing, Bearer token auth)
    ├── ui_api.py         # /ui/api/* handlers (browser-facing, Ingress auth)
    ├── queue.py          # job queue, state machine, persistence
    ├── scanner.py        # YAML discovery, bundle generation
    ├── registry.py       # build client registry
    ├── device_poller.py  # mDNS listener + aioesphomeapi queries
    ├── static/
    │   └── index.html    # single-file Web UI (all paths relative, base href injected)
    └── requirements.txt  # aiohttp, aioesphomeapi, zeroconf
```

---

## Component 4: Client Dockerfile

```
client/
├── Dockerfile
├── client.py             # main loop, heartbeat, job runner
├── version_manager.py    # esphome version install/eviction (LRU)
└── requirements.txt      # requests
```

- Base: `python:3.11-slim`
- System deps: `gcc`, `libffi-dev`, `libssl-dev` (required to build esphome wheels)
- Entrypoint: `python client.py`
- Volume: `/esphome-versions` (persist version cache across container restarts)

---

## Component 5: File Layout (This Repo)

```
distributed-esphome/
├── REQUIREMENTS.md
├── ha-addon/
│   ├── config.yaml
│   ├── Dockerfile
│   ├── run.sh
│   └── server/
│       ├── main.py
│       ├── api.py
│       ├── ui_api.py
│       ├── queue.py
│       ├── scanner.py
│       ├── registry.py
│       ├── device_poller.py
│       ├── static/
│       │   └── index.html
│       └── requirements.txt
├── client/
│   ├── Dockerfile
│   ├── client.py
│   ├── version_manager.py
│   └── requirements.txt
└── tests/
    ├── test_queue.py
    ├── test_scanner.py
    ├── test_client.py
    ├── test_device_poller.py
    └── fixtures/
        └── esphome_configs/
            ├── secrets.yaml
            ├── device1.yaml
            ├── device2.yaml
            └── packages/
                └── common.yaml
```

---

## Success Criteria

### Server
- [ ] Discovers all `.yaml` files in `/config/esphome/` on startup (excluding `secrets.yaml`)
- [ ] Correctly reports installed ESPHome version via `importlib.metadata`
- [ ] `/api/v1/jobs/next` is atomic: two simultaneous clients cannot claim the same job
- [ ] Bundle sent to clients includes `secrets.yaml` and the full directory tree
- [ ] Timed-out jobs are re-enqueued and retried up to 3 times before marking permanently `failed`
- [ ] Cancelled jobs transition to `failed` immediately regardless of current state
- [ ] On restart, `assigned`/`running` jobs reset to `pending`; `pending` jobs restore as-is
- [ ] Web UI loads without JavaScript errors in a modern browser
- [ ] Web UI clients panel refreshes without page reload
- [ ] Web UI queue panel updates in real time while a run is active
- [ ] Web UI devices panel shows online/offline status and running firmware version
- [ ] "Needs Update" flag correctly identifies devices running an older ESPHome version
- [ ] "Upgrade Outdated" button enqueues only targets where running version ≠ server version
- [ ] "Force Upgrade" per device enqueues a single-target compile regardless of version match

### Client
- [ ] Registers with server on startup and appears in UI as online
- [ ] Disappears from online list within 30s of shutdown
- [ ] Installs the correct ESPHome version before compiling; timer starts after install
- [ ] Evicts oldest version when `MAX_ESPHOME_VERSIONS + 1` versions would be on disk
- [ ] Compiles successfully and returns log to server
- [ ] Performs OTA upload after successful compile; reports result separately
- [ ] Reports `failed` and releases job if compile exceeds `JOB_TIMEOUT`
- [ ] Cleans up temp directory after every job (success or failure, via try/finally)
- [ ] Resumes polling after completing a job

### Device Status
- [ ] Server discovers ESPHome devices on LAN via mDNS without manual configuration
- [ ] Running firmware version retrieved from device via native API
- [ ] Device online/offline state updates within 60 seconds of a device going offline
- [ ] Devices are correctly mapped to their YAML config by name

### Integration
- [ ] A compile triggered from UI results in firmware flashed on device via OTA
- [ ] Two clients sharing a queue each receive unique jobs (no double-assignment)
- [ ] Killing a client mid-job causes timeout and re-assignment to another client
- [ ] Selecting and cancelling jobs from the UI removes them from the queue
- [ ] After OTA completes, device version in UI updates on next poll cycle

---

## Test Plan

### Unit Tests (pytest, no HA or Docker required)

| Test | File | What it validates |
|------|------|-------------------|
| Queue enqueue + dequeue | `test_queue.py` | FIFO order, deduplication |
| Job claim atomicity | `test_queue.py` | Concurrent claims: only one succeeds |
| Job timeout + re-enqueue | `test_queue.py` | State transitions, retry counter increments |
| Max retries → permanent failure | `test_queue.py` | Job marked `failed` after 3 timeouts |
| Cancel job (any state) | `test_queue.py` | Transitions to `failed` |
| Restart recovery — pending | `test_queue.py` | Pending jobs reload correctly from JSON |
| Restart recovery — assigned | `test_queue.py` | Assigned/running jobs reset to pending |
| YAML scanner discovery | `test_scanner.py` | Finds correct files, excludes `secrets.yaml` from target list |
| Bundle creation | `test_scanner.py` | tar.gz includes `secrets.yaml` and full tree |
| Version eviction | `test_client.py` | LRU eviction triggers at limit+1 |
| Client timeout behavior | `test_client.py` | Job marked failed after timeout, temp dir cleaned |
| Device name → YAML mapping | `test_device_poller.py` | Correct match and unmanaged handling |

### Integration Tests (docker compose, mock ESPHome)

Use a `docker-compose.test.yml` that:
- Starts the server with a fixture config directory mounted at `/config/esphome/`
- Starts 2 client containers
- Replaces the `esphome` binary with a mock shell script (sleeps briefly, exits 0)

| Test | What it validates |
|------|-------------------|
| Client registration | Both clients appear in `/ui/api/clients` as online |
| Job dispatch — 2 clients, 2 jobs | Each client gets exactly one unique job |
| Job dispatch — 1 client, 3 jobs | Client processes jobs sequentially, all complete |
| Timeout + reassignment | Client paused (SIGSTOP) mid-job; job times out; second client picks it up |
| Cancel via UI API | `POST /ui/api/cancel` marks job as failed; no result accepted after cancel |
| Queue persistence | Server restarted mid-queue; running jobs reset to pending; pending jobs restored |
| Version install | Job specifies new ESPHome version; client installs before compiling |
| Version eviction | After 4 distinct versions, oldest venv is removed |

### Manual Acceptance Tests (real HA + real ESPHome device)

| Test | Pass condition |
|------|----------------|
| Add-on installs cleanly | Add-on starts with no errors in HA log |
| Config discovery | All device `.yaml` files appear in Web UI targets panel |
| Device discovery | Devices appear in Web UI devices panel with correct version |
| "Needs Update" detection | Device running old firmware shows update flag |
| Compile All | All configs compiled; logs available in queue panel |
| OTA flash | After compile, device version in UI matches server version on next poll |
| Multi-client compile | N configs dispatched across 2 clients simultaneously; no duplicates |
| Client killed mid-job | Job times out, re-assigned to remaining client, completes successfully |
| Upgrade Outdated | Only devices with version mismatch are compiled and flashed |
| Force Upgrade | Single device force-upgrade enqueues and completes regardless of current version |

---

## Implementation Order

1. **`queue.py`** — job state machine, persistence, timeout tracking
2. **`scanner.py`** — YAML discovery, tar.gz bundle generation (including secrets.yaml)
3. **`registry.py`** — build client registry (register, heartbeat, online detection)
4. **`api.py`** — `/api/v1/*` client-facing REST handlers
5. **`device_poller.py`** — mDNS listener + aioesphomeapi device version queries
6. **`ui_api.py`** — `/ui/api/*` browser-facing JSON handlers
7. **`static/index.html`** — Web UI (clients, devices, targets, queue panels)
8. **`main.py`** — aiohttp app wiring, background tasks, add-on entrypoint
9. **`ha-addon/` packaging** — Dockerfile, config.yaml, run.sh
10. **`client/version_manager.py`** — ESPHome version install, LRU eviction
11. **`client/client.py`** — main client loop, heartbeat thread, job runner
12. **`client/Dockerfile`** — client Docker image
13. **`tests/`** — unit tests, then integration tests
