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
- [x] **T.3 UI API tests** *(1.3.0-dev.25)* — 36 tests in `tests/test_ui_api.py` covering server-info, targets listing, content GET/POST (+ path traversal rejection), archive/restore/permanent-delete, compile (all/specific/outdated/pinned/invalid), validate, rename, queue listing, retry (specific + all_failed), cancel, clear by state, remove by ID, workers list/set-parallel-jobs (with bounds check)/remove (online refused, offline ok)/clean-cache. `ui_api.py` coverage went from 12% → 50%.
- [x] **T.4 Extend existing module tests** *(1.3.0-dev.25)* — 12 new scanner tests (`get_device_metadata` for name/friendly_name/area/comment/project/web_server/substitutions; `build_name_to_target_map` for stem fallback, hyphen→underscore normalization, encryption key extraction, use_address overrides, empty-target case) + 11 new queue tests (pinned_client_id semantics + retry preservation, ota_only results, `update_status` status_text, `finished_at` on success/failure/pending). scanner.py 61% → 81%, job_queue.py 74% → 83%.

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
- [x] **CI.6 Publish Docker images from `develop`** *(1.3.0-dev.22)* — `publish-client.yml` and `publish-server.yml` now also trigger on pushes to `develop`. Added a rolling `develop` tag (enabled only on develop-branch pushes) alongside the existing version tag (e.g. `1.3.0-dev.22`) and sha tag. `latest` stays pinned to `main` via `enable={{is_default_branch}}`. Lets users point worker containers at `ghcr.io/weirded/esphome-dist-client:develop` to test unreleased changes without rebuilding locally.

## Python Codebase Cleanup

- [x] **PY.1 Server DRY cleanup** *(1.3.0-dev.1)* — `helpers.py` with `safe_resolve()`, `json_error()`, `constant_time_compare()`, `clamp()`; replaced 14 inline path checks + 68 error responses
- [x] **PY.2 Client cleanup** *(1.3.0-dev.1)* — extracted `sysinfo.py` (245 lines), added debug logging to 10 silent exceptions, tarfile filter fallback for Python <3.12
- [x] **PY.3 Version manager thread safety** *(1.3.0-dev.1)* — `wait_event.wait()` with 600s timeout, disk space auto-eviction with `keep_version` parameter
- [x] **PY.4 Consistency & polish** *(1.3.0-dev.10)* — added CLAUDE.md guidelines for batch toasts, UX review, and quality standards
- [x] **PY.5 Extract magic strings to constants** *(1.3.0-dev.10)* — `constants.py` with HA_SUPERVISOR_IP, header names, SECRETS_YAML; updated api.py, main.py, scanner.py, ui_api.py
- [x] ~~**PY.6 Extract magic strings to constants (UI)**~~ — dropped; UI strings are each used in one place, extracting adds indirection without benefit

## Client Library Adoption

LIB.1 requires a new Docker image (`psutil` needs C compilation). LIB.0 adds detection so the server/UI warns when the worker image is too old.

- [x] **LIB.0 Client image version detection** *(1.3.0-dev.17)* — `ha-addon/client/IMAGE_VERSION` file baked into the client Docker image (sits next to `client.py` via `COPY IMAGE_VERSION .`), reported in register payload. Server stores `worker.image_version`, has `MIN_IMAGE_VERSION` constant in `constants.py`, and in `/api/v1/workers/heartbeat` suppresses `server_client_version` for stale-image workers (returning `image_upgrade_required` + `min_image_version` instead) so they don't enter an auto-update loop against a broken image. `/api/v1/client/code` also returns 409 for stale workers. `/ui/api/server-info` exposes `min_image_version` for the UI. `WorkersTab` shows a red "image stale" badge next to the version. Client logs a one-time warning and stops setting `_update_available`. 7 new tests in `test_api.py`.
- [x] **LIB.1 `psutil` for client system info** *(1.3.0-dev.21)* — added `psutil>=5.9` to client requirements, rewrote `sysinfo.py` to use `psutil.virtual_memory()`, `psutil.cpu_percent()`, `psutil.disk_usage()`, and `psutil.cpu_count()`. Kept the CPU benchmark, `_get_os_version()` (distro detection via `/etc/os-release`), and `_get_cpu_model()` (CPU brand string via `/proc/cpuinfo`/sysctl) since psutil doesn't expose those. Cut the file from 245 → 217 lines and made it cross-platform (Windows support as a bonus). Primed `cpu_percent()` at module load so the first heartbeat returns a real value instead of 0.0. Bumped `IMAGE_VERSION` to "2" and `MIN_IMAGE_VERSION` to "2" — validates LIB.0 end-to-end: pre-dev.19 workers will show the "image stale" badge until they rebuild.

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

## Open Bugs

- [x] **#176** *(1.3.0-dev.23)* — (GitHub #22) `esphome run` was prompting interactively when the worker host had multiple upload targets (e.g. a USB serial dongle plus the OTA address). Worker has no stdin, so the job stalled / crashed at `choose_prompt`. Fix: `--device` is now ALWAYS passed on the `esphome run` call. When the server provides `ota_address` we use that; otherwise we pass the literal string `"OTA"` — ESPHome's `--device` help explicitly documents this as the way to "avoid the interactive prompt" and resolve via mDNS/DNS.
- [x] **#177** *(1.3.0-dev.23)* — (GitHub #21) The in-worker OTA retry path was invoking `esphome upload ... --no-logs`, which crashed with `unrecognized arguments: --no-logs`. Confirmed via `esphome run --help` / `esphome upload --help`: `run` accepts `--no-logs` (we need it so the worker doesn't hang tailing device logs after OTA), `upload` does NOT (it never tails logs). Fix: dropped `--no-logs` from the retry `upload_cmd`, kept it on the primary `run_cmd`. The retry-vs-recompile design is already correct — on OTA failure we call `esphome upload` (not `esphome run`) so compiled artifacts are reused from the build dir.
- [x] **#178** *(1.3.0-dev.8)* — (GitHub #19) Privacy/streamer mode now covers unmanaged devices. Unmanaged rows render IP with `className="sensitive"` (blurred by streamer CSS), and the 6.8 "Show unmanaged devices" toggle lets users hide them entirely. Pending release — issue stays open until 1.3 ships.
- [ ] **#179** — (GitHub #2, follow-up to #159) User still sees duplicate device rows after 1.1 hyphen fix. Sample YAML uses `packages: remote_package_files` from a GitHub URL with `generic-thread.yaml`. Need to reproduce with their config — possibly a remote-package / thread-device interaction the current name-mapping doesn't handle.
- [x] **#180** *(1.3.0-dev.23)* — Client now logs the full esphome command line before each invocation (`logger.info("Invoking: %s", " ".join(cmd))`). Covers validate, compile+OTA, and OTA retry paths. Useful for debugging command-line issues like #176/#177.
- [x] **#181** *(1.3.0-dev.23)* — "image stale" badge in the Workers tab is now a clickable button that opens the Connect Worker modal (the same UI that shows the latest `docker run` command). Tooltip explicitly recommends reinstalling the worker from that command instead of the vaguer "rebuild the image".


- [x] **#182** *(1.3.0-dev.24)* — Workers tab was showing "up 5m" even for offline workers, because `system_info.uptime` is the worker's self-reported process uptime from the last heartbeat (stale once offline). Fix: added `last_seen` to the `Worker` type (server already exposes it via `registry.to_dict()`), and the render now shows "offline for Xm" using `now - last_seen` when the worker is offline. Tooltip shows the absolute last-heartbeat timestamp. Online workers still show "up X".
- [x] **#183** *(1.3.0-dev.24)* — "Invoking: …" line from #180 was only going to the Python logger, not the user-visible streaming job log. Fix: new `_log_invocation(job_id, cmd)` helper calls both `logger.info()` and `_flush_log_text()` with a cyan-colored line so the command appears in the xterm log modal and gets included in bug report copy-pastes.
