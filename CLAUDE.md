# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Distributed ESPHome is a system that offloads ESPHome firmware compilation to remote machines. The server runs as a Home Assistant add-on, manages a job queue, and serves a web UI. Build workers run in Docker on remote machines, poll the server for jobs, compile firmware using ESPHome, and push firmware via OTA.

## Commands

### Run Tests
```bash
pytest tests/
```

### Run a Single Test File or Test
```bash
pytest tests/test_queue.py
pytest tests/test_client.py::TestVersionManager::test_lru_eviction
```

### Install Dependencies
```bash
pip install pytest pytest-asyncio aiohttp aioesphomeapi zeroconf requests
# Or from requirements files:
pip install -r ha-addon/server/requirements.txt
pip install -r ha-addon/client/requirements.txt
```

### Run the Server Locally
```bash
ESPHOME_CONFIG_DIR=/path/to/configs PORT=8765 SERVER_TOKEN=dev-token python ha-addon/server/main.py
```

### Run the Worker Locally
```bash
SERVER_URL=http://localhost:8765 SERVER_TOKEN=dev-token python ha-addon/client/client.py
```

### Build Docker Images
```bash
docker build -t esphome-dist-server ha-addon/
docker build -t esphome-dist-client ha-addon/client/
```

### Package the HA Add-on Tarball
Produces a tarball that untars directly to `distributed-esphome/` (ready to drop in HA's `addons/local/`):
```bash
tar -czf distributed-esphome-addon.tar.gz -s '/^ha-addon/distributed-esphome/' ha-addon
```

## Architecture

### Server (`ha-addon/server/`)

The server is an `aiohttp` async application with two authentication tiers:
- `/api/v1/*` — Bearer token auth for build workers
- `/ui/api/*` — HA Ingress trust (no worker auth) for the browser UI

**Component responsibilities:**
- `main.py` — App setup, auth middleware, background timeout checker (every 30s), HA Ingress compatibility (X-Ingress-Path header injection)
- `queue.py` — In-memory job queue persisted to `/data/queue.json`. State machine: `PENDING → ASSIGNED → RUNNING → SUCCESS/FAILED/TIMED_OUT`. Jobs time out and retry up to 3 times before permanently failing. On server restart, `ASSIGNED`/`RUNNING` jobs reset to `PENDING`.
- `scanner.py` — Discovers `.yaml` targets in `/config/esphome/` (excluding `secrets.yaml` from the target list but including it in bundles). `create_bundle()` produces a tar.gz of the full config directory.
- `registry.py` — In-memory build worker registry (`WorkerRegistry`); workers are considered online if last heartbeat was within 30s.
- `device_poller.py` — Discovers ESPHome devices via `_esphomelib._tcp` mDNS, polls them every 60s via `aioesphomeapi` for running firmware version and compilation time. Maps devices to YAML targets using a name map built from parsed `esphome.name` fields (handles cases where filename differs from device name).
- `api.py` — Worker REST API: register, heartbeat, claim job (`GET /api/v1/jobs/next` returns base64 tar.gz bundle), submit result. Both `/api/v1/workers/*` (new) and `/api/v1/clients/*` (legacy) routes are supported.
- `ui_api.py` — Browser JSON API: targets, devices, workers, queue state, compile trigger, cancel. Both `/ui/api/workers/*` (new) and `/ui/api/clients/*` (legacy) routes are supported.
- `static/index.html` — Single-file vanilla JS/CSS UI; no build step. Refresh rates: queue=3s, workers=5s, devices=15s.

### Worker (`ha-addon/client/`)

The worker binary (`client.py`) is a synchronous polling loop with a background heartbeat thread:
1. Registers with server → gets `client_id`
2. Background thread sends heartbeats every 10s
3. Main loop polls `GET /api/v1/jobs/next` every 5s
4. On job receipt: ensures ESPHome version is installed (`VersionManager`), extracts bundle to temp dir, runs `esphome compile`, then `esphome upload` for OTA, submits results, cleans up

`version_manager.py` maintains virtualenvs under `/esphome-versions/<version>/` with an LRU cache (default max 3 versions).

### Job Bundle Flow

When a worker claims a job, the server calls `scanner.create_bundle()` which tarballs the entire ESPHome config directory into a base64-encoded payload. The worker extracts this, compiles the specified target YAML, and sends firmware via OTA directly from the worker machine to the ESP device. This means **the worker must have network access to the ESP devices**.

### Configuration

Server config is loaded from `/data/options.json` (HA add-on) with environment variable fallbacks. Key env vars: `ESPHOME_CONFIG_DIR`, `SERVER_TOKEN`, `JOB_TIMEOUT` (600s), `OTA_TIMEOUT` (120s), `PORT` (8765).

Worker config is all via environment: `SERVER_URL`, `SERVER_TOKEN`, `POLL_INTERVAL` (5s), `JOB_TIMEOUT` (600s), `MAX_ESPHOME_VERSIONS` (3).

## Test Setup

`tests/conftest.py` adds `ha-addon/server` and `ha-addon/client` to `sys.path`. Tests use `asyncio_mode = auto` (configured in `pytest.ini`). Sample ESPHome YAML fixtures are in `tests/fixtures/esphome_configs/`.

## Deployment

`hass-4` refers to the local Home Assistant instance. Use the `push-to-hass-4.sh` script to deploy the add-on:
```bash
./push-to-hass-4.sh
```

## Release Process

Always bump the version number when pushing to GitHub, unless otherwise specified. Use `bash scripts/bump-version.sh X.Y.Z` to update all three places atomically.

**Every version bump MUST include a `ha-addon/CHANGELOG.md` entry.** Add a new `## X.Y.Z` section at the top with a brief description of what changed. If a section for the current version already exists, update it. The changelog is in reverse-chronological order. A pre-push hook enforces that a changelog entry exists for the current version.

## Design Specification

`REQUIREMENTS.md` is the authoritative design document covering the full API spec, job state machine behavior, bundle format, device polling details, and acceptance criteria.
