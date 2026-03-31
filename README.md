# Distributed ESPHome

Offload ESPHome firmware compilation to remote machines. A Home Assistant add-on coordinates the job queue and serves the web UI; lightweight Docker containers on other hosts do the compiling and push firmware via OTA.

## Why?

ESPHome compilation is CPU-intensive and slow on the Raspberry Pi or similar low-power hardware running Home Assistant. This project lets you point the work at faster machines (x86 or ARM, including Apple Silicon) while keeping HA as the source of truth for your device configs.

## Architecture

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
  [ESPHome devices on LAN]
```

Add one or more remote build clients (Docker containers) to compile firmware and push it via OTA.

## Installation

### 1. Install the HA Add-on

Add this repository to your Home Assistant add-on store:

[![Add repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fweirded%2Fdistributed-esphome)

Or manually: **Settings → Add-ons → Add-on Store → ⋮ → Repositories** and add `https://github.com/weirded/distributed-esphome`.

Then find **ESPHome Distributed Build Server** in the store and click **Install**.

<details>
<summary>Manual install (local copy)</summary>

```bash
# From this repo root
tar -czf distributed-esphome-addon.tar.gz -s '/^ha-addon/distributed-esphome/' ha-addon
scp distributed-esphome-addon.tar.gz ha-host:/tmp/
ssh ha-host "cd /usr/share/hassio/addons/local && tar -xzf /tmp/distributed-esphome-addon.tar.gz"
```

Then in HA: **Settings → Add-ons → Local add-ons → ESPHome Distributed Build Server → Install**.
</details>

### Standalone Server (Docker)

If you don't use Home Assistant, you can run the server as a standalone Docker container:

```bash
docker run -d \
  --name distributed-esphome-server \
  --network host \
  -v /path/to/esphome/configs:/config/esphome \
  -v esphome-dist-data:/data \
  -e SERVER_TOKEN=your-secret-token \
  ghcr.io/weirded/esphome-dist-server:latest
```

The web UI is available at `http://your-host:8765`.

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `ESPHOME_CONFIG_DIR` | `/config/esphome` | Path to ESPHome YAML configs inside the container |
| `SERVER_TOKEN` | auto-generated | Shared secret for build client auth |
| `PORT` | `8765` | HTTP port |
| `JOB_TIMEOUT` | `600` | Compile timeout in seconds |
| `OTA_TIMEOUT` | `120` | OTA upload timeout in seconds |
| `CLIENT_OFFLINE_THRESHOLD` | `30` | Seconds before a client is considered offline |
| `DEVICE_POLL_INTERVAL` | `60` | How often to poll device firmware versions (seconds) |

> **Note:** `--network host` is required for mDNS device discovery. The `/data` volume persists the job queue and auto-generated auth token across restarts.

### 2. Configure the Add-on

| Option | Default | Description |
|--------|---------|-------------|
| `token` | `""` | Shared secret for build client auth (leave empty to auto-generate) |
| `job_timeout` | `600` | Compile timeout in seconds |
| `ota_timeout` | `120` | OTA upload timeout in seconds |
| `client_offline_threshold` | `30` | Seconds before a client is considered offline |
| `device_poll_interval` | `60` | How often to poll device firmware versions (seconds) |

### 3. Add Remote Build Clients (optional)

The Web UI shows a **Docker run** command pre-filled with your server URL and token. You can copy it directly or use the packaging script to build a self-contained archive:

```bash
# Build archive (outputs dist/esphome-dist-client-<version>.tar.gz)
./package-client.sh http://your-ha-host:8765 your-token

# Deploy to another Docker host
scp dist/esphome-dist-client-0.0.1.tar.gz user@build-host:/tmp/
ssh user@build-host "cd /tmp && tar -xzf esphome-dist-client-0.0.1.tar.gz"

# On the build host — start (tails logs; Ctrl-C detaches, container keeps running)
SERVER_URL=http://your-ha-host:8765 SERVER_TOKEN=your-token ./start.sh

# Or start detached
SERVER_URL=http://your-ha-host:8765 SERVER_TOKEN=your-token ./start.sh --background
```

The archive contains three scripts:

| Script | What it does |
|--------|-------------|
| `start.sh` | Loads image (if needed), starts container, tails logs. `--background` to detach. Fails immediately if `SERVER_URL` or `SERVER_TOKEN` are unset. |
| `stop.sh` | Stops and removes the container. |
| `uninstall.sh` | Stops container, removes image, optionally removes the `esphome-versions` volume. |

> **Note:** Build clients must have network access to your ESP devices (same LAN or VLAN) to push firmware via OTA.

## Web UI

Access via the HA sidebar (**ESPH Distributed**) or directly at `http://your-ha-host:8765`.

Three tabs — works on mobile and small laptop screens:

- **Devices** — all discovered ESPHome YAML configs with mDNS device status (online/offline, running version); "config changed" indicator when the YAML has been modified since the last compile; compile individual, all, or only outdated ones; inline YAML editor
- **Queue** — live job status with logs; retry failed jobs (including OTA failures), cancel in-progress jobs; badge shows active/failed count
- **Clients** — connected build workers with online status, current job per slot, version, and system info (CPU arch, core count, memory, OS version, CPU model, uptime); enable/disable clients; remove offline clients; **+ Connect Client** button opens a pre-filled `docker run` command

## How It Works

1. The server scans `/config/esphome/*.yaml` on HA for compilable targets (re-scans every 30s for changes)
2. When you trigger a compile, one job per YAML is added to the queue
3. Build clients poll `GET /api/v1/jobs/next` every 5 seconds
4. On claiming a job, the client receives the full ESPHome config directory as a `tar.gz` bundle (including `secrets.yaml`)
5. The client ensures the required ESPHome version is installed (LRU cache, max 3 versions), compiles, then pushes firmware via OTA directly to the device
6. Results (compile log, OTA outcome) are posted back to the server
7. The server's device poller picks up the new firmware version via mDNS + native API within the next poll cycle

### Job State Machine

```
PENDING → ASSIGNED → RUNNING → SUCCESS
                   ↘          ↘ FAILED
                    ↖ TIMED_OUT (up to 3 retries, then permanent FAILED)
```

- **PENDING** → **ASSIGNED**: a client worker claims the job
- **ASSIGNED** → **RUNNING**: client starts the compile subprocess
- **RUNNING** → **SUCCESS**: compile + OTA completed
- **RUNNING/ASSIGNED** → **TIMED_OUT**: deadline exceeded; re-enqueued as PENDING (up to 3 retries, then permanent FAILED)
- Any state → **FAILED**: compile error, OTA failure after retries, or user cancel

On server restart, any `ASSIGNED`/`RUNNING` jobs reset to `PENDING`. Triggering a new compile for a target automatically removes any old terminal (success/failed) jobs for that target.

### Client Auto-Update

Clients check the server's `server_client_version` on every heartbeat. If the server is running a newer client version, the client downloads the updated code and restarts itself in-place (`os.execv`). Updates only apply when the client is idle (not mid-job). After 3 failed update attempts the circuit breaker trips and no more updates are tried until the container restarts.

### ESPHome Version Management

Each client maintains a cache of ESPHome virtualenvs under `/esphome-versions/<version>/`. At most 3 versions are kept on disk (LRU eviction). Mount `/esphome-versions` as a Docker volume to persist installs across container restarts.

`ESPHOME_SEED_VERSION` pre-installs a specific version at startup so the first job doesn't wait for a fresh install.

## Client Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_URL` | required | e.g. `http://homeassistant.local:8765` |
| `SERVER_TOKEN` | required | Shared auth token |
| `POLL_INTERVAL` | `5` | Seconds between job polls when idle |
| `HEARTBEAT_INTERVAL` | `10` | Seconds between heartbeats |
| `JOB_TIMEOUT` | `600` | Compile timeout in seconds |
| `OTA_TIMEOUT` | `120` | OTA upload timeout in seconds |
| `MAX_ESPHOME_VERSIONS` | `3` | Max cached ESPHome versions on disk |
| `MAX_PARALLEL_JOBS` | `2` | Concurrent build workers per client |
| `HOSTNAME` | system hostname | Worker name shown in UI |
| `ESPHOME_SEED_VERSION` | — | Pre-install this ESPHome version at startup |
| `ESPHOME_BIN` | — | Use this binary instead of the version-manager venvs |
| `HOST_PLATFORM` | — | Override detected OS in UI (e.g. `macOS 15.3 (Apple M1 Pro)`) — useful when running Docker on non-Linux hosts |
| `PLATFORMIO_CORE_DIR` | — | No longer needed — each slot automatically uses `$ESPHOME_VERSIONS_DIR/pio-slot-N/` |

## Security Considerations

This add-on is designed for **trusted home networks** and makes deliberate trade-offs that favour simplicity and ease of use over defence-in-depth. If you run this on an untrusted or shared network, be aware of the following:

### Shared auth token

A single Bearer token authenticates all build clients. The Web UI displays this token in the "Connect Client" modal so you can copy-paste it. Anyone with access to the HA UI (or the direct port) can see the token.

### Plaintext HTTP

All communication between the server and build clients is unencrypted HTTP. The auth token, ESPHome configs (including `secrets.yaml`), and firmware bundles are transmitted in the clear. On a typical home LAN this is acceptable; on a shared or untrusted network, consider tunnelling traffic through a VPN or reverse proxy with TLS.

### secrets.yaml included in every build bundle

When a client claims a job, it receives a tarball of the entire ESPHome config directory — including `secrets.yaml`. This is necessary because ESPHome compilation requires access to substituted secrets. Every build client you connect will have access to your Wi-Fi passwords, API keys, and OTA passwords.

### Client auto-update

Build clients automatically download updated Python code from the server and restart themselves. This makes upgrades seamless but means a compromised server (or a man-in-the-middle on the HTTP connection) could push arbitrary code to all connected clients. The auto-update only runs when clients are idle.

### UI API relies on HA Ingress for authentication

The `/ui/api/*` endpoints have no built-in authentication — they trust that Home Assistant's Ingress proxy has already authenticated the user. If port 8765 is accessible directly (bypassing HA), anyone on the network can manage the queue, read build logs, and edit YAML configs without credentials.

### Network access requirements

Build clients need direct network access to your ESP devices (for OTA on ports 3232/8266). The server needs to be reachable by all clients. Ensure your firewall rules accommodate this.

For a detailed analysis, see [SECURITY_AUDIT.md](SECURITY_AUDIT.md).

## Development

### Run Tests

```bash
pip install pytest pytest-asyncio aiohttp aioesphomeapi zeroconf requests
pytest tests/
```

### Run the Server Locally

```bash
ESPHOME_CONFIG_DIR=/path/to/esphome/configs PORT=8765 SERVER_TOKEN=dev-token \
  python ha-addon/server/main.py
```

### Run a Client Locally

```bash
SERVER_URL=http://localhost:8765 SERVER_TOKEN=dev-token python ha-addon/client/client.py
```

### Build Docker Images

```bash
# Server image (HA add-on — requires BUILD_FROM arg)
docker build -t esphome-dist-server ha-addon/

# Server image (standalone)
docker build -f ha-addon/Dockerfile.standalone -t esphome-dist-server ha-addon/

# Client image (auto-detects host arch; pass explicit platform if needed)
docker build -t esphome-dist-client ha-addon/client/
# ARM64 (Apple Silicon, Raspberry Pi 4+):
docker buildx build --platform linux/arm64 --load -t esphome-dist-client ha-addon/client/
```

### Package the HA Add-on

```bash
tar -czf distributed-esphome-addon.tar.gz -s '/^ha-addon/distributed-esphome/' ha-addon
```

### Bump Version

```bash
bash scripts/bump-version.sh 0.0.X
```

Updates `ha-addon/VERSION`, `ha-addon/config.yaml`, and `ha-addon/client/client.py` atomically.

## Repository Layout

```
distributed-esphome/
├── ha-addon/
│   ├── config.yaml           # HA add-on manifest (version: must match VERSION)
│   ├── Dockerfile            # HA add-on image (uses BUILD_FROM base)
│   ├── Dockerfile.standalone # Standalone server image (python:3.11-slim base)
│   ├── VERSION               # Single source of truth for the version number
│   ├── DOCS.md               # Documentation tab in HA UI
│   ├── CHANGELOG.md          # Changelog tab in HA UI
│   ├── translations/en.yaml  # Config option labels for HA UI
│   ├── build.yaml            # Multi-arch base image mapping
│   ├── client/               # Build client code (also used for standalone Docker image)
│   │   ├── Dockerfile
│   │   ├── client.py         # Main loop, heartbeat, job runner, auto-update
│   │   ├── version_manager.py # ESPHome version install/eviction (LRU)
│   │   └── dist-scripts/     # start.sh / stop.sh / uninstall.sh + PowerShell variants
│   └── server/
│       ├── main.py           # aiohttp app, middleware, background tasks
│       ├── api.py            # /api/v1/* — client REST API (Bearer token auth)
│       ├── ui_api.py         # /ui/api/* — browser JSON API (Ingress auth)
│       ├── app_config.py     # Centralised configuration (AppConfig dataclass)
│       ├── job_queue.py      # Job state machine, persistence
│       ├── scanner.py        # YAML discovery, bundle generation
│       ├── registry.py       # Build client registry
│       ├── device_poller.py  # mDNS listener + aioesphomeapi polling
│       └── static/index.html # Single-file Web UI (tab layout)
├── scripts/
│   ├── bump-version.sh       # Update version in all 3 places atomically
│   ├── install-hooks.sh      # Configure git to use .githooks/
│   └── ...
├── .githooks/pre-push        # Runs tests + mypy before every push
├── .github/workflows/ci.yml            # GitHub Actions: tests + mypy on every push/PR
├── .github/workflows/publish-server.yml # Publish standalone server image to GHCR
├── .github/workflows/publish-client.yml # Publish client image to GHCR
├── package-client.sh         # Build + package client Docker image for distribution
└── REQUIREMENTS.md           # Full design specification
```

## Versioning

The version lives in three places that must stay in sync — use `bash scripts/bump-version.sh X.Y.Z` to update all three atomically:

1. `ha-addon/VERSION` — read by the server at runtime
2. `ha-addon/config.yaml` — required by the HA add-on manifest
3. `ha-addon/client/client.py` — `CLIENT_VERSION` constant (checked against server on heartbeat)

## Platform Support

Both the HA add-on (server) and standalone build clients support **x86-64 and ARM** architectures:

- The HA add-on runs on `aarch64`, `amd64`, `armhf`, `armv7`, and `i386` (declared in `ha-addon/config.yaml`).
- The build client Docker image is a standard Python image that builds natively for any architecture. On **Apple Silicon** (`linux/arm64`) builds run natively — no Rosetta emulation — which can be significantly faster than cross-compiling on an x86 machine.

```bash
# Build a native ARM64 client image (e.g. on Apple Silicon or Raspberry Pi 4)
docker buildx build --platform linux/arm64 --load -t esphome-dist-client ha-addon/client/

# Package and distribute an ARM64 client archive
./package-client.sh http://your-ha-host:8765 your-token linux/arm64
```
