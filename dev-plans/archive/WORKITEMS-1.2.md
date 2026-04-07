# Work Items — 1.2.0

shadcn/ui design system, TanStack Table, SWR, local worker, 65+ bug fixes.

## Features

- [x] Configurable parallel job slots from UI (+/- controls, pushed via heartbeat)
- [x] Queue shows friendly device names with filename and timestamp
- [x] Upgrade All skips known-offline devices
- [x] Pin jobs to specific worker ("Upgrade on..." submenu)
- [x] Docker Compose worker file
- [x] Configurable device columns (area, project, comment) with column picker
- [x] Disk space management — workers report usage, version manager auto-evicts when low
- [x] **DS.0** Install Tailwind v4 + shadcn init, map CSS variables
- [x] **DS.1** New components use shadcn (DropdownMenu for column picker, hamburger, upgrade)
- [x] Toast migrated to Sonner
- [x] ESPHome version selector migrated to shadcn DropdownMenu
- [x] Search boxes added to Queue and Workers tabs
- [x] Queue buttons grouped into shadcn dropdowns (Retry, Clear)
- [x] Validation jobs filtered from queue display
- [x] shadcn/ui design system: Dialog, Button, DropdownMenu, Sonner toast, Tailwind preflight
- [x] TanStack Table for all three tabs (sorting, column visibility, row selection)
- [x] SWR data fetching (replaced manual setInterval polling)
- [x] Built-in local worker (python:3.11-slim base for PlatformIO compatibility)
- [x] Configurable device columns (Area, Comment, Project) with gear icon picker
- [x] Streamer mode (blur sensitive data)
- [x] Worker management: 0-slot pause, disk reporting, debounced controls
- [x] Archive management API (list, restore, permanent delete)
- [x] Copy to Clipboard on log modals
- [x] Unsaved changes warning in editor (shadcn Dialog)

---

## Bug Fixes (90–158)

<details>
<summary>Expand 69 bug fixes from 1.2.0</summary>

- [x] **#90** *(1.2.0-dev.3)* — Validate 502 "Cannot save". Made updateDirtyDecorations errors non-fatal (.catch(() => {})) so async diff failures don't bubble up as save errors.
- [x] **#91** *(1.2.0-dev.4)* — Validate log modal popped under editor. Added `stacked` CSS class (z-index 500) to LogModal when editor is open, so validation output appears over the editor.
- [x] **#92** *(1.2.0-dev.6)* — ESPHome logo huge and columns dropdown blanking screen. Root cause: Tailwind preflight reset was overriding img sizing and injecting base styles. Fixed by importing only tailwindcss/theme + tailwindcss/utilities (skipping preflight), since we have our own CSS reset.
- [x] **#93** *(1.2.0-dev.7)* — Columns button blanked screen. Root cause: DropdownMenuLabel requires being inside DropdownMenuGroup (Base UI error #31: "MenuGroupRootContext is missing"). Missing wrapper crashed React. Fixed by wrapping label + items in DropdownMenuGroup.
- [x] **#94** *(1.2.0-dev.8)* — shadcn/ui dropdown not honoring dark mode. Root cause: shadcn variables in :root were set to light zinc values. Fixed by mapping shadcn variables (--popover, --foreground, etc.) to app theme variables via var() references, so they automatically adapt to dark/light mode.
- [x] **#95** *(1.2.0-dev.8)* — Table limited to 1400px width. Removed max-width constraint on main element so table uses full browser width.
- [x] **#96** *(1.2.0-dev.8)* — Devices not refreshing after YAML edit. Editor onClose now triggers fetchDevicesAndTargets() so changes appear immediately.
- [x] **#97** *(1.2.0-dev.8)* — "Upgrade on" worker list now sorted alphabetically (case-insensitive), matching Workers tab sort.
- [x] **#98** *(1.2.0-dev.8)* — Hamburger menu restructured into sections: "Device" (Live Logs, Restart, Copy API Key), "Config" (Rename, Delete), and "Upgrade on..." as a submenu.
- [x] **#99** *(1.2.0-dev.8)* — Hamburger menu converted from custom CSS dropdown to shadcn DropdownMenu, consistent with columns picker. Both menus now use same Base UI primitives and theme.
- [x] **#100** *(1.2.0-dev.9)* VERIFIED — Copy API Key works correctly. Playwright confirmed: endpoint returns 200 with 44-char base64 key for devices with api.encryption.key configured. Button is disabled for devices without keys. Clipboard copy works.
- [x] **#101** *(1.2.0-dev.10)* — Slots +/- moved to dedicated "Slots" column in Workers tab. Minimum lowered from 1 to 0 (0 = paused, worker accepts no jobs). Server validation updated to accept 0-32. Client spawns no worker threads at 0.
- [x] **#102** *(1.2.0-dev.10)* — Local worker runs inside the add-on container. Server spawns client.py as subprocess on startup with 0 slots (paused by default). Users increase slots via Workers tab to activate. Uses /data/esphome-versions for builds. Terminated cleanly on shutdown.
- [x] **#103** *(1.2.0-dev.10)* — Disk space reporting added to worker system info. Workers report disk_total, disk_free, disk_used_pct for the /esphome-versions volume. Displayed in Workers tab Platform column as "Disk: X/Y free". Turns yellow >75% used, red >90%.
- [x] **#104** *(1.2.0-dev.11)* — Server crash on startup. Root cause: `cfg.server_token` should be `cfg.token` (AppConfig attribute name). Typo in local worker spawn code.
- [x] **#105** *(1.2.0-dev.11)* — Updated DOCS.md and README.md: removed obsolete package-client.sh/start.sh/stop.sh references, simplified worker setup (just Connect Worker button + docker-compose option), documented local worker, updated Web UI features (Monaco editor, live logs, configurable columns, HA integration, dark/light theme, etc.), updated repo layout (added ui/, removed dist-scripts/). Added docs update reminder to CLAUDE.md release checklist.
- [x] **#106** *(1.2.0-dev.12)* — Local worker code was correct (MAX_PARALLEL_JOBS=0), but `max_parallel_jobs || 1` in UI defaulted 0 to 1. Changed to `?? 0`. Also marked backlog #6 done.
- [x] **#107** *(1.2.0-dev.12)* — Local worker row highlighted with surface2 background, "built-in" badge, always sorted to top of workers list regardless of sort order. Remove button hidden for local worker.
- [x] **#108** *(1.2.0-dev.12)* — Slot +/- controls debounced with 600ms delay. Rapid clicks accumulate locally, single API call fires after user stops clicking.
- [x] **#109** *(1.2.0-dev.12)* — Disk space on separate line: "Disk: X / Y (Z% free)". Orange when >80% used, red when >90% used.
- [x] **#110** *(1.2.0-dev.12)* INVESTIGATED — Yes, worker restart is required to change slot count (heartbeat sends new value, client does os.execv restart). This is automatic and takes ~2-3 seconds.
- [x] **#111** *(1.2.0-dev.12)* — Toast now shows worker hostname (e.g. "lenovo-1 disabled"). Row height stabilized with consistent styling.
- [x] **#112** *(1.2.0-dev.12)* — Version manager evicts unused ESPHome versions when disk free drops below MIN_FREE_DISK_PCT (default 10%). Runs before each install. Keeps at least 1 version (the active one).
- [x] **#113** *(1.2.0-dev.13)* — Devices header consolidated into single row: DEVICES title, search box, Upgrade dropdown (All, All Online, Outdated, Selected), and gear icon for column picker. Removed second header row.
- [x] **#114** *(1.2.0-dev.13)* — DS.2 started: migrated toast system from custom ToastContainer to shadcn Sonner. Installed dialog and badge components.
- [x] **#115** *(1.2.0-dev.14)* — Gear icon enlarged from default to fontSize 16px.
- [x] **#116** *(1.2.0-dev.14)* — Area not read for configs with git package dependencies. Root cause: _resolve_esphome_config fails silently when git clone fails (e.g. race condition, network). Added fallback: simple yaml.safe_load reads area/comment/name directly from the YAML file when full resolution fails.
- [x] **#117** *(1.2.0-dev.14)* — Upgrade All Online not firing. Root cause: Base UI Menu.Item uses `onClick`, not `onSelect`. Changed all DropdownMenuItem handlers from onSelect to onClick.
- [x] **#118** *(1.2.0-dev.14)* — DS.2 toast migrated to Sonner, dropdowns done. Buttons/badges/dialog migration deferred.
- [x] **#119** *(1.2.0-dev.15)* — Area still missing for 11 devices. Two root causes: (1) yaml.safe_load fallback choked on !include/!secret tags — fixed with permissive YAML loader that passes through unknown tags. (2) Some configs define area in substitutions but not in esphome: block — added fallback to check substitutions.area.
- [x] **#120** *(1.2.0-dev.16)* — DS status notes consolidated.
- [x] **#121** *(1.2.0-dev.16)* — Device name resolution broken by raw YAML fallback returning unresolved ${name} literals. Restructured: full ESPHome resolution is always primary (handles names/substitutions/packages). Raw YAML fallback only fills MISSING fields (area, comment, project) with LITERAL values (skips anything containing ${...}). Never overwrites resolved values.
- [x] **#122** *(1.2.0-dev.17)* — "Upgrade on..." pinned jobs never started. Root cause: performance-based scheduling deferred ALL jobs when a faster worker existed, including pinned jobs. Fix: pinned jobs bypass the defer check in claim_next — they can only be claimed by the designated worker, so deferring made them stuck.
- [x] **#123** *(1.2.0-dev.17)* — Kauf-plug devices missing name/comment. Root cause: full ESPHome config resolution fails for these (git package clone issue), and the raw YAML fallback didn't resolve ${substitutions}. Fix: fallback now resolves simple ${key} substitutions from the substitutions block before extracting metadata.
- [x] **#124** *(1.2.0-dev.18)* — Validation jobs filtered from queue display and tab counts. displayQueue excludes validate_only jobs. LogModal still sees full queue for streaming. Auto-pruning handles cleanup.
- [x] **#125** *(1.2.0-dev.18)* — Workers with 0 slots excluded from "Upgrade on..." submenu (filtered by max_parallel_jobs > 0).
- [x] **#126** *(1.2.0-dev.18)* — Queue buttons grouped into two shadcn dropdowns: "Retry" (Retry All Failed, Retry Selected, Cancel Selected) and "Clear" (Clear Succeeded, Clear All Finished).
- [x] **#127** *(1.2.0-dev.18)* — Search boxes added to Queue and Workers tabs, matching Devices layout. Queue filters by device name, target, state, worker. Workers filters by hostname, OS, CPU, version.
- [x] **#128** *(1.2.0-dev.18)* — Pinned worker preserved on retry. Previously only OTA failures preserved the pin. Now all retried jobs keep their original pinned_client_id.
- [x] **#129** *(1.2.0-dev.18)* — Queue rows now use same device-name/device-filename CSS classes as Devices tab for consistent rendering.
- [x] **#130** *(1.2.0-dev.18)* — Empty queue shows "0" in tab badge instead of empty/dash.
- [x] **#131** *(1.2.0-dev.18)* — ESPHome version selector converted from custom dropdown to shadcn DropdownMenu. Removed versionDropdownOpen state and manual click-outside handler.
- [x] **#132** *(1.2.0-dev.19)* — Archive management: added GET /ui/api/archive (list), POST /ui/api/archive/{f}/restore, DELETE /ui/api/archive/{f} (permanent delete) endpoints. Delete modal now has double confirmation for permanent delete (first click shows "Delete Permanently", second screen confirms "Yes, Delete Forever"). API client functions added for archive operations. UI archive viewer deferred to future iteration.
- [x] **#133** *(1.2.0-dev.19)* — Removed Disable/Enable button entirely. Workers are now paused by setting slots to 0 (single concept). Status shows "Paused" instead of "Disabled". Row dims at 0 slots. Remove button only shows for offline non-local workers.
- [x] **#134** *(1.2.0-dev.27)* — Upgrade dropdown too narrow. Added min-w-[180px] to ensure options don't wrap.
- [x] ~~**#135**~~ NOT A BUG — Hamburger menu already uses shadcn DropdownMenu (migrated in 1.2.0-dev.8).
- [x] **#136** *(1.2.0-dev.27)* — Live logs and compile logs showing empty terminal. Root cause: Dialog portal mounts DOM asynchronously, but xterm useEffect ran before containerRef was populated. Fix: callback ref pattern — containerCallbackRef triggers state change when DOM node mounts, which re-fires the xterm initialization effect.
- [x] **#137** *(1.2.0-dev.27)* — Editor/log modals too tall (buttons off-screen). Changed dialog-lg height to min(80vh, calc(100vh - 4rem)) and dialog-xl to min(90vh, calc(100vh - 2rem)).
- [x] **#138** *(1.2.0-dev.27)* — Renamed "Running" column to "Version" in both table header and column picker.
- [x] **#139** *(1.2.0-dev.31)* — Docker command light mode contrast. Changed hardcoded `color: #e2e8f0` to `color: var(--text)` so it adapts to theme.
- [x] **#140** *(1.2.0-dev.32)* — Validate log modal: Edit and Retry buttons hidden when job.validate_only is true.
- [x] **#141** *(1.2.0-dev.33)* — Copy to Clipboard button added to LogModal and DeviceLogModal headers (next to Download). Extracts terminal text and copies via navigator.clipboard.
- [x] **#142** *(1.2.0-dev.33)* — Removed Rename button from editor header. Rename is still available via the hamburger menu.
- [x] **#143** *(1.2.0-dev.33)* — Close (✕) button added to all modals. Removed showCloseButton={false} from all 6 Dialog usages — shadcn Dialog's default close button (absolute top-right) now renders on every modal.
- [x] **#144** *(1.2.0-dev.34)* — Copy buttons not working. Root cause: navigator.clipboard requires secure context (HTTPS). Added textarea fallback for HTTP/Ingress contexts.
- [x] **#145** *(1.2.0-dev.34)* — X and Download buttons overlapping. Fix: added pr-12 right padding to DialogHeader so content doesn't extend under the library's absolute-positioned close button. All modals use the default close button — no custom overrides.
- [x] **#146** *(1.2.0-dev.35)* — Editor X button overlapping header buttons. Added right padding (3rem) to .editor-header CSS so buttons don't extend under the close button.
- [x] **#147** *(1.2.0-dev.35)* — Toast feedback on copy. Both LogModal and DeviceLogModal now show "Copied to clipboard" toast via Sonner after successful copy.
- [x] **#148** *(1.2.0-dev.35)* — Connect Worker modal scrollbar. Removed maxHeight constraint on content div — Dialog handles height naturally.
- [x] **#149** *(1.2.0-dev.38)* — Local worker missing git and build dependencies. Added `apk add git gcc musl-dev libffi-dev openssl-dev` to server Dockerfile. Also installed client requirements.txt in server image so local worker has all Python deps.
- [x] **#150** *(1.2.0-dev.40)* — Header icon buttons inconsistent size. Theme and streamer toggles now use fixed 28x28 rounded circles. Streamer toggle shows only icon (👁/🔒) instead of changing text length. Active state highlights with accent color.
- [x] **#151** *(1.2.0-dev.41)* — Polling refresh closes open hamburger menu. Wrapped DeviceMenu in React.memo so it doesn't re-render on every poll cycle. Base UI portal keeps dropdown open across parent re-renders.
- [x] **#152** *(1.2.0-dev.41)* — Editor closes without warning when there are unsaved changes. Added confirm dialog: "You have unsaved changes. Close anyway?" when dirtyLineCount > 0.
- [x] **#153** *(1.2.0-dev.41)* — Local worker: xtensa-lx106-elf-g++ not found (ESP8266 cross-compiler). Root cause: PlatformIO downloads glibc-compiled toolchains but Alpine uses musl. Added `gcompat` (glibc compatibility layer) to Dockerfile.
- [x] **#154** *(1.2.0-dev.50)* — Hamburger menu closing on refresh. Root cause: TanStack Table recreates row DOM on SWR data change, unmounting DropdownMenu. Fix: menu rendered as fixed-positioned overlay outside the table with left-opening hover submenu for worker list. Playwright verified: opens instantly, positioned correctly, submenu within viewport, stays open 20+ seconds across polls.
- [x] **#155** *(1.2.0-dev.42)* — Editor unsaved warning uses native window.confirm. Replaced with shadcn Dialog showing "Unsaved Changes" with Cancel/Discard Changes buttons, rendered at z-index 600 above the editor.
- [x] **#156** *(1.2.0-dev.42)* — Local worker slot count lost on restart. Persisted to /data/local_worker_slots. Server reads on startup, UI writes on change.
- [x] **#157-158** *(1.2.0-dev.60)* — Local worker compilation failures. Root cause: Alpine base image's musl libc can't run PlatformIO's glibc cross-compiler toolchains (segfault with gcompat). Fix: hardcoded `FROM python:3.11-slim` (Debian) in Dockerfile — same proven base as the client image. HA Supervisor overrides BUILD_FROM arg, so hardcoding was necessary. Includes gcc, libffi-dev, libssl-dev, git.

</details>
