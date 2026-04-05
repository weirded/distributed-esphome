# Changelog

## 1.2.0

Design system overhaul, TanStack Table, SWR data fetching, and 60+ bug fixes.

**shadcn/ui Design System**
- Full adoption of shadcn/ui with Tailwind CSS v4 and Base UI primitives
- All modals migrated to shadcn Dialog (Editor, Log, Device Log, Rename, Delete, Connect Worker)
- All buttons migrated to shadcn Button with warn/success/destructive variants
- All dropdown menus use shadcn DropdownMenu (column picker, hamburger, upgrade, queue actions, ESPHome version selector)
- Toast notifications via Sonner
- Status indicators via shared StatusDot component
- Badges, tabs, panels, inputs all converted to Tailwind utility classes
- Consistent dark/light theme via CSS variable mapping

**TanStack Table**
- All three tables (Devices, Queue, Workers) use @tanstack/react-table
- Built-in column sorting, column visibility, and row selection
- Removed hand-rolled useSortable hook, SortableHeader component, DOM-query checkbox patterns

**SWR Data Fetching**
- Replaced 5 manual setInterval polling loops with useSWR hooks
- Automatic cache, deduplication, and stale-while-revalidate
- Immediate revalidation after actions (compile, retry, cancel)

**Worker Management**
- Built-in local worker runs inside the add-on container (0 slots by default, increase via UI)
- Worker slots adjustable 0-32 (0 = paused); removed separate Disable/Enable toggle
- Debounced +/- slot controls for rapid adjustment
- Disk space reporting with color warnings (orange >80%, red >90%)
- Auto-eviction of unused ESPHome versions when disk is low
- Local worker highlighted with "built-in" badge, pinned to top of list
- Docker Compose file for easy worker deployment

**UI Improvements**
- Configurable device table columns (Area, Comment, Project) with gear icon picker
- Consolidated device header: search + Upgrade dropdown + column picker in one row
- Queue buttons grouped into Retry and Clear dropdowns
- Search boxes on all three tabs (Devices, Queue, Workers)
- Streamer mode: toggle blurs IPs, tokens, and sensitive data
- Copy to Clipboard button on log modals with toast feedback
- Close button on all modals (shadcn Dialog native)
- "Running" column renamed to "Version"
- Validation jobs filtered from queue display
- Empty tabs show "0" badge instead of blank

**Backend**
- Archive management: list, restore, and permanently delete archived configs
- Terminal job auto-pruning (>1 hour old)
- Pinned worker preserved on retry (not just OTA failures)
- YAML metadata fallback: permissive loader for configs with git packages, simple substitution resolution
- Server Dockerfile installs git + build deps for local worker compilation

**Bug Fixes**
- 60+ fixes across bugs #90-#150 (see BUGS.md for details)

## 1.1.0
Major update: React UI rewrite, ESPHome dashboard-grade features, Home Assistant integration.

**New React UI**
- Complete rewrite from vanilla JS to React + Vite + TypeScript
- Monaco YAML editor with ESPHome schema-aware autocomplete (697 components from installed package)
- Per-component config var suggestions fetched from schema.esphome.io
- !secret autocomplete from secrets.yaml, inline YAML syntax validation
- Save & Upgrade button (save + compile + OTA in one click)
- Unsaved change highlighting with line-level diff indicators
- Dark/light theme toggle with localStorage persistence
- Device search/filter bar across all columns

**Device Lifecycle**
- Rename device: updates config file, esphome.name, triggers compile+OTA to flash new name
- Delete device: archive to .archive/ or permanent delete with confirmation dialog
- Restart device via native ESPHome API (aioesphomeapi button_command) with HA REST fallback

**Live Device Logs**
- WebSocket streaming via aioesphomeapi with full ANSI color support in xterm.js
- Boot log included (dump_config=True)
- Timestamps on each log line [HH:MM:SS]
- Works with encrypted API connections (noise_psk)

**Compile Improvements**
- Switched to `esphome run --no-logs` (single process compile+OTA, matches native ESPHome UI)
- Colorized compile logs: INFO=green, WARNING=yellow, ERROR=red
- OTA retry with 5s delay on failure (keeps job in WORKING state for proper re-queuing)
- Server timezone passed to workers (prevents config_hash mismatch and unnecessary clean rebuilds)
- OTA always uses explicit --device with known IP address
- ESPHome install errors now visible in streaming job log

**Home Assistant Integration**
- Background poller detects ESPHome devices registered in HA via template API + /api/states
- MAC-based device matching (queries HA device connections) — most reliable method
- Name-based fallback: friendly_name, esphome.name, filename stem, MAC fragment matching
- HA column in Devices tab shows configured status (Yes/—)
- HA connectivity (_status binary_sensor) feeds into online/offline column
- Device restart via HA REST API as fallback when native API unavailable

**Config Validation**
- Validate button saves editor content first, then runs esphome config
- Validation opens streaming log modal directly (no toast intermediary)
- Badge shows Validating/Valid/Failed status in queue

**Performance**
- Concurrent device polling via asyncio.gather (all devices checked in parallel)
- HA entity poller runs immediately on startup (no 30s delay)
- Config resolution caches git clones (skip_update=True after first resolution)
- PyPI version list increased from 10 to 50

**UI Polish**
- Per-row Clear button in queue tab
- Edit buttons in queue rows and log modal header
- Hamburger menu redesigned: vertical ellipsis icon, plain text styling
- Live Logs and Restart moved to hamburger menu (never grayed out)
- Light mode: dark header for ESPHome logo readability, themed form inputs
- "Checking..." state with pulsing dot on startup (instead of showing offline)
- Copy API Key, Rename, Delete in device hamburger menu

**Operations**
- Suppressed aioesphomeapi.connection warnings (expected when devices offline)
- ESPHome add-on version detection at DEBUG level (no log spam)
- Debug endpoint GET /ui/api/debug/ha-status for HA matching troubleshooting
- Queue remove-by-ID endpoint for per-job clearing

**Bug Fixes**
- 89 bugs tracked and fixed during development (see BUGS.md)
- Fixed polling interval explosion (React useEffect dependency bug)
- Fixed editor content wiped on parent re-render (useRef pattern)
- Fixed disabled button CSS specificity (!important on all disabled properties)
- Fixed duplicate devices after rename (old entry removed from poller)
- Fixed modal closing on drag-select (mousedown target tracking)
- Fixed DeprecationWarning on app state mutation (clear+update pattern)

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
