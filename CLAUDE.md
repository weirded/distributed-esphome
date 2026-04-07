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
- `job_queue.py` — In-memory job queue persisted to `/data/queue.json`. Job state machine: `PENDING → ASSIGNED → RUNNING → SUCCESS/FAILED`. Jobs time out and retry up to 3 times before permanently failing. On server restart, `ASSIGNED`/`RUNNING` jobs reset to `PENDING`.
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

Worker config is all via environment:

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_URL` | required | e.g. `http://homeassistant.local:8765` |
| `SERVER_TOKEN` | required | Shared auth token |
| `POLL_INTERVAL` | `5` | Seconds between job polls when idle |
| `HEARTBEAT_INTERVAL` | `10` | Seconds between heartbeats |
| `JOB_TIMEOUT` | `600` | Compile timeout in seconds |
| `OTA_TIMEOUT` | `120` | OTA upload timeout in seconds |
| `MAX_ESPHOME_VERSIONS` | `3` | Max cached ESPHome versions on disk |
| `MAX_PARALLEL_JOBS` | `2` | Concurrent build jobs per worker (0 = paused) |
| `HOSTNAME` | system hostname | Worker name shown in UI |
| `ESPHOME_SEED_VERSION` | — | Pre-install this ESPHome version at startup |
| `ESPHOME_BIN` | — | Use this binary instead of the version-manager venvs |
| `HOST_PLATFORM` | — | Override detected OS in UI (e.g. `macOS 15.3 (Apple M1 Pro)`) |

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
- **Bump the dev version at the end of every turn:** `bash scripts/bump-dev.sh` (auto-increments `-dev.N`). This is mandatory — never skip it.
- Push to GitHub freely — CI runs tests, no GHCR images published
- Deploy to hass-4 for testing: `./push-to-hass-4.sh`

**Stable releases (merge to `main`):**
Follow `dev-plans/RELEASE_CHECKLIST.md` for the full step-by-step process. Key steps:
- Use `bash scripts/bump-version.sh X.Y.Z` for the stable version
- Finalize `ha-addon/CHANGELOG.md` — consolidate dev changes into a clean release entry
  (use `dev-plans/WORKITEMS-X.Y.md` as source material — it has both the work items and the bug fixes for the release; group by category)
- Update `README.md` and `ha-addon/DOCS.md` — ensure they accurately describe the current feature set, configuration options, and setup instructions
- The pre-push hook enforces a changelog entry when pushing to `main`
- Tag the release: `git tag vX.Y.Z && git push origin vX.Y.Z`
- GHCR images are published automatically on push to `main`

**Changelog is NOT updated during development on `develop`.** The `dev-plans/WORKITEMS-X.Y.md` files track progress with version numbers (work items + bug fixes for each release). The changelog is written once at release time.

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

- **Default to shadcn/ui.** All new interactive UI (buttons, dialogs, dropdowns, inputs, etc.) must use shadcn/ui components. Don't hand-roll components that shadcn already provides.
- **Use library components as intended.** When using shadcn/ui, Tailwind, or any library, leverage their built-in functionality rather than disabling features and reimplementing them. If a library component doesn't fit, adapt our code to work with it — don't strip and replace it. Take the easy/intended path, not hacky workarounds.
- **Prefer composition over override.** Adjust layout/spacing to accommodate library behavior rather than adding `showCloseButton={false}` and rolling a custom close button.
- **Server state in SWR, UI state in React.** SWR is the cache for server data — read from it, don't copy it into `useState`. Lift state only as high as needed.
- **Shared TypeScript types for API responses.** Define types once for what the server returns and use them across components. No `any` or inline ad-hoc shapes.
- **Tailwind utility classes in JSX, not custom CSS.** Only use CSS files for things Tailwind can't express (animations, complex selectors). No `@apply`. Use `cn()` (shadcn merge utility) for conditional classes, not string concatenation.
- **One component per file, colocate related code.** Types, helpers, and constants used by a single component live near that component, not in a global utils grab-bag.
- **Semantic HTML.** `<button>` not `<div onClick>`, `<table>` for tabular data. shadcn handles much of this — don't undermine it with custom markup.
- **All API calls go through `api/client.ts`.** Components never call `fetch` directly.
- **Batch operations get one toast.** When an action affects multiple items (e.g. "clean all caches"), use `Promise.all` and show a single summary toast — never one toast per item. Bulk actions should be handled in App.tsx, not by iterating callbacks in child components.
- **Think about the UX.** Before shipping a UI change, mentally walk through it: does the layout make sense? Does it look right on the real dashboard with real data? Avoid `flex` on `<td>`, buttons that look like links, or anything that would look sloppy to a user.

## Project Tracking

All roadmap, release process, and bug tracking lives in `dev-plans/`:

- `dev-plans/README.md` — index of all the files
- `dev-plans/WORKITEMS-X.Y.md` — one file per release. Each file mixes feature work items (with checkboxes) and bug fixes (numbered, with FIXED/WONTFIX/etc. status). Bug numbers are global and monotonic across releases.
- `dev-plans/WORKITEMS-1.3.md` — **current release.** Open bugs go at the bottom under "Open Bugs", folded into the Bug Fixes list as they land.
- `dev-plans/PRD.md` — product requirements document for the full ESPHome dashboard replacement
- `dev-plans/SECURITY_AUDIT.md` — security audit findings (refer when making security-relevant changes)
- `dev-plans/RELEASE_CHECKLIST.md` — step-by-step release process (what Claude does vs. what the human does)

**Always update tracking files when completing work:**
- Both work items and bug entries use the same checkbox format: `- [x] **#NNN** *(X.Y.Z-dev.N)* — description` (where `#NNN` only applies to bugs).
- When a work item is done, check the box and add the specific version tag (e.g. `*(1.3.0-dev.7)*` — use the actual dev.N, not the generic `dev`).
- When a bug is fixed, check the box and add the version tag. For wontfix/duplicate/stale entries, use `~~**#NNN**~~ WONTFIX —` (strike-through bold ID + label).
- Do this immediately after the work is complete, not deferred to later.
