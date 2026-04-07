# Work Items — 1.0.0

First stable release. Distributed ESPHome compilation with a full web UI built on vanilla JS, xterm.js, and Monaco editor (basic keyword completion). Foundation for everything that follows.

## Distributed Compilation

- [x] Job queue with `PENDING → WORKING → SUCCESS/FAILED` state machine
- [x] Performance-based job scheduling (fastest idle worker first, spread evenly)
- [x] Workers report CPU benchmark, real-time utilization, system info
- [x] Effective score `= perf_score × (1 - cpu_usage/100)` for load-aware scheduling

## Web UI (vanilla JS — pre-React)

- [x] Three tabs: Devices, Queue, Workers
- [x] xterm.js live log viewer with WebSocket streaming and ANSI support
- [x] Monaco YAML editor with basic keyword completion
- [x] ESPHome version dropdown (detect from HA add-on, select from PyPI)
- [x] Connect Worker modal with configurable `docker run` command generator
- [x] Auto-reload UI on server version change (`X-Server-Version` header)

## Device Management

- [x] mDNS device discovery + ping fallback + `wifi.use_address` support
- [x] Device-to-config matching using ESPHome's full config resolution pipeline
- [x] Encrypted API connections (extracts `api.encryption.key` from configs)
- [x] Config change detection (file mtime vs device compilation time)
- [x] Proactive device entries for `use_address` configs (no mDNS required)
- [x] HA ESPHome add-on version detection via Supervisor API

## Build Workers

- [x] Docker-based remote workers with auto-update
- [x] System info reporting (CPU, memory, OS, architecture, uptime)
- [x] Persistent worker identity across restarts
- [x] Clean deregistration on shutdown (SIGTERM handler)
- [x] OTA firmware upload with retry and network diagnostics on failure
- [x] OTA retry jobs pinned to original worker (PlatformIO cache reuse)

## Operations

- [x] Resolved config caching (mtime-based, eliminates repeated git clones)
- [x] Suppressed noisy HTTP access logs
- [x] `hassio_api` integration for ESPHome version detection
- [x] `host_network` for mDNS device discovery
- [x] Multi-arch Docker images (amd64 + arm64) published to GHCR

---

*Pre-1.0 history exists in `ha-addon/CHANGELOG.md` under "Pre-1.0 Development History" — the v0.0.x iterations that led up to the first stable release.*
