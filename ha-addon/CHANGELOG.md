# Changelog

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
