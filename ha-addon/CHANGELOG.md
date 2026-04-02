# Changelog

## 1.0.0
First stable release. Distributed ESPHome compilation with a full web UI.

**Distributed Compilation**
- Job queue with PENDING → WORKING → SUCCESS/FAILED state machine
- Performance-based job scheduling (fastest idle worker first, spread evenly)
- Workers report CPU benchmark, real-time utilization, system info
- Effective score = perf_score × (1 - cpu_usage/100) for load-aware scheduling

**Web UI**
- Three tabs: Devices, Queue, Workers
- xterm.js live log viewer with WebSocket streaming and ANSI support
- Monaco YAML editor with basic keyword completion
- ESPHome version dropdown (detect from HA add-on, select from PyPI)
- Connect Worker modal with configurable docker run command generator
- Auto-reload UI on server version change (X-Server-Version header)

**Device Management**
- mDNS device discovery + ping fallback + wifi.use_address support
- Device-to-config matching using ESPHome's full config resolution pipeline
- Encrypted API connections (extracts api.encryption.key from configs)
- Config change detection (file mtime vs device compilation time)
- Proactive device entries for use_address configs (no mDNS required)
- HA ESPHome add-on version detection via Supervisor API

**Build Workers**
- Docker-based remote workers with auto-update
- System info reporting (CPU, memory, OS, architecture, uptime)
- Persistent worker identity across restarts
- Clean deregistration on shutdown (SIGTERM handler)
- OTA firmware upload with retry and network diagnostics on failure
- OTA retry jobs pinned to original worker (PlatformIO cache reuse)

**Operations**
- Resolved config caching (mtime-based, eliminates repeated git clones)
- Suppressed noisy HTTP access logs
- hassio_api integration for ESPHome version detection
- host_network for mDNS device discovery
- Multi-arch Docker images (amd64 + arm64) published to GHCR

## Pre-1.0 Development History

See git history for detailed changes during the 0.0.1–0.0.73 development period.
