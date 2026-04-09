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

## Scheduled Upgrades ([#30](https://github.com/weirded/distributed-esphome/issues/30))

Cron-style scheduler for automatic device upgrades — e.g. "every 8th of the month at 10am, upgrade all outdated devices".

- [ ] **SU.1 Schedule storage** — persist schedules to `/data/schedules.json`: `[{id, name, cron, target: "all" | "outdated" | [device names], enabled, last_run, next_run}]`
- [ ] **SU.2 Cron parser + scheduler loop** — stdlib-only (avoid new deps); background task wakes on next_run and enqueues the same compile jobs the "Upgrade Outdated" button uses today
- [ ] **SU.3 `GET/POST/DELETE /ui/api/schedules`** — list, create, update, delete
- [ ] **SU.4 Schedules tab (or section in Workers tab)** — list schedules, enable/disable toggle, "run now" button, show last/next run timestamps
- [ ] **SU.5 Schedule create modal** — friendly cron builder (daily/weekly/monthly presets + raw cron expression), target picker (all / outdated / specific devices)
- [ ] **SU.6 History** — last N runs per schedule with success/fail counts linking back to queue entries
