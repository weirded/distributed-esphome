# Work Items — 1.4.0

Theme: **Fleet management and automation.** Novel features you can't get from the stock ESPHome dashboard — controlling many devices at scale, pinning versions, scheduling upgrades, and downloading compiled firmware.

## Version Pinning

Pin individual devices to a specific ESPHome version. Pinned devices compile with their pinned version even during bulk upgrades. The pin is stored in the per-device `# distributed-esphome:` comment block (`pin_version: 2024.11.1`) — invisible to ESPHome's parser, travels with the config through git/backups.

**Foundation landed in 1.4.0-dev.2:** The generic metadata comment system (`read_device_meta()` / `write_device_meta()`) and the `POST /ui/api/targets/{f}/meta` endpoint already support reading/writing `pin_version`. The `/ui/api/targets` response includes `pinned_version`, and `needs_update` respects it. What remains is the UI + compile guards.

- [x] **VP.1 Scanner: read pin** *(1.4.0-dev.2)* — `read_device_meta()` extracts `pin_version` from the comment block; `get_device_metadata()` merges it as `pinned_version` into the metadata dict returned to callers.
- [x] **VP.2 Scanner: write/clear pin** *(1.4.0-dev.2)* — `write_device_meta()` handles arbitrary key-value writes including `pin_version`. The `POST /ui/api/targets/{f}/meta` endpoint wraps it for the UI (set `pin_version` to a value, or `null` to clear).
- [x] **VP.3 API endpoints** *(1.4.0-dev.3)* — `POST /ui/api/targets/{target}/pin` (set pin, body `{version}`) and `DELETE /ui/api/targets/{target}/pin` (clear pin). Dedicated convenience endpoints on top of the generic `/meta`.
- [x] **VP.4 Hamburger menu** *(1.4.0-dev.3)* — "Pin to current version" (pins to the device's running_version) / "Unpin version (X.Y.Z)" (when pinned). Uses `pinTargetVersion` / `unpinTargetVersion` API client functions.
- [ ] **VP.5 UpgradeModal** — "Keep device pinned" checkbox when upgrading a pinned device (compiles with the pinned version instead of the selected one).
- [x] **VP.6 Visual indicator** *(1.4.0-dev.2)* — 📌 pin icon next to device name when `pinned_version` is set (with tooltip showing the version).
- [x] **VP.7 Compile guard** *(1.4.0-dev.3)* — when a pinned device is included in bulk "Upgrade All/Outdated", the compile endpoint reads `pin_version` from the device's metadata comment and uses it instead of the global version. An explicit `version_override` from the UpgradeModal still takes precedence.
- [x] **VP.8 Scheduled Upgrades integration** *(1.4.0-dev.2)* — the `schedule_checker()` background task uses `meta.get("pin_version") or get_esphome_version()` as the compile version, so pinned devices respect their pin during scheduled runs.

## Device Organization

Note: the `tags` field is already supported by the metadata comment system (1.4.0-dev.2) — `read_device_meta()` / `write_device_meta()` handle it, and `/ui/api/targets` returns it. What remains is the UI for filtering/grouping by tags.

- [ ] **6.3 Device groups/tags** — filter/group UI in Devices tab using the `tags` field from the YAML comment block
- [ ] **6.6 Bulk operations** — extend multi-select: bulk delete, bulk validate, bulk tag

## Scheduled Upgrades ([#30](https://github.com/weirded/distributed-esphome/issues/30))

Per-device cron scheduler for automatic compile+OTA. Schedule is stored in the device's `# distributed-esphome:` comment block (`schedule: 0 2 * * 0`, `schedule_enabled: true`), not a separate file. The server's `schedule_checker()` background task fires every 60s, computes next run via `croniter`, and enqueues jobs when due. Respects version pinning.

**Core landed in 1.4.0-dev.2.** What shipped:
- Storage is per-device in the YAML comment (not `/data/schedules.json` as originally planned — simpler, no orphan entries, travels with the file).
- `croniter>=1.3` (pure Python) for cron parsing — changed from "stdlib-only" because writing a correct cron parser is more code and more bugs than the 50KB library.
- 7 scheduler unit tests + 11 metadata read/write tests.

- [x] **SU.1 Schedule storage** *(1.4.0-dev.2)* — stored in the per-device `# distributed-esphome:` comment block: `schedule` (5-field cron), `schedule_enabled` (bool), `schedule_last_run` (ISO datetime). Read via `read_device_meta()`, written via `write_device_meta()`. Surfaced in `/ui/api/targets` response.
- [x] **SU.2 Cron parser + scheduler loop** *(1.4.0-dev.2)* — `schedule_checker()` background task in `main.py`, runs every 60s. Uses `croniter` to compute next fire time from last_run. Enqueues compile+OTA via `queue.enqueue()`. Marks jobs with `Job.scheduled = True`. Persists `schedule_last_run` back to the YAML comment after each fire. Lazy-imports croniter so a missing install doesn't crash the server.
- [x] **SU.3 API endpoints** *(1.4.0-dev.2)* — `POST /ui/api/targets/{f}/schedule` (set cron + enable), `DELETE .../schedule` (clear), `POST .../schedule/toggle` (flip enabled). Plus the generic `POST /ui/api/targets/{f}/meta` for arbitrary metadata writes.
- [x] **SU.5 Schedule create modal** *(1.4.0-dev.2)* — `ScheduleModal.tsx`: preset dropdown (Daily 2am, Weekly Sunday 2am, Monthly 1st 2am, Every 6h, Every 12h) + "Custom" raw cron input + enabled toggle + Save/Remove/Cancel. Opened from the device hamburger menu ("Schedule Upgrade...").
- [ ] **SU.4 Schedules overview** — optional: a section somewhere that lists ALL scheduled devices at a glance (currently visible per-device via the 🕐 icon, but no single-page "all schedules" view).
- [ ] **SU.6 History** — last N runs per schedule with success/fail counts linking back to queue entries. (Currently the job's `scheduled: true` flag identifies scheduler runs in the queue, but there's no aggregated history view.)

## Build Operations

- [ ] **5.2 Build cache status** — workers report cache stats, display in UI
- [ ] **5.4 Notification hooks** — webhook URL for job success/failure (Slack/Discord)

## Firmware Download

After a successful compile, extract the firmware binary and make it downloadable from the UI. Foundation for remote compilation in a later release.

- [ ] **3.1a Worker extracts firmware binary** — read .bin after compile, POST to server
- [ ] **3.1b Server stores firmware** — `/data/firmware/<target>/`, metadata endpoint
- [ ] **3.1c Download button on device row** — `GET /ui/api/targets/{f}/firmware`

## Open Bugs & Tweaks

- [x] **#1** *(1.4.0-dev.3)* — Immediate device state refresh after mutations. Currently only post-OTA and mDNS events trigger an immediate `refresh_target()` / SWR mutate. Other actions leave the UI stale for up to 1s (SWR poll) or 60s (device poller). Fix: after each of these actions, invalidate the relevant cached state so the next UI poll sees the change immediately:
  - **File save** — user edits YAML in the editor → `config_modified` flag should flip instantly (scanner cache needs invalidation)
  - **Version pin/unpin** — user pins a device to a version → `pinned_version` in device metadata should appear immediately (scanner cache + SWR mutate)
  - **Schedule create/update/delete** — user modifies a schedule → schedule state should reflect immediately (SWR mutate on the relevant endpoint)


- [ ] 2 For the scheduler, when a user opens the modal that lets them configure the time, let's give a drop-down for every entry: time, hours, days, or weeks, and let them specify a time. Figure out a format where they can specify more or less arbitrary repetition. I would also like to add a global schedule button that lets me select devices with the checkboxes and lets me update the schedule for all of those devices in one operation. 

- [x] **3** *(1.4.0-dev.2)* — Cron expression validation. Server-side `croniter(expr)` validates on `set_target_schedule` and returns a 400 with "Invalid cron expression: ..." that the client shows as an error toast.

- [ ] 4 I don't know where, but we need to add a view where I can see all schedules in one place. 

- [x] **5** *(1.4.0-dev.3)* — Human-readable schedule column. New toggleable "Schedule" column (default off) with `formatCronHuman()` rendering common presets as short strings ("Daily 02:00", "Sun 02:00", "1st 02:00", "Every 6h"). Complex expressions fall back to the raw cron text. Paused schedules show "(paused)" in muted text.

