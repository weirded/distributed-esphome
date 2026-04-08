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
- [x] **PW.6 Editor modal** *(1.3.0-dev.27)* — 6 tests in `e2e/editor.spec.ts`: clicking Edit opens Monaco; modal has Save / Validate / Save & Upgrade buttons; Save fires the content POST; Validate fires the validate POST; Save & Upgrade fires both save then compile; Escape closes the modal cleanly. Uses Playwright route interception to count API hits — verifies the actual contract, not just visual state.
- [x] **PW.7 Theme and responsiveness** *(1.3.0-dev.27)* — 7 tests in `e2e/theme-responsive.spec.ts`: theme toggle flips `data-theme` attribute, persists across reloads, streamer mode adds `.streamer` class. Narrow viewport (480×800): header + tabs visible, window-level horizontal scroll locked, `.table-wrap` is the scroll container. Desktop viewport (1920×1080): no horizontal scroll. Found and fixed a real responsive bug along the way: `.table-wrap` was missing `width: 100%` so its `overflow-x: auto` couldn't clip the table's `min-width: 500px`, and added `html, body { overflow-x: hidden }` so phones don't yank sideways on horizontal swipes.

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

- [x] **QG.1 Codify quality standards in CLAUDE.md** *(1.3.0-dev.30)* — added a "Quality Standards (QG.1)" section to CLAUDE.md splitting rules into automated CI gates (pytest+pytest-cov, ruff, mypy server+client, frontend tsc+vite build, mocked Playwright, 16-target compile matrix) and manual developer-discipline rules (test coverage for new code + regression tests for fixes; constants extracted when used in 2+ places via `helpers.py`/`constants.py`; no `# noqa`/`# type: ignore` without justification; immediate WORKITEMS updates with specific dev.N tags; bumping `IMAGE_VERSION`+`MIN_IMAGE_VERSION` in lockstep when the image changes; running the hass-4 prod smoke suite after every turn). Explicit "what this is NOT" carve-outs (no 100% coverage target, no PR templates, ruff is the only style enforcement) so the bar stays high without process bloat.

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
- [x] **#179** *(1.3.0-dev.28)* — (GitHub #2, follow-up to #159) Thread-only and static-IP devices were producing duplicate rows. Two root causes fixed:

  1. **`scanner.build_name_to_target_map` only honored `wifi.use_address`.** It ignored `ethernet.use_address`, `openthread.use_address`, and `{wifi,ethernet}.manual_ip.static_ip`. Thread-only devices and statically-IP'd devices had no proactive `Device` row, so any mDNS-discovered entry created a duplicate. **Fix:** added `get_device_address(config, device_name)` to scanner.py that mirrors ESPHome's `CORE.address` resolver — walks `wifi → ethernet → openthread` in order, each honoring `use_address` → `manual_ip.static_ip` → `{name}.local`. `build_name_to_target_map` now calls it for every target so `address_overrides` is populated for every YAML (even DHCP wifi falls back to `{name}.local`).

  2. **`device_poller._handle_service_change` parsed only IPv4.** It called `socket.inet_ntoa(info.addresses[0])` directly, which errors on the 16-byte AAAA records that Thread devices advertise via SRP/mDNS. The YAML row and the mDNS row never reconciled. **Fix:** new `_extract_address(info)` helper that prefers `info.parsed_addresses()` (modern python-zeroconf), falls back to manual `socket.inet_ntoa`/`inet_ntop` parsing, and prefers IPv4 when both are present. Plus a new `_find_existing_device_key(name)` that matches by hyphen/underscore-normalized name, so an mDNS-discovered `my_device` merges into a YAML-derived `my-device` row instead of duplicating. Both `_handle_service_change` and `update_compile_targets` now use this helper.

  **Tests:** 9 unit tests for `get_device_address` covering each network type × `use_address`/`manual_ip.static_ip`/default fallback + wifi-wins-over-ethernet precedence; 4 tests for `build_name_to_target_map` populating overrides for thread-only/static-ip/dhcp targets; 6 tests for `_extract_address` (parsed_addresses preferred, IPv4 preferred, IPv6 only, packed IPv4 fallback, packed IPv6 fallback, empty); 3 tests for `_find_existing_device_key` (exact, normalized, no-match) + 2 integration tests for `update_compile_targets` ensuring no duplicate when YAML and mDNS both fire. Plus 2 new fixture YAMLs (`tests/fixtures/esphome_configs/static_ip_device.yaml`, `thread_only_device.yaml`) and 3 fixture-based tests that exercise the same code path the production code uses.
- [x] **#180** *(1.3.0-dev.23)* — Client now logs the full esphome command line before each invocation (`logger.info("Invoking: %s", " ".join(cmd))`). Covers validate, compile+OTA, and OTA retry paths. Useful for debugging command-line issues like #176/#177.
- [x] **#181** *(1.3.0-dev.23)* — "image stale" badge in the Workers tab is now a clickable button that opens the Connect Worker modal (the same UI that shows the latest `docker run` command). Tooltip explicitly recommends reinstalling the worker from that command instead of the vaguer "rebuild the image".


- [x] **#182** *(1.3.0-dev.24)* — Workers tab was showing "up 5m" even for offline workers, because `system_info.uptime` is the worker's self-reported process uptime from the last heartbeat (stale once offline). Fix: added `last_seen` to the `Worker` type (server already exposes it via `registry.to_dict()`), and the render now shows "offline for Xm" using `now - last_seen` when the worker is offline. Tooltip shows the absolute last-heartbeat timestamp. Online workers still show "up X".
- [x] **#183** *(1.3.0-dev.24)* — "Invoking: …" line from #180 was only going to the Python logger, not the user-visible streaming job log. Fix: new `_log_invocation(job_id, cmd)` helper calls both `logger.info()` and `_flush_log_text()` with a cyan-colored line so the command appears in the xterm log modal and gets included in bug report copy-pastes.

- [x] **#184** *(1.3.0-dev.30)* — Devices tab now shows the IP resolution source under each IP in small text. Plumbed from `scanner.get_device_address()` (which now returns `(address, source)`) → `build_name_to_target_map` (4-tuple now includes `address_sources`) → `device_poller.update_compile_targets` → `Device.address_source` → `/ui/api/targets` → `Target.address_source` → `DevicesTab` IP cell. Sources: `mdns` (discovered), `wifi_use_address`, `wifi_static_ip`, `ethernet_use_address`, `ethernet_static_ip`, `openthread_use_address`, `mdns_default` (the `{name}.local` fallback). mDNS only "wins" over `mdns_default` — explicit user choices like `wifi.use_address` stay authoritative because that mismatch is itself useful information.

- [x] **#185** *(1.3.0-dev.28)* — CI was failing on the T.4 metadata tests. Root cause: the test fixtures used a minimal `esphome: + esp8266:` config that ESPHome's resolver in CI's newer version (2026.3.3) rejects as invalid; my local 2026.3.1 was more lenient. When `_resolve_esphome_config` returns None, metadata extraction silently no-ops. Fix: added a `_MIN_BOARD` template constant in `tests/test_scanner.py` (esp8266 board + minimal wifi block) shared by all metadata tests so they validate across versions.

- [x] **#186** *(1.3.0-dev.28)* — Added `tests/fixtures/esphome_configs/static_ip_device.yaml` and `thread_only_device.yaml` plus 3 fixture-based scanner tests. Validated as part of the #179 fix — exercises the real ESPHome resolution pipeline against `wifi.manual_ip.static_ip` and Thread-only configs.
- [x] **#187** *(1.3.0)* — Some devices on hass-4 had an IP shown but no "IP source" label after deploying #184. Investigating uncovered a deeper bug: `device_poller._save_cache` was persisting `ip_address`, which is wrong for DHCP devices — a renewed lease leaves a stale cached IP that points at the wrong device until mDNS reconciles. Fix: (a) `_save_cache`/`_load_cache` now persist ONLY the stable per-firmware bits (`running_version`, `compilation_time`, `mac_address`); `ip_address` and `address_source` are deliberately not cached. The IP is repopulated on startup from `update_compile_targets` (the YAML's `get_device_address` default) and then overridden by mDNS as devices come back online. (b) `update_compile_targets`'s `else` branch now ALWAYS backfills `address_source` when it's None — previously it skipped the source assignment whenever the IP was already set, so even after the first fix cached devices would have stayed sourceless until mDNS hit. 4 new regression tests in `test_device_poller.py` covering: `update_compile_targets` backfilling `address_source` on an existing device with an IP, NOT clobbering an existing source, `_save_cache` excluding `ip_address`/`address_source`, and `_load_cache` ignoring those fields if an old cache file still has them.