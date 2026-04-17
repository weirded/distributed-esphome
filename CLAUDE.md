# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project Overview

ESPHome Fleet (internally: `distributed-esphome`) manages fleets of ESPHome devices — offloads compilation to remote workers, schedules upgrades, pins versions per device, and organizes devices via tags. Runs as a Home Assistant add-on with a built-in local worker. Additional build workers run in Docker on remote machines, poll the server for jobs, compile firmware using ESPHome, and push firmware via OTA directly to ESP devices.

**Naming convention:** user-facing docs/UI/log lines say **"ESPHome Fleet"**. Code identifiers, the GitHub repo (`weirded/distributed-esphome`), Docker image names (`esphome-dist-server`, `esphome-dist-client`), the add-on slug (`esphome_dist_server`), Python module names, and the YAML comment marker (`# distributed-esphome:`) all keep their original `distributed_esphome` / `esphome-dist-*` form — changing those would force a migration on every existing install for no user benefit.

## Architecture

### Server (`ha-addon/server/`)

`aiohttp` async application with two authentication tiers:

- `/api/v1/*` — Bearer token auth for build workers (also accepts requests from the HA Supervisor IP).
- `/ui/api/*` — HA Ingress trust (no worker auth) for the browser UI.

Component responsibilities:

- `main.py` — app setup, auth middleware, background loops (timeout checker, HA entity poller, PyPI version refresher), HA Ingress `X-Ingress-Path` injection.
- `job_queue.py` — in-memory job queue persisted to `/data/queue.json`. State machine: `PENDING → WORKING → SUCCESS | FAILED | TIMED_OUT`. Jobs retry up to 3 times before permanent failure. On server restart, `WORKING` jobs reset to `PENDING`. Loader recovers gracefully from malformed/truncated queue files.
- `scanner.py` — discovers `.yaml` targets in `/config/esphome/`. `create_bundle()` produces a tar.gz of the full config directory (including `secrets.yaml`, needed for ESPHome's `!secret` resolution). **ESPHome is NOT bundled in the server Docker image (SE.1–SE.10).** At first boot, `ensure_esphome_installed()` lazy-installs the version reported by the HA ESPHome add-on into `/data/esphome-versions/<ver>/` via the shared `VersionManager`. The venv's `site-packages` is prepended to `sys.path` so `from esphome.* import ...` works; the binary at `<venv>/bin/esphome` is used by `/ui/api/validate`. Downstream callers (`_resolve_esphome_config`, `/ui/api/components`, validate) degrade gracefully while the install is in flight — 1–3 min on first boot; subsequent restarts are instant.
- `registry.py` — in-memory build worker registry (no persistence); workers are "online" if last heartbeat was within `worker_offline_threshold` seconds.
- `device_poller.py` — discovers ESPHome devices via `_esphomelib._tcp` mDNS, polls them via `aioesphomeapi` for running version.
- `api.py` — worker REST API (register, heartbeat, claim job, submit result, stream log). Parses every request body through the typed pydantic models in `protocol.py`.
- `ui_api.py` — browser JSON API (targets, devices, workers, queue, compile, cancel).
- `protocol.py` — **single source of truth** for server↔worker wire messages (pydantic v2). Byte-identical copy lives in `ha-addon/client/protocol.py`; a test enforces they match.
- `static/` — Vite-built React app output (source in `ha-addon/ui/`).

### Worker (`ha-addon/client/`)

`client.py` is a synchronous polling loop with a background heartbeat thread. Registers with the server, polls for jobs, ensures the correct ESPHome version is installed (`version_manager.py` — LRU cache of virtualenvs under `/esphome-versions/<version>/`), extracts the config bundle, runs `esphome run`, and submits results. Because the worker performs the OTA upload itself, **it must have network access to the ESP devices**.

`IMAGE_VERSION` (baked into the Docker image) and `MIN_IMAGE_VERSION` (in `ha-addon/server/constants.py`) gate the in-place source-code auto-update: the server refuses to push `.py` updates to workers whose Docker image is below `MIN_IMAGE_VERSION`, because a stale image can't be fixed by rewriting files in place.

### Job Bundle Flow

When a worker claims a job, the server calls `scanner.create_bundle()` which tarballs the ESPHome config directory into a base64 payload. The worker extracts this, compiles the target YAML, and OTA-flashes the firmware directly to the ESP device.

### Configuration

Server config is loaded from `/data/options.json` with environment variable fallbacks. Worker config is all via environment.

Key worker env vars:

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

## Commands

Scripts live in `scripts/`:

| Script | Purpose |
|--------|---------|
| `scripts/bump-dev.sh` | Increment `-dev.N` — **run at the end of every turn.** |
| `scripts/bump-version.sh X.Y.Z` | Set stable version for a release. |
| `scripts/check-invariants.sh` | Run the enforced-invariant grep linter (also runs in CI). |
| `./push-to-hass-4.sh` | Deploy to hass-4 and run the full prod Playwright smoke suite. |

Common dev commands:

- `pytest tests/` — full test suite.
- `ruff check ha-addon/server/ ha-addon/client/` — Python lint.
- `mypy ha-addon/server/ --ignore-missing-imports` / `mypy ha-addon/client/ ...` — type check.
- `cd ha-addon/ui && npm run build` — frontend build (`tsc -b && vite build`).
- `cd ha-addon/ui && npx playwright test` — 37-test mocked e2e suite.

See `dev-plans/RELEASE_CHECKLIST.md` for the full stable-release process.

## Test Setup

`tests/conftest.py` adds `ha-addon/server` and `ha-addon/client` to `sys.path`. `pytest.ini` sets `asyncio_mode = auto`. Sample ESPHome YAML fixtures live in `tests/fixtures/esphome_configs/`.

## Frontend (`ha-addon/ui/`)

React 19 + TypeScript 5.9 + Vite 8 + Tailwind v4 + shadcn/ui (Base UI primitives). Build output lands in `ha-addon/server/static/`. Path alias `@/*` → `src/*`.

- SWR polls workers/devices/queue at 1 Hz (state is cheap in-memory on the server side).
- All server calls live in `src/api/client.ts` (or siblings under `src/api/`). Components never call `fetch()` directly — enforced by `scripts/check-invariants.sh` rule UI-1.
- Shared types in `src/types/index.ts`. Playwright fixtures are typed against these so a field rename breaks tests.

## Enforced Invariants

Checked mechanically by `scripts/check-invariants.sh` (wired into the CI `test` job) or by pytest / mypy / ruff / the TS build. **Violating these fails CI.**

**UI-1 — No `fetch()` outside `src/api/`.** All HTTP calls go through the `api/` layer. Components never call `fetch()` directly.

**UI-2 — No Tailwind `@apply`.** Use utility classes in JSX. CSS files only for things Tailwind can't express (animations, complex selectors).

**UI-3 — No `any` type in new TS code.** Use `unknown` or a real type. Existing sanctioned uses (Monaco/xterm internals) are allow-listed with `// ALLOW_ANY: <reason>` inline.

**UI-4 — No `flex`/`inline-flex` on `<td>`.** Table cells must not be flex containers — it breaks table layout.

**UI-5 — Typed fixtures.** E2E Playwright fixtures in `ha-addon/ui/e2e/fixtures.ts` must import the runtime types from `src/types` so a field rename breaks the e2e build. (Enforced by `tsc -b` on the e2e project.)

**UI-7 — Icon-only buttons need both `aria-label` and `title`.** Icon controls carry no visible text, so screen readers need `aria-label` and sighted hover needs `title`. If you reach for one, add both — they're almost always the same string. Landed from UX.12 after the UX review (bug class: icons that hover-reveal no context, or lack accessible names).

**E2E-1 — No `page.waitForTimeout()` in Playwright specs.** Fixed sleeps are flake factories — CI is slower than your laptop, or the page state settles faster. Wait on an observable condition instead (`expect.poll`, `toBeVisible`, `toHaveCount(0)`, a route-interceptor counter, etc.). Landed from CR.6 after a 200ms sleep in `e2e-hass-4/cyd-office-info.spec.ts` was found flaking the prod-smoke suite on slow HA restarts.

**PY-1 — YAML goes through `yaml.safe_load`.** Never hand-rolled regex parsers for YAML content (regression source: #160, ESPHome device-name detection). The `_ota_network_diagnostics` regex fallback is allow-listed because it tries `safe_load` first.

**PY-2 — Every file that calls `subprocess.run`/`subprocess.Popen` must have a module-level `logger`.** The actual command line must also be logged before the subprocess runs (reviewed in PR; file-level logger presence is the grep-able floor). Bug sources: #176, #177, #180 — untriageable reports when the command line wasn't in the log.

**PY-3 — `esphome upload` invocations must not pass `--no-logs`.** That flag is `esphome run`-only. Direct regression guard for #177.

**PY-4 — Bump `IMAGE_VERSION` + `MIN_IMAGE_VERSION` when the worker Docker image changes.** System packages, Python version, `requirements.txt`, Dockerfile — any change to what `COPY`'d into the image (other than the auto-updatable `.py` source). A file-mtime check in `check-invariants.sh` warns if `requirements.txt` / `Dockerfile` is newer than `IMAGE_VERSION`. See the `1.3.1-dev.2` incident for why: the pydantic add-on broke every deployed worker because this wasn't bumped.

**PY-5 — No `# noqa`, `# type: ignore`, `eslint-disable`, or `@ts-ignore` without a comment explaining why.** Enforced by code review; if you're silencing a tool, fix the root cause instead.

**PY-6 — Pydantic models in `protocol.py` are the wire contract.** `ha-addon/server/protocol.py` and `ha-addon/client/protocol.py` must stay byte-identical (enforced by `tests/test_protocol.py::test_server_and_client_protocol_files_are_identical`). Every server-facing `/api/v1/*` handler parses its body through the typed model; workers build their requests from the typed model. New fields are additive + optional unless `PROTOCOL_VERSION` is bumped.

**PY-7 — Every `--ignore-vuln` must have an applicability assessment.** When adding a CVE ignore to `pip-audit` (or any audit tool), the inline comment must include: (1) why the fix version can't be pulled in (transitive bound, breaking change, etc.), (2) whether our code actually exercises the vulnerable code path, and (3) a date so staleness is visible. Don't just say "can't upgrade" — say whether the vulnerability matters for this codebase. If it does matter, track a follow-up in WORKITEMS rather than silently ignoring it.

**PY-8 — Every direct dep in `requirements.txt` must also appear in `requirements.lock`.** Dockerfiles install from the lockfile with `--require-hashes`, so anything present only in `requirements.txt` is silently missing from the image. Root cause of bug #39: `croniter` was added to `ha-addon/server/requirements.txt` but `scripts/refresh-deps.sh` was never rerun — the production image had no croniter, `schedule_checker` caught the `ImportError` and returned, and no scheduled upgrade ever fired in prod. `scripts/check-invariants.sh` now verifies the lockfile covers every entry in the .txt file.

**PY-9 — No macOS-only packages in `requirements.lock`.** `pyobjc-core`, `pyobjc-framework-*`, and `appnope` leak in as platform-conditional transitives when `pip-compile` is run on a Mac host (they should carry `sys_platform == "darwin"` markers but `pip-compile --generate-hashes` strips markers). The Linux Docker build then errors with `PyObjC requires macOS to build`. Happened twice (1.3.1-dev.9, 1.4.1-dev.55). Always regenerate lockfiles via `scripts/refresh-deps.sh`, which runs `pip-compile` inside a `python:3.11-slim` container on `linux/amd64`. `scripts/check-invariants.sh` greps the lock for the known macOS-package names and fails CI on any hit.

## Design Judgment (aspirational — reviewed, not enforced)

These aren't grep-checkable but matter just as much. They're how the codebase stays coherent.

- **Disable, don't fail.** When a feature isn't available for a target/worker/job (no restart button in YAML, no API key, worker offline, etc.), render the button or menu item **disabled with an explanatory tooltip** rather than letting the user click it and watch it fail. The tooltip should tell them what's missing and ideally how to fix it. Detect availability up-front from data we already have (YAML metadata, registry state) — don't probe by trying. **Exception: the Upgrade button is always enabled** regardless of device state, because compiling for a target is meaningful even if the device is offline (the firmware is still produced and OTA-pending). Origin: bug #14 — Restart was always clickable but silently no-op'd for devices whose YAML had no restart button.
- **Default to shadcn/ui.** All new interactive UI (buttons, dialogs, dropdowns, inputs, selects) uses the shadcn wrappers in `components/ui/`. Don't hand-roll components that already exist there. If shadcn doesn't have it yet, add a thin wrapper (see `components/ui/input.tsx`, `components/ui/select.tsx`).
- **Use library components as intended.** Prefer composition over override. Adjust layout to accommodate library behavior rather than stripping features.
- **Server state in SWR, UI state in React.** SWR is the cache — read from it, don't copy it into `useState`.
- **Lift DropdownMenu `open` state out of any row cell.** When a `<DropdownMenu>` lives inside a TanStack Table cell (Devices hamburger, Queue Download, etc.), the 1 Hz SWR poll re-instantiates the row's cell components and tears down any state kept *inside* the menu — the dropdown slams shut mid-click. Always control the menu with an `open` + `onOpenChange` prop where the state lives in the parent tab component (`useState<string | null>(null)` keyed by row id, so only one dropdown is open at a time), and add that state to the columns `useMemo` deps so cells re-render when it flips. Origin: bug #2 (devices hamburger, 1.4.1-dev.3) and bug #71 (queue Download dropdown, 1.5.0-dev.75). If the same symptom shows up on a third menu, fix it the same way — do not try to stop SWR from re-rendering.
- **One component per file, colocate related code.** Types/helpers/constants used by a single component live near that component, not in a global utils grab-bag.
- **Semantic HTML.** `<button>` not `<div onClick>`, `<table>` for tabular data.
- **Icons: Lucide only.** All UI icons come from `lucide-react`. No emoji glyphs (🕐 📅 📌), no HTML entities (`&#8942;`, `&#9881;`), no custom SVGs inline. Sized with Tailwind (`size-3`, `size-3.5`, `size-4`) to match the shadcn convention. Wrap icon-only buttons with `aria-label` (see QS.2); when the icon carries meaning beyond decoration (status indicator, stateful toggle), wrap in a `<span title="…">` so hover reveals the semantic.
- **Batch operations get one toast.** Bulk actions use `Promise.all` and a single summary toast — never one toast per item. Bulk actions live in `App.tsx`, not in child component loops.
- **Think about the UX before shipping.** Walk through the change mentally: does the layout make sense on real data? Would it look sloppy to a user?
- **Update `.gitignore` whenever a new tool is introduced.** Most tools generate cache/lock/build/report directories — add them in the same commit that introduces the tool.

## Performance Expectations

This is a home-lab tool used by one or two people intermittently, not a high-traffic web service. Optimize for **idle efficiency**, not peak throughput.

- **Idle is the default state.** When no user has the UI open and no compile is running, the server should be close to zero CPU. Background tasks (scheduler, device poller, entity poller, PyPI refresher) sleep on long intervals — don't add tight loops or frequent timers without justification. Log noise is a proxy for wasted work.
- **Active use can be expensive.** When a user is interacting with the UI or a compile is running, it's fine to do real work — scan configs, query devices, resolve YAML. Don't pre-compute or cache aggressively for a user who might not show up for days.
- **Be mindful of payload size.** Users access the UI over home networks that may be slow (VPN, remote access, mobile tethering). Enable gzip/deflate on the web server for JSON and static assets. Don't send large blobs (full job logs, firmware binaries) in polling responses — stream them on demand via WebSocket or separate endpoints. The 1Hz SWR polls should be small JSON; strip heavy fields (like `log`) from list endpoints and let the UI fetch them individually when a modal opens.
- **Don't over-optimize.** Shaving milliseconds off a response that runs once a second for one user is not worth the code complexity. Prefer simple, correct implementations over clever ones. If something is slow, measure before optimizing.

## Quality Standards (QG.1)

The bar for landing new code on `develop`. Most are automated; the rest are developer discipline.

### Automated gates (CI must be green)

1. **`pytest tests/`** with `pytest-cov` — full test suite.
2. **`ruff check ha-addon/server/ ha-addon/client/`** — Python lint, zero warnings.
3. **`mypy ha-addon/server/` and `mypy ha-addon/client/`** — type check, zero errors.
4. **`cd ha-addon/ui && npm run build`** — TypeScript + Vite production build.
5. **`cd ha-addon/ui && npm run test:e2e`** — 37-test mocked Playwright suite.
6. **`bash scripts/check-invariants.sh`** — the enforced invariants above.
7. **`.github/workflows/compile-test.yml`** — real `esphome compile` against 16 fixture YAMLs across platforms/frameworks.

### Manual gates (developer discipline)

1. **Test coverage for new code.** New module or significant function gets unit tests in the same commit. Bug fixes get a regression test that fails before the fix and passes after.
2. **E2E coverage for user-visible features.** New UI features get a mocked Playwright test in `e2e/` at minimum. Features touching the real compile path also get a test in `e2e-hass-4/`.
3. **Constants over magic strings.** When a string/header/path/threshold appears 2+ times, extract it. `ha-addon/server/constants.py` is the canonical home.
4. **Error handling at boundaries.** Use the helpers in `ha-addon/server/helpers.py` (`safe_resolve`, `json_error`, `clamp`, `constant_time_compare`). Every endpoint is a boundary.
5. **Update `dev-plans/WORKITEMS-X.Y.md` immediately after completing work.** Don't batch updates.
6. **Production smoke test after every turn.** `./push-to-hass-4.sh` is part of the dev loop, not a release-only step.

### What this is NOT

- No code style enforcement beyond ruff.
- No coverage target. Aim for tests that prove non-obvious behavior, not cosmetic coverage of trivial getters.
- No "comprehensive" PR templates. This is a single-developer project with an AI pair — keep the bar high, the process light.

## Documentation

When adding features or changing user-visible behavior, keep in sync:

- `README.md` — public project overview.
- `ha-addon/DOCS.md` — user-facing docs shown in the HA add-on panel.
- `ha-addon/CHANGELOG.md` — **written for users, not developers.** ~90% of the entry should cover things users see and experience (new UI features, UX improvements, bug fixes with user-visible symptoms, configuration changes). ~10% at most for internal/behind-the-scenes work (tests, CI, protocol types, code cleanup) — collapse into a brief "Under the hood" section, not detailed workstream breakdowns. Group by what the user experiences, not by internal workstream labels. Never say "no new features" when there are user-visible features — scan the WORKITEMS bug list for UI/UX work. **Only mention changes relative to the last public release** — if a bug was introduced during the dev cycle and fixed before release, it never existed from the user's perspective and doesn't belong in the changelog. Same for regressions, intermediate refactors, or test-only fixes that shipped and un-shipped within the same cycle. The changelog describes what changed *for the user upgrading from the previous stable*, not the full internal git history.

## Project Tracking

Everything lives in `dev-plans/`:

- `dev-plans/README.md` — index.
- `dev-plans/WORKITEMS-X.Y.md` — one file per release. Feature work items (checkboxes) + bug fixes (numbered). **Bug numbers are global and monotonic across releases** — never reset.
- `dev-plans/WORKITEMS-1.5.md` — current release (UI quality + rebrand + HA native integration; formerly in-flight as 1.4.1, renamed per #70).
- `dev-plans/archive/` — released WORKITEMS files from prior versions. Historical reference; don't edit.
- `dev-plans/SECURITY_AUDIT.md` — security audit findings.
- `dev-plans/RELEASE_CHECKLIST.md` — step-by-step release process.

**Turn** = one user prompt → one assistant response cycle. At the end of every turn:
1. Run `bash scripts/bump-dev.sh` — auto-increments `-dev.N`. Never skip.
2. Run `./push-to-hass-4.sh` for the prod smoke test.
3. **Check add-on logs for errors/warnings** after deploy: `ssh root@hass-4.local "ha addons logs local_esphome_dist_server" | grep -iE "ERROR|WARNING|Traceback|DeprecationWarning" | tail -20`. Fix any new issues before moving on. Warnings that existed before this turn can be noted but don't block.
4. Update `dev-plans/WORKITEMS-X.Y.md` immediately — check the box, add the specific dev.N tag. Don't batch.

**Work item / bug checkbox format:** `- [x] **#NNN** *(X.Y.Z-dev.N)* — description` (the `#NNN` only applies to bugs). Use the exact dev.N, not a generic `dev`. For wontfix/duplicate/stale entries, use `~~**#NNN**~~ WONTFIX —` (strike-through bold ID + label).

**Next release file:** Create `dev-plans/WORKITEMS-X.Y+1.md` immediately after tagging `vX.Y.Z` (part of the post-release checklist). The current file moves to `dev-plans/archive/` at the same time, and this file's "Project Tracking" section is updated to point at the new current release.

## Deployment

`hass-4` is the local Home Assistant instance. `./push-to-hass-4.sh` deploys the add-on, waits for the new version to report ready, and runs the full `e2e-hass-4` Playwright suite (real compile + OTA to `cyd-office-info`). Run after every turn.

**HA Core restart when the custom integration changes.** Changes under `ha-addon/custom_integration/` require a full `ha core restart` to take effect — the integration_installer copies new files to `/config/custom_components/` on add-on boot, but HA Core loads Python modules once at startup and doesn't hot-reload them. The add-on restart during deploy does NOT restart HA Core (Supervisor only restarts the add-on container). `push-to-hass-4.sh` hashes the integration directory and compares to a remote stamp file (`/tmp/esphome_fleet_integration.hash`); on a mismatch it runs `ha core restart` before the smoke suite. Skipped when the integration is byte-identical to the last push so non-integration turns don't pay the 30-60s restart cost.
