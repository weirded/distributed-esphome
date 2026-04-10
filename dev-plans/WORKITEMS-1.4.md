# Work Items — 1.4.0

Theme: **Fleet management and automation.** Novel features you can't get from the stock ESPHome dashboard — controlling many devices at scale, pinning versions, scheduling upgrades, and downloading compiled firmware.

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

## Device Organization

- [ ] **6.3 Device groups/tags** — JSON sidecar metadata, filter/group UI in Devices tab
- [ ] **6.6 Bulk operations** — extend multi-select: bulk delete, bulk validate, bulk tag

## Scheduled Upgrades ([#30](https://github.com/weirded/distributed-esphome/issues/30))

Cron-style scheduler for automatic device upgrades — e.g. "every 8th of the month at 10am, upgrade all outdated devices".

- [ ] **SU.1 Schedule storage** — persist schedules to `/data/schedules.json`: `[{id, name, cron, target: "all" | "outdated" | [device names], enabled, last_run, next_run}]`
- [ ] **SU.2 Cron parser + scheduler loop** — stdlib-only (avoid new deps); background task wakes on next_run and enqueues the same compile jobs the "Upgrade Outdated" button uses today
- [ ] **SU.3 `GET/POST/DELETE /ui/api/schedules`** — list, create, update, delete
- [ ] **SU.4 Schedules tab (or section in Workers tab)** — list schedules, enable/disable toggle, "run now" button, show last/next run timestamps
- [ ] **SU.5 Schedule create modal** — friendly cron builder (daily/weekly/monthly presets + raw cron expression), target picker (all / outdated / specific devices)
- [ ] **SU.6 History** — last N runs per schedule with success/fail counts linking back to queue entries

## Build Operations

- [ ] **5.2 Build cache status** — workers report cache stats, display in UI
- [ ] **5.4 Notification hooks** — webhook URL for job success/failure (Slack/Discord)

## Firmware Download

After a successful compile, extract the firmware binary and make it downloadable from the UI. Foundation for remote compilation in a later release.

- [ ] **3.1a Worker extracts firmware binary** — read .bin after compile, POST to server
- [ ] **3.1b Server stores firmware** — `/data/firmware/<target>/`, metadata endpoint
- [ ] **3.1c Download button on device row** — `GET /ui/api/targets/{f}/firmware`

## Open Bugs & Tweaks

