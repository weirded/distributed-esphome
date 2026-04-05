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
- `job_queue.py` — In-memory job queue persisted to `/data/queue.json`. Jobs time out and retry up to 3 times before permanently failing.
- `scanner.py` — Discovers `.yaml` targets in `/config/esphome/` (excluding `secrets.yaml` from the target list but including it in bundles). `create_bundle()` produces a tar.gz of the full config directory.
- `registry.py` — In-memory build worker registry (`WorkerRegistry`); workers are considered online if last heartbeat was within 30s.
- `device_poller.py` — Discovers ESPHome devices via `_esphomelib._tcp` mDNS, polls them every 60s via `aioesphomeapi` for running firmware version and compilation time. Maps devices to YAML targets using a name map built from parsed `esphome.name` fields (handles cases where filename differs from device name).
- `api.py` — Worker REST API: register, heartbeat, claim job (`GET /api/v1/jobs/next` returns base64 tar.gz bundle), submit result. Both `/api/v1/workers/*` (new) and `/api/v1/clients/*` (legacy) routes are supported.
- `ui_api.py` — Browser JSON API: targets, devices, workers, queue state, compile trigger, cancel. Both `/ui/api/workers/*` (new) and `/ui/api/clients/*` (legacy) routes are supported.
- `static/` — Vite-built React app output. Source is in `ha-addon/ui/` (React + TypeScript + Tailwind + shadcn/ui). Build: `cd ha-addon/ui && npm run build`.

### Worker (`ha-addon/client/`)

The worker binary (`client.py`) is a synchronous polling loop with a background heartbeat thread. It registers with the server, polls for jobs, ensures the correct ESPHome version is installed (`VersionManager`), extracts the config bundle, runs `esphome run`, and submits results.

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

## Branching & Release Process

**Branches:**
- `develop` — default working branch. All development happens here.
- `main` — stable releases only. Users install from this branch.

**Day-to-day development (on `develop`):**
- Bump the dev version after each turn: `bash scripts/bump-dev.sh` (auto-increments `-dev.N`)
- Push to GitHub freely — CI runs tests, no GHCR images published
- Deploy to hass-4 for testing: `./push-to-hass-4.sh`

**Stable releases (merge to `main`):**
Follow `RELEASE_CHECKLIST.md` for the full step-by-step process. Key steps:
- Use `bash scripts/bump-version.sh X.Y.Z` for the stable version
- Finalize `ha-addon/CHANGELOG.md` — consolidate dev changes into a clean release entry
  (use `WORKITEMS.md` and `BUGS.md` as source material, group by category)
- Update `README.md` and `ha-addon/DOCS.md` — ensure they accurately describe the current feature set, configuration options, and setup instructions
- The pre-push hook enforces a changelog entry when pushing to `main`
- Tag the release: `git tag vX.Y.Z && git push origin vX.Y.Z`
- GHCR images are published automatically on push to `main`

**Changelog is NOT updated during development on `develop`.** The WORKITEMS.md and BUGS.md files track progress with version numbers. The changelog is written once at release time.

## Documentation

When adding new features, changing configuration options, or modifying user-visible behavior, keep these docs in sync with the implementation:

- `README.md` — public-facing project overview, installation, architecture, configuration tables, and repository layout
- `ha-addon/DOCS.md` — user-facing documentation shown in the Home Assistant add-on panel

## Frontend (`ha-addon/ui/`)

React + TypeScript + Vite app. Build output goes to `ha-addon/server/static/`.

```bash
cd ha-addon/ui && npm run build    # production build
cd ha-addon/ui && npx vite         # dev server
```

**Stack:** React 19, Vite 8, TypeScript 5.9, Tailwind v4 (with preflight), shadcn/ui (Base UI primitives).

**Key patterns:**
- **shadcn components** in `src/components/ui/` — Dialog, DropdownMenu, Button, Badge, Checkbox, Sonner toast. Use these for all new interactive UI.
- **CSS variables** in `src/theme.css` — app theme (`--bg`, `--surface`, `--border`, `--text`, `--accent`, etc.) mapped to shadcn variables. Both dark and light modes via `[data-theme="light"]`.
- **Shared utilities** in `src/utils.ts` (`timeAgo`, `stripYaml`, `getJobBadge`, etc.) and `src/utils/terminal.ts` (terminal copy/download helpers).
- **StatusDot** component for online/offline/checking/paused indicators.
- **Polling** via `setInterval` in App.tsx (devices 15s, workers 5s, queue 3s). State lives in App.tsx, passed down as props.
- **API client** in `src/api/client.ts` — all server calls, auto-reload on version change.

**Path alias:** `@/*` maps to `src/*` (configured in tsconfig + vite.config).

## Design Principles

- **Use library components as intended.** When using shadcn/ui, Tailwind, or any library, leverage their built-in functionality rather than disabling features and reimplementing them. If a library component doesn't fit, adapt our code to work with it — don't strip and replace it.
- **Prefer composition over override.** Adjust layout/spacing to accommodate library behavior rather than adding `showCloseButton={false}` and rolling a custom close button.

## Project Tracking

- `WORKITEMS.md` — feature roadmap organized by release, with checkboxes
- `BUGS.md` — numbered bug log with status (FIXED/IN PROGRESS/INVESTIGATING) and version tags
- `RELEASE_CHECKLIST.md` — step-by-step release process (what Claude does vs. what the human does)
- `PRD.md` — product requirements document for the full ESPHome dashboard replacement
