# Work Items — 1.5.0

Theme: **Power-user features that go beyond stock ESPHome.** Better ways to manage large device fleets, track config changes, and get AI assistance.

## File Tree Editor

Browse and edit any file in the ESPHome config directory, including subdirectories. VS Code-style file tree sidebar in the editor modal.

- [ ] **FT.1 `GET /ui/api/files`** — recursive directory listing, returns flat `[{path, size, binary}]`
- [ ] **FT.2 `GET /ui/api/files/{path:.+}`** — read file by relative path (path traversal prevention)
- [ ] **FT.3 `POST /ui/api/files/{path:.+}`** — write file (invalidates config cache for .yaml)
- [ ] **FT.4 Install `@headless-tree/core` + `@headless-tree/react`** — headless tree library
- [ ] **FT.5 `FileTree.tsx` component** — flat list → tree, expand/collapse, active highlight, binary grayed out
- [ ] **FT.6 Sidebar layout** — editor body flex row: `[file tree 240px] | [monaco flex-1]`, sidebar toggle
- [ ] **FT.7 File switching** — dirty check → load/save, language detection by extension
- [ ] **FT.8 Conditional buttons** — Save & Upgrade/Validate/Rename only for entry-point YAML; includes get Save only
- [ ] **FT.9 API functions** — `listFiles()`, `readFile()`, `writeFile()` in client.ts

## Device Organization

- [ ] **6.3 Device groups/tags** — JSON sidecar metadata, filter/group UI in Devices tab
- [ ] **6.6 Bulk operations** — extend multi-select: bulk delete, bulk validate, bulk tag

## Config Diff

- [ ] **1.5a Store config snapshot** — save YAML at compile time to `/data/config_snapshots/`
- [ ] **1.5b Diff endpoint** — return unified diff between current and last-compiled
- [ ] **1.5c Diff viewer in editor** — Monaco diff editor or inline diff display

## Import

- [ ] **2.1c Create device: import from URL** — fetch config from GitHub/project URL

## Version Pinning

Pin individual devices to a specific ESPHome version. Pinned devices compile with their pinned version even during bulk upgrades. The pin is stored as a structured YAML comment (`# distributed-esphome: pin_version=2024.11.1`) at the top of the device YAML — invisible to ESPHome's parser, no sidecar files, travels with the config through git/backups.

- [ ] **VP.1 Scanner: read pin** — extract `# distributed-esphome: pin_version=X.Y.Z` from raw YAML text before parsing; include `pinned_version` in device metadata returned by `get_device_metadata()`
- [ ] **VP.2 Scanner: write/clear pin** — `write_pin(target, version)` / `clear_pin(target)` helpers to add/remove the comment line in a YAML file without disturbing the rest of the content
- [ ] **VP.3 API endpoints** — `POST /ui/api/targets/{target}/pin` (set pin, body `{version}`) and `DELETE /ui/api/targets/{target}/pin` (clear pin)
- [ ] **VP.4 Hamburger menu** — "Pin to current version" (when unpinned) / "Unpin version" (when pinned), with the pinned version shown inline
- [ ] **VP.5 UpgradeModal** — "Keep device pinned" checkbox when upgrading a pinned device (compiles with the pinned version instead of the selected one)
- [ ] **VP.6 Visual indicator** — pin icon + version badge on pinned devices in the device list
- [ ] **VP.7 Compile guard** — when a pinned device is included in bulk "Upgrade All/Outdated", use the pinned version (not the global version) for that device's job
- [ ] **VP.8 Scheduled Upgrades integration** — pinned devices respect their pin during scheduled runs (uses pinned version, or optionally skip pinned devices)

## Git Integration

Version history, commit, and push/pull for ESPHome configs — pairs with the File Tree Editor and Config Diff features to give power users full source-control visibility without leaving the UI.

- [ ] **GI.1 Git detection** — on startup, detect whether the config directory is a git repo; expose `git_enabled` flag in `/ui/api/info`
- [ ] **GI.2 Git status endpoint** — `GET /ui/api/git/status` — returns per-file status (modified, untracked, staged) for the config directory
- [ ] **GI.3 Git log endpoint** — `GET /ui/api/git/log` — recent commits (hash, message, author, date) for the config directory
- [ ] **GI.4 Git commit endpoint** — `POST /ui/api/git/commit` — stage changed files + commit with user-provided message
- [ ] **GI.5 Git pull/push endpoints** — `POST /ui/api/git/pull`, `POST /ui/api/git/push` — sync with remote (if configured)
- [ ] **GI.6 Git status indicators in File Tree** — modified/untracked badges on files in the FT sidebar
- [ ] **GI.7 Git history panel** — commit log viewer, per-file history, diff between commits

## Build Operations

- [ ] **5.2 Build cache status** — workers report cache stats, display in UI
- [ ] **5.4 Notification hooks** — webhook URL for job success/failure (Slack/Discord)

## Remote Compilation

Allow compiling on VPS servers not on the local network — firmware download + separate OTA step.

- [ ] **RC.1 Firmware download mode** — worker stores compiled binary instead of OTA-flashing; server endpoint to download firmware
- [ ] **RC.2 Separate OTA step** — UI-triggered OTA from stored firmware to local device
- [ ] **RC.3 GitHub Actions integration** — optional: trigger builds via GitHub Actions workflow

## Scheduled Upgrades ([#30](https://github.com/weirded/distributed-esphome/issues/30))

Cron-style scheduler for automatic device upgrades — e.g. "every 8th of the month at 10am, upgrade all outdated devices".

- [ ] **SU.1 Schedule storage** — persist schedules to `/data/schedules.json`: `[{id, name, cron, target: "all" | "outdated" | [device names], enabled, last_run, next_run}]`
- [ ] **SU.2 Cron parser + scheduler loop** — stdlib-only (avoid new deps); background task wakes on next_run and enqueues the same compile jobs the "Upgrade Outdated" button uses today
- [ ] **SU.3 `GET/POST/DELETE /ui/api/schedules`** — list, create, update, delete
- [ ] **SU.4 Schedules tab (or section in Workers tab)** — list schedules, enable/disable toggle, "run now" button, show last/next run timestamps
- [ ] **SU.5 Schedule create modal** — friendly cron builder (daily/weekly/monthly presets + raw cron expression), target picker (all / outdated / specific devices)
- [ ] **SU.6 History** — last N runs per schedule with success/fail counts linking back to queue entries
