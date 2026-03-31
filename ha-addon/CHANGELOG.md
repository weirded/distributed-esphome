# Changelog

## 0.0.40
- Standalone Docker distribution for the server (no Home Assistant required)
- GitHub Actions workflow to publish server image to GHCR on push
- Pre-push hook validates changelog entry exists for current version

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
