# Changelog

## 0.0.61
- Workers report CPU utilization on every heartbeat (sampled from /proc/stat)
- Scheduling uses effective score = perf_score × (1 - cpu_usage/100)
  so a busy fast machine defers to an idle slower one
- Workers tab shows CPU usage alongside perf score

## 0.0.60
- Fix job distribution: spread evenly across workers before filling slots
  - Rule 1: defer if ANY worker has fewer active jobs (spread first)
  - Rule 2: among equal job counts, defer if a faster worker has free slots
  - 4 jobs across 4 workers → 1 each, not 2+2 on fastest two

## 0.0.59
- Fix job scheduling: remove broken grace period approach, replace with
  simple rule: defer if a faster worker has equal-or-fewer jobs AND free slots
  - Single job → fastest worker
  - Two jobs → one per worker (fastest first)
  - Batch → spread across all, then fastest gets more

## 0.0.58
- Fix multi-slot scheduling: count actual WORKING jobs per worker (not just
  current_job_id) so 2 jobs go to 2 different workers instead of both slots
  on the fastest worker
- Devices tab: show "last seen" time (e.g. "3m ago") below online/offline status

## 0.0.57
- Auto-reload UI when server version changes (polls every 30s, shows toast, reloads after 1.5s)

## 0.0.56
- Performance-based job scheduling: faster workers claim jobs first
  - If a faster idle worker exists, slower workers defer for 2 seconds
  - After grace period, any idle worker can claim
  - Single-job scenario: always runs on the fastest available worker

## 0.0.55
- Succeeded jobs can now be retried (individual Retry button + Retry Selected)
- Connect Worker: server URL is now a dropdown with hostname + all known IPs
- Checkboxes in Queue and Devices tabs retained across auto-refresh
- Worker performance score: 1-second CPU benchmark (SHA256), shown in Workers tab
- Workers tab: CPU arch, cores, memory moved from hostname to platform column

## 0.0.54
- Log modal: Retry button in header for failed/OTA-failed jobs
- Queue tab: Clear Succeeded button now green (btn-success)
- Connect Worker dialog: uses server IP address instead of hostname/mDNS name
- HOST_PLATFORM correctly omitted from docker command when empty (auto-detected by client)

## 0.0.53
- Fix CI: exclude e2e tests (need ESPHome installed, take 3+ minutes)
- Add 10-minute timeout and concurrency cancellation to CI workflow

## 0.0.52
- Redesigned Connect Worker modal with configurable form fields
  (container name, hostname, parallel jobs, seed version, host platform, restart policy)
- Docker command generates dynamically as options change, with Copy button
- Removed package-client.sh, push-to-clients.sh, and all dist-scripts
  (start.sh, stop.sh, uninstall.sh, PowerShell variants, Proxmox builder)
  — GHCR image + docker run command is now the only distribution method

## 0.0.51
- Rename "Client" to "Worker" throughout: UI labels, API routes, config keys, docs
  - New API routes `/api/v1/workers/*` and `/ui/api/workers/*` (old `/clients/*` routes kept for backward compatibility)
  - Config option `client_offline_threshold` → `worker_offline_threshold` (old key still accepted)
  - Workers tab, "+ Connect Worker" button, "Build Workers" heading in the web UI
  - `ClientRegistry` → `WorkerRegistry` in server code (alias retained for compat)
- Remove "Linux" from platform column (always said Linux in Docker; now shows OS + CPU only)
- Exclude macOS resource fork files (`._*`, `.DS_Store`) from all tarballs

## 0.0.50
- Fix e2e tests: FakeServer __init__ was broken by misplaced property
- All 111 tests passing (95 unit + 16 e2e)

## 0.0.49
- Version bump to trigger CI e2e test re-run

## 0.0.48
- Simplify job state machine: replace ASSIGNED + RUNNING with a single WORKING state
  - PENDING → WORKING → SUCCESS/FAILED (RUNNING was unused in production)
  - Backwards compatible: old queue.json with "assigned"/"running" values load as WORKING
  - Log modal header badge now matches queue table badge exactly (shows status_text or "Working")

## 0.0.47
- Unify log storage: streaming log IS the authoritative log
  - Client no longer sends full log on completion (server uses streamed buffer)
  - Server persists streamed log on job completion
  - Both live and finished logs render through xterm.js

## 0.0.46
- Fix log streaming latency: use read1() for non-blocking pipe reads
  (returns available bytes immediately instead of waiting to fill 4KB buffer)

## 0.0.45
- Replace custom log renderer with xterm.js terminal emulator
  - Full ANSI escape code support (colors, cursor movement, \r progress bars)
  - Progress bars update in place as intended
  - Auto-scroll follows output
- Log modal header updates live (state badge, duration) while open
- Polling fallback interval reduced to 500ms

## 0.0.44
- Fix progress bars: read raw bytes from subprocess (preserves \r carriage returns)
- Always scroll to bottom on log updates (simple auto-tail)
- Reduce flush interval from 2s to 500ms for more responsive live logs

## 0.0.43
- Fix ANSI stripping: handle `[?25l` cursor-hide and other `?`-prefixed escapes
- Fix \r handling: split on \r correctly for progress bar overwrites
- Fix auto-scroll: programmatic scrolls no longer reset the auto-tail flag

## 0.0.42
- Log modal: fixed 80vh height, auto-tail follows output unless user scrolls up
- Progress bars render correctly (handle \r carriage returns)
- Strip ANSI escape codes from log output

## 0.0.41
- Fix live log streaming: replace websocket-client with HTTP POST batching
  (client auto-update can't install new pip dependencies, so websocket-client
  was never available on deployed clients)
- Remove websocket-client dependency from client requirements
- Add POST /api/v1/jobs/{id}/log endpoint for batched log streaming
- Client streams lines every 2 seconds via HTTP POST using existing requests lib

## 0.0.39
- HTTP polling fallback for live logs when WebSocket through HA Ingress fails
- Console debug logging for WebSocket connection troubleshooting
- GET /ui/api/jobs/{id}/log?offset=N endpoint for offset-based log tailing

## 0.0.38
- WebSocket-based live log streaming: build client streams subprocess output line-by-line to the server; browser tails job logs in real-time via a WebSocket in the log modal

## 0.0.37
- Backfill missing changelog entries
- Strengthen CLAUDE.md release process instructions

## 0.0.36
- Added "always bump version on push" rule to CLAUDE.md

## 0.0.35
- Docker run command in UI uses server version tag instead of :latest
- Container named `distributed-esphome-worker`

## 0.0.34
- GHCR publish workflow for client Docker image (multi-arch: amd64 + arm64)
- Skip e2e tests in pre-push hook (1.4s instead of 2.5 minutes)

## 0.0.33
- Single client codebase: removed duplicate top-level `client/` directory
- `ha-addon/client/` is now the single source of truth
- Committed client code to git for GitHub-based installs
- Removed `scripts/sync-client.sh`

## 0.0.32
- Fix add-on startup: bypass s6-overlay, use Docker tini + direct CMD
- Root cause: s6-overlay-suexec setuid blocked by container security context
- Proper architecture: `init: true`, `ENTRYPOINT []`, `CMD ["python3", ...]`
- Deploy script now flushes stale AppArmor kernel profiles

## 0.0.31
- Remove custom AppArmor profile — use HA default instead

## 0.0.30
- Fix AppArmor — add execute permission for binaries

## 0.0.29
- Use s6-overlay properly with `init: true`

## 0.0.28
- Use plain bash in run.sh — drop bashio/s6 dependencies

## 0.0.27
- Fix /init permission denied — override base image ENTRYPOINT

## 0.0.26
- Revert to CMD+run.sh — s6-overlay /init permission denied

## 0.0.25
- Version bump for client auto-update

## 0.0.24
- Network diagnostics on OTA failure
- Use `wifi.use_address` for OTA diagnostics target
- Proxmox LXC template builder for client package

## 0.0.23
- HA add-on compliance: s6-overlay service runner, DOCS.md, translations, AppArmor profile
- Added changelog

## 0.0.22
- Removed dead local client code
- Security audit and documentation

## 0.0.21
- Persist client hostname on job so queue UI survives client deregister

## 0.0.20
- Version bump
- Restore hostname in queue client column, add pinned hint below

## 0.0.19
- Pin OTA retry jobs to the original client

## 0.0.18
- Persistent client identity across restarts
- Deregister client on clean shutdown
- Log system info on client startup
- Auto-detect HOST_PLATFORM in start.sh from host OS

## 0.0.17
- HOST_PLATFORM env var to override detected OS in Docker client

## 0.0.16
- Client system info reporting (CPU, memory, OS, uptime)

## 0.0.15
- Use ESPHome's full config resolution for device name matching

## 0.0.14
- Centralised AppConfig for server configuration
- OTA-only retry for failed uploads (skip recompile)

## 0.0.13
- OTA Pending badge in UI
- Windows PowerShell scripts for client distribution

## 0.0.12
- Remove offline clients from UI automatically

## 0.0.11
- Retry OTA failures automatically
- Device name matching improvements
- Config change detection to trigger recompile

## 0.0.10
- Increase default job timeout to 600s to accommodate parallel builds

## 0.0.9
- Tab-based UI (Queue, Devices, Clients)
- Queue cleanup controls
- Multi-architecture Docker images
- DRY client code refactor
- Distribution scripts for client package

## 0.0.8
- GitHub Actions CI for multi-arch builds
- Per-worker log preamble for easier debugging
- Pre-push hook

## 0.0.7
- Per-slot PlatformIO core directories to fix parallel build conflicts

## 0.0.6
- ESPHome version displayed in client header
- Per-slot client rows in UI
- Worker slot shown in queue view

## 0.0.5
- Parallel build workers on each client
- Thread-safe VersionManager

## 0.0.4
- Server version display in UI
- Early ESPHome update check on client startup
- Unified job states

## 0.0.3
- In-place client re-registration
- Device action buttons in UI

## 0.0.2
- OTA log streaming
- Retry selected jobs
- Persistent queue clear setting
- Faster queue polling

## 0.0.1
- Initial release: distributed ESPHome build system
- Job queue with state machine (PENDING → ASSIGNED → RUNNING → SUCCESS/FAILED)
- Build client with ESPHome version manager and LRU cache
- HA Ingress web UI
- mDNS device discovery and firmware version polling
