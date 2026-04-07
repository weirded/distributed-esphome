# Work Items — 1.3.0 (current release)

Theme: **Harden the codebase.** Fill test coverage gaps, add CI, clean up Python code, add Playwright browser tests, and add ESPHome build integration tests. No new user features — focus on reliability and preventing regressions.

## ESPHome Build Integration Tests

Fixture YAML configs that cover every supported ESPHome platform/framework combination. Run actual `esphome compile` in CI and on the local worker to catch toolchain/dependency regressions early (like the Alpine glibc issues in 1.2.0).

- [x] **BT.1 Fixture configs** *(1.3.0-dev.1)* — 16 minimal compilable YAML fixtures in `tests/fixtures/compile_targets/` covering ESP8266, ESP32 (Arduino + IDF), ESP32-S2/S3/C3/C6 (IDF), RP2040, BK72xx, RTL87xx, plus complex configs (external components, packages, Bluetooth Proxy, Thread)
- [x] **BT.2 Docker compile test script** *(1.3.0-dev.1)* — `scripts/test-compile.sh` (host) and `scripts/test-compile-docker.sh` (Docker client + server images)
- [x] **BT.3 Local worker compile test** *(1.3.0-dev.1)* — `test-compile-docker.sh --server-only` validates the python:3.11-slim server image
- [x] **BT.4 CI integration** *(1.3.0-dev.1)* — `.github/workflows/compile-test.yml`: 16-target client matrix + 4-target server matrix with PlatformIO caching

## Python Test Suite

117 existing tests. Main gaps: api.py, ui_api.py, main.py have low coverage.

- [x] **T.0 Fix test anti-patterns** *(1.3.0-dev.3)* — removed redundant sys.path from 7 files, replaced hardcoded /tmp with tmp_path, converted test_queue.py to native async tests (167 tests total)
- [x] **T.1 Auth middleware tests** *(1.3.0-dev.1)* — 13 tests in `tests/test_auth.py`: Bearer token, Ingress trust, dev bypass
- [x] **T.2 Worker API tests** *(1.3.0-dev.1)* — 37 tests in `tests/test_api.py`: registration, heartbeat, scheduling, pinned jobs, result submission
- [ ] **T.3 UI API tests** (~23) — targets, compile, config CRUD, rename, queue management
- [ ] **T.4 Extend existing module tests** (~15) — scanner metadata, queue pinning, poller cache

## Playwright Browser Tests

End-to-end testing of the web UI using Playwright.

- [x] **PW.1 Playwright setup** *(1.3.0-dev.5)* — `@playwright/test`, Vite preview server, route-intercepted mock API
- [x] **PW.2 Smoke tests** *(1.3.0-dev.5)* — 10 tests: page load, header, all tabs, tab counts, version badge
- [x] **PW.3 Device tab interactions** *(1.3.0-dev.5)* — 5 tests: search/filter, editor modal, theme toggle, upgrade button
- [x] **PW.4 Queue tab interactions** *(1.3.0-dev.5)* — 4 tests: state badges, search, log modal, worker hostname
- [x] **PW.5 Workers tab interactions** *(1.3.0-dev.5)* — 5 tests: hostnames, connect modal, system info
- [ ] **PW.6 Editor modal** — open, edit YAML, save, validate, dirty state warning
- [ ] **PW.7 Theme and responsiveness** — dark/light toggle, narrow viewport behavior

## CI / GitHub Actions

- [x] **CI.1 Run E2E tests in CI** *(1.3.0-dev.1)* — `.github/workflows/ci.yml` runs full test suite (removed `--ignore` filters)
- [x] **CI.2 Add test coverage reporting** *(1.3.0-dev.7)* — `pytest-cov` with term-missing + HTML artifact upload (42% baseline)
- [x] **CI.3 Add ruff linting** *(1.3.0-dev.7)* — `ruff check` on server + client code in CI; fixed 6 lint errors (unused imports, ambiguous vars)
- [x] **CI.4 Add frontend build+lint job** *(1.3.0-dev.1)* — `frontend` job in CI: `npm ci && npm run build`
- [x] **CI.5 Run Playwright tests in CI** *(1.3.0-dev.7)* — Chromium install + `playwright test` in frontend job, failure artifacts uploaded

## Python Codebase Cleanup

- [x] **PY.1 Server DRY cleanup** *(1.3.0-dev.1)* — `helpers.py` with `safe_resolve()`, `json_error()`, `constant_time_compare()`, `clamp()`; replaced 14 inline path checks + 68 error responses
- [x] **PY.2 Client cleanup** *(1.3.0-dev.1)* — extracted `sysinfo.py` (245 lines), added debug logging to 10 silent exceptions, tarfile filter fallback for Python <3.12
- [x] **PY.3 Version manager thread safety** *(1.3.0-dev.1)* — `wait_event.wait()` with 600s timeout, disk space auto-eviction with `keep_version` parameter
- [x] **PY.4 Consistency & polish** *(1.3.0-dev.10)* — added CLAUDE.md guidelines for batch toasts, UX review, and quality standards
- [x] **PY.5 Extract magic strings to constants** *(1.3.0-dev.10)* — `constants.py` with HA_SUPERVISOR_IP, header names, SECRETS_YAML; updated api.py, main.py, scanner.py, ui_api.py
- [x] ~~**PY.6 Extract magic strings to constants (UI)**~~ — dropped; UI strings are each used in one place, extracting adds indirection without benefit

## Client Library Adoption

LIB.1 requires a new Docker image (`psutil` needs C compilation). LIB.0 adds detection so the server/UI warns when the worker image is too old.

- [ ] **LIB.0 Client image version detection** — `IMAGE_VERSION` baked into Docker image, `MIN_IMAGE_VERSION` on server, heartbeat gates auto-update, UI warning badge
- [ ] **LIB.1 `psutil` for client system info** — replace ~200 lines of /proc/cpuinfo parsing with cross-platform API

## Security Hardening

- [x] **SEC.1 Timing-safe token comparison** *(1.3.0-dev.1)* — `constant_time_compare()` in `helpers.py`, used in auth middleware and `api.py`
- [x] **SEC.2 Bounded log storage** *(1.3.0-dev.6)* — `append_log()` caps `_streaming_log` at 512 KB per job, truncates with marker, silently drops further appends
- [x] **SEC.3 Validate max_parallel_jobs on registration** *(1.3.0-dev.1)* — `clamp()` in `helpers.py`, bounds 0-32 in `api.py` worker registration

## Quality Gates (CLAUDE.md)

Capstone for the 1.3 release: codify the standards established by all the above work into CLAUDE.md so future releases don't regress.

- [ ] **QG.1 Codify quality standards in CLAUDE.md** — document enforceable rules covering: constants over magic strings, test coverage requirements for new code, ruff/lint compliance, error handling patterns, naming conventions, frontend TypeScript standards, and any other conventions established during 1.3 cleanup. This is the last 1.3 task — written after everything else lands so it reflects the actual state of the codebase.

## Unmanaged Devices

- [x] **6.8 Hide/remove unmanaged devices** *(1.3.0-dev.8)* — "Show unmanaged devices" toggle in column picker gear dropdown, persisted to localStorage

## Queue UX

- [x] **6.7 Default queue sort by time** *(1.3.0-dev.8)* — default sort changed to `created_at` descending; added sortable Time column to queue table

## Build Management

- [x] **5.1 Clean build artifacts** *(1.3.0-dev.8)* — "Clean Cache" button on online workers, dispatched via heartbeat, worker clears esphome-versions directory

---

## Bugs & Tweaks

- [x] **#159** *(1.3.0-dev.4)* — Duplicate device rows for configs with hyphens in esphome.name. (GitHub issue #2) Root cause: ESPHome normalizes device names for mDNS — hyphens become underscores. `_map_target()` did exact string comparison. Fix: added hyphen/underscore normalization in `_map_target()` (tries normalized lookup on both name_to_target map and filename stems) and `build_name_to_target_map()` (adds underscore-normalized variant of hyphenated names to the map).
- [x] **#160** *(1.3.0-dev.4)* — OTA diagnostics reports wrong device name. (GitHub issue #15) Root cause: `_ota_network_diagnostics()` used a naive regex matching the first `name:` in the YAML (e.g. a neopixel light). Fix: replaced regex with yaml.safe_load to extract esphome.name properly, with a fallback that only looks under the esphome: block.
- [x] **#161** *(1.3.0-dev.4)* — Hamburger menu drops off-screen when opened near bottom-right corner. Fix: added viewport boundary detection via callback ref — flips menu upward when it would extend below viewport, and removes translateX(-100%) when menu would extend past the left edge.
- [x] ~~**#162**~~ DUPLICATE of #161 — hamburger menu bottom-right corner issue. Already fixed in 1.3.0-dev.4.
- [x] ~~**#163**~~ WONTFIX — When the UI is open and a new upgrade is deployed, HA shows an "add-on is offline" dialog instead of the app reloading gracefully. This is HA Ingress behavior — the proxy intercepts the connection before our app can handle it. SWR already retries and the version-change detector triggers a reload once the server is back.
- [x] **#164** *(1.3.0-dev.9)* — "Upgrade on..." submenu drops off-screen when opened near viewport edge. Fix: added callback ref with viewport detection — opens to the right if insufficient space on the left, flips upward if extending below viewport.
- [x] **#165** *(1.3.0-dev.9)* — Clean Cache button layout broken (flex on td) and missing global button. Fix: removed flex from td, added "Clean All Caches" button in Workers tab header.
- [x] ~~**#166**~~ STALE — #163 marked WONTFIX, #164 fixed in 1.3.0-dev.9.
- [x] **#167** *(1.3.0-dev.10)* — Queue showed enqueue time twice (Device column + Time column). Removed timeAgo from Device column, added absolute HH:MM:SS with relative time below in Time column. Uses browser locale (inherits HA timezone).
- [x] **#168** *(1.3.0-dev.10)* — Retry button now shown for successful jobs too. Changed `isJobRetryable` to include all finished jobs (not just failed).
- [x] **#169** *(1.3.0-dev.10)* — Clean All Caches was generating one toast per worker. Fix: dedicated `handleCleanAllCaches` in App.tsx uses Promise.all with a single summary toast. Added CLAUDE.md guidelines about batching toasts and thinking about UX.
- [x] **#170** *(1.3.0-dev.10)* — Time column renamed to "Start Time". Added "Finish Time" column showing HH:MM:SS + duration for finished jobs, elapsed time for in-progress jobs. Added `finished_at` to Job type.
- [x] **#171** *(1.3.0-dev.15)* — Queue duration was wrong — used worker-side `duration_seconds` instead of wall-clock time. Fix: compute `finished_at - created_at` for finished jobs and `now - created_at` for in-progress jobs in the Finish Time cell.
- [x] ~~**#172**~~ REVERTED — `--no-logs` removal was reverted in #173 below. Sticking with `esphome run --no-logs`.
- [x] **#173** *(1.3.0-dev.16)* — Reverted #172. Restored `esphome run --no-logs` (single subprocess for compile+OTA, matches native ESPHome UI). The version-compat concern with `--no-logs` is acceptable; if it becomes a real problem later we'll add a fallback.
- [x] **#174** *(1.3.0-dev.16)* — Default queue sort changed back to State (working → pending → timed_out → failed → success). Time-based default from #6.7 was wrong default — running jobs are more important than newest. Time column is still sortable.
- [x] **#175** *(1.3.0-dev.16)* — Finish Time column now labels its duration: "Took 2m 14s" when finished, "Elapsed 45s" when in progress.


