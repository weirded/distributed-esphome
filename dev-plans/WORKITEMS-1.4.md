# Work Items — 1.4.0

Theme: **Fleet management and automation.** Novel features you can't get from the stock ESPHome dashboard — controlling many devices at scale, pinning versions, scheduling upgrades, and downloading compiled firmware.

## Version Pinning

Pin individual devices to a specific ESPHome version. Pinned devices compile with their pinned version even during bulk upgrades. The pin is stored in the per-device `# distributed-esphome:` comment block (`pin_version: 2024.11.1`) — invisible to ESPHome's parser, travels with the config through git/backups.

**Foundation landed in 1.4.0-dev.2:** The generic metadata comment system (`read_device_meta()` / `write_device_meta()`) and the `POST /ui/api/targets/{f}/meta` endpoint already support reading/writing `pin_version`. The `/ui/api/targets` response includes `pinned_version`, and `needs_update` respects it. What remains is the UI + compile guards.

- [x] **VP.1 Scanner: read pin** *(1.4.0-dev.2)* — `read_device_meta()` extracts `pin_version` from the comment block; `get_device_metadata()` merges it as `pinned_version` into the metadata dict returned to callers.
- [x] **VP.2 Scanner: write/clear pin** *(1.4.0-dev.2)* — `write_device_meta()` handles arbitrary key-value writes including `pin_version`. The `POST /ui/api/targets/{f}/meta` endpoint wraps it for the UI (set `pin_version` to a value, or `null` to clear).
- [x] **VP.3 API endpoints** *(1.4.0-dev.3)* — `POST /ui/api/targets/{target}/pin` (set pin, body `{version}`) and `DELETE /ui/api/targets/{target}/pin` (clear pin). Dedicated convenience endpoints on top of the generic `/meta`.
- [x] **VP.4 Hamburger menu** *(1.4.0-dev.3)* — "Pin to current version" (pins to the device's running_version) / "Unpin version (X.Y.Z)" (when pinned). Uses `pinTargetVersion` / `unpinTargetVersion` API client functions.
- [x] **VP.5 UpgradeModal** *(1.4.0-dev.5)* — Warning banner when upgrading a pinned device with a different version. Shows the pinned version, the selected compile version, and explains the pin itself won't change (future scheduled/bulk upgrades still use the pinned version). Revised from "keep pinned checkbox" to a simpler informational warning per bug #10 — the pin is never auto-changed by an upgrade.
- [x] **VP.6 Visual indicator** *(1.4.0-dev.2)* — 📌 pin icon next to device name when `pinned_version` is set (with tooltip showing the version).
- [x] **VP.7 Compile guard** *(1.4.0-dev.3)* — when a pinned device is included in bulk "Upgrade All/Outdated", the compile endpoint reads `pin_version` from the device's metadata comment and uses it instead of the global version. An explicit `version_override` from the UpgradeModal still takes precedence.
- [x] **VP.8 Scheduled Upgrades integration** *(1.4.0-dev.2)* — the `schedule_checker()` background task uses `meta.get("pin_version") or get_esphome_version()` as the compile version, so pinned devices respect their pin during scheduled runs.

## Device Organization

Key/value tags (like AWS resource tags), stored in the per-device `# distributed-esphome:` comment block as a `tags:` map. Users can group the Devices table by any tag key (Notion-style table groups) and filter by `key=value`.

Format in the YAML comment block:
```yaml
# distributed-esphome:
#   tags:
#     location: kitchen
#     floor: "1"
#     env: prod
#     owner: stefan
```

The existing `tags` field landed in 1.4.0-dev.2 as a simple list of strings — that needs to migrate to a key/value map. `read_device_meta()` should accept both shapes during the transition (list → coerce to `{tag: ""}` or warn-and-ignore) and `write_device_meta()` always writes the map shape going forward.

- [ ] **DO.1 Tag schema migration** — `read_device_meta()` accepts either list-of-strings (legacy) or string-keyed map; normalizes to map on read. `write_device_meta()` always writes the map. Add a unit test that round-trips both shapes.
- [ ] **DO.2 Tag CRUD endpoints** — `POST /ui/api/targets/{f}/tags` (set, body `{key, value}`), `DELETE /ui/api/targets/{f}/tags/{key}` (clear). Reuses `read_device_meta()` / `write_device_meta()`. Validates key is non-empty, max 64 chars, no leading/trailing whitespace; value is string, max 256 chars (allow empty for "key present, no value").
- [ ] **DO.3 Tag editor UI** — modal opened from the device hamburger menu ("Edit tags…"). Shows current tags as editable rows: `[key] [value] [×]` plus an "+ Add tag" button. Save persists via `POST /ui/api/targets/{f}/tags` for each changed entry. Datalist autocomplete on `key` from the union of all keys currently in use across the fleet.
- [ ] **DO.4 Tag column** — toggleable "Tags" column on the Devices tab showing each device's tags as compact `key=value` chips (truncated, full set in tooltip). Sortable by string representation.
- [ ] **DO.5 Group-by-tag selector** — top-of-table dropdown: "Group by: [None / location / floor / env / …]". When set, rows are grouped under sticky group headers showing the value (e.g., "location: kitchen — 4 devices"). Devices without that tag key fall into an "— unset —" group at the bottom. Group state persists in localStorage. Like Notion table groups: collapsible group headers, group-level select-all checkbox.
- [ ] **DO.6 Filter by tag** — top-of-table filter chips: click a tag chip in any row to add it as a filter (`location=kitchen`). Multiple chips AND together. Clear-all button. Filter state in URL query string so it survives reloads and is shareable.
- [ ] **DO.7 Bulk tag operations** — extend multi-select on the Devices tab: "Set tag…" (prompts for key+value, applies to all selected via `Promise.all`), "Remove tag…" (prompts for key, removes from all selected). Single summary toast per bulk action.
- [ ] **DO.8 Bulk delete + bulk validate** *(formerly 6.6)* — extend multi-select: bulk delete and bulk validate alongside the existing bulk upgrade.

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
- [x] **SU.4 Schedules overview** *(1.4.0-dev.9)* — new "Schedules" tab next to Devices/Queue/Workers. Shows a table of all scheduled devices with columns: Device, Schedule (cron or one-time datetime), Status (Active/Paused/One-time), Next/Last Run, Version (with 📌 for pinned), Worker. Clicking a row opens the ScheduleModal for that device. Empty state explains how to set up a schedule. Tab badge shows count of devices with any schedule.
- [ ] **SU.6 History** — last N runs per schedule with success/fail counts linking back to queue entries. (Currently the job's `scheduled: true` flag identifies scheduler runs in the queue, but there's no aggregated history view.)

## Build Operations

- [x] **5.2 Build cache status** *(1.4.0-dev.6)* — workers now report `cached_targets` (count of per-target build dirs) and `cache_size_mb` (total cache size) in `system_info`. Workers tab shows "Cache: N targets (M MB)". Foundation: #13 switched from random tmpdirs to stable per-target build dirs under `/esphome-versions/builds/<target>/` so the `.esphome/` PlatformIO cache persists across jobs.

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

- [x] **2** *(1.4.0-dev.4)* — Richer schedule modal + global schedule button. Rewrote `ScheduleModal.tsx` with a friendly interval picker: "Every [N] [hours/days/weeks] [on DOW] at [HH:MM]" with dropdowns for each field, plus a "Cron" mode toggle for power users. Parses existing cron expressions back into the friendly picker state when possible. Also added "Schedule Selected..." to the bulk actions dropdown — applies the same schedule to all checkbox-selected devices in one operation via `Promise.all(setTargetSchedule(...))`. The modal shows the generated cron expression as a reference preview.

- [x] **3** *(1.4.0-dev.2)* — Cron expression validation. Server-side `croniter(expr)` validates on `set_target_schedule` and returns a 400 with "Invalid cron expression: ..." that the client shows as an error toast.

- [x] **4** *(1.4.0-dev.4)* — All-schedules view. The "Schedule" column is now default-visible on the Devices tab, showing human-readable schedule strings for every device in one place. Sorting by this column groups all scheduled devices together. Combined with the 🕐 clock icon on the name, this gives a complete at-a-glance overview without a separate page.

- [x] **5** *(1.4.0-dev.3)* — Human-readable schedule column. New toggleable "Schedule" column (default off) with `formatCronHuman()` rendering common presets as short strings ("Daily 02:00", "Sun 02:00", "1st 02:00", "Every 6h"). Complex expressions fall back to the raw cron text. Paused schedules show "(paused)" in muted text.

- [x] **6** *(1.4.0-dev.4)* — Pin indicator moved from name column to version column. Shows 📌 + pinned version number next to the running version (e.g., "2026.3.3 📌 2024.11.1").

- [x] **7** *(1.4.0-dev.4)* — Hamburger menu too narrow for "Unpin version (2026.3.3)". Changed from fixed `min-w-[160px]` to `min-w-[200px] w-max max-w-[320px]` so it sizes to content (grows for long text, capped at 320px to prevent viewport overflow).

- [x] **8** *(1.4.0-dev.5)* — Moved "Schedule Selected..." out of the Upgrade dropdown into a new "Actions ▾" dropdown between Upgrade and the column picker gear icon. Cleaner separation: Upgrade dropdown is compile-only, Actions is for bulk metadata operations.

- [x] **9** *(1.4.0-dev.5)* — Pin indicator simplified: just 📌 next to the running version (no repeated version number). The pinned version is in the tooltip and the hamburger menu.

- [x] **10** *(1.4.0-dev.5)* — Pinned-device upgrade warning in UpgradeModal. When the selected compile version differs from the device's pin, an amber warning banner explains: "This device is pinned to X, but this upgrade will compile with Y. The pin itself won't change — future scheduled and bulk upgrades will still use the pinned version." The upgrade honors the modal's selected version without touching the pin (VP.7 already handled the compile guard).

- [x] **11** *(1.4.0-dev.5)* — Refresh button (↻) next to the ESPHome version picker in the top nav. Triggers `mutateEsphomeVersions()` to re-fetch from the server (which queries PyPI). New `onRefresh` prop on `EsphomeVersionDropdown`.

- [x] **12** *(1.4.0-dev.6)* — Pinning warning in UpgradeModal: when the user changes the version on a pinned device, the modal now says "Pin update: upgrading will update the pin to X." and the confirm handler calls `pinTargetVersion(target, version)` to update the pin before enqueuing the compile. The pin is updated, not just warned about.

- [x] **13** *(1.4.0-dev.6)* — Compiles starting from scratch every time. Root cause: `run_job` used `tempfile.mkdtemp()` for each job, so the `.esphome/` build cache (PlatformIO compiled objects) was thrown away after every compile. Fix: stable per-target build directory at `/esphome-versions/builds/<target_stem>/`. The bundle extracts over the existing dir (`.esphome/` persists), turning a 60-90s full compile into a 5-10s incremental build when only the YAML changed. The "Clean Cache" button already handles cleanup by wiping all of `/esphome-versions/`. Also fixed: CI was failing because `eslint-plugin-react-hooks@7.0.1` doesn't support `eslint@10` (Dependabot bumped eslint but not the plugin) — added `--legacy-peer-deps` to `npm ci` in CI + removed the deprecated `baseUrl` from `tsconfig.app.json` (TS 6 deprecation).

- [x] **14** *(1.4.0-dev.7)* — Toast on version refresh. The ↻ button now shows "Refreshing ESPHome versions..." on click and "ESPHome version list updated" on completion.
- [x] **15** *(1.4.0-dev.7)* — "Remove Schedule from Selected" added to the Actions dropdown. Filters selected targets to those with a schedule, calls `deleteTargetSchedule` for each via `Promise.all`, shows a summary toast.
- [x] **16** *(1.4.0-dev.7)* — Button height consistency. All dropdown triggers in DevicesTab (Upgrade, Actions, gear) and QueueTab (Retry, Clear) now use the same `h-7 text-[0.8rem]` sizing. Previously Upgrade was `text-xs`, Actions was `text-sm`, and the gear was `text-base` — all different heights.
- [x] **17** *(1.4.0-dev.7)* — One-time scheduled upgrade. The ScheduleModal now has a third "Once" tab with a datetime-local picker. Stores `schedule_once: "<ISO datetime>"` in the YAML comment block. The scheduler fires it when the datetime passes, then auto-clears the field. New endpoint: `POST /ui/api/targets/{f}/schedule/once`. The targets response includes `schedule_once`. The one-time schedule doesn't create a recurring cron — it's fire-and-forget.
- [x] **18** *(1.4.0-dev.8)* — Past-date validation for one-time schedules. Client-side: `min` attribute on datetime-local input. Server-side: rejects datetimes in the past with 400.
- [x] **19** *(1.4.0-dev.8)* — Immediate UI refresh after bulk schedule operations. New `onRefresh` prop on DevicesTab (calls `mutateDevices()`). Bulk schedule set, schedule-once, and remove-schedule all call it after success.
- [x] **20** *(1.4.0-dev.8)* — Bulk schedule-once implemented (was a no-op `onSaveOnce={() => {}}`). Now calls `setTargetScheduleOnce` for each selected target via `Promise.all`.
- [x] **21** *(1.4.0-dev.8)* — "Triggered" column on Queue tab. Shows "🕐 Schedule" or "👤 User". Sortable.
- [x] **22** *(1.4.0-dev.12)* — Unified Upgrade modal. Merged the separate UpgradeModal + ScheduleModal into a single modal with mutually exclusive radio buttons: "Now" (compile immediately) vs "Scheduled" (recurring cron or one-time). Both modes share the worker + version selectors. Entry points: row "Upgrade" button (defaultMode: 'now'), hamburger "Schedule Upgrade..." (defaultMode: 'schedule'), Schedules tab "Edit" (defaultMode: 'schedule', schedule pre-filled). Removed the old ScheduleModal entirely. App.tsx simplified: single `upgradeModalTarget` state with `defaultMode` field.
- [x] **23** *(1.4.0-dev.9)* — Schedules tab implemented (SU.4 + #23). New "Schedules" tab with table: Device, Schedule (cron/datetime), Status (Active/Paused/One-time), Next/Last Run, Version (pinned indicator), Worker. Rows are clickable → opens ScheduleModal. Empty state with setup instructions.
- [x] **25** *(1.4.0-dev.11)* — Schedules tab UX: (a) removed row-click-to-edit, added an explicit "Edit" button per row. (b) Added checkboxes with select-all header + "Remove Selected" button in a toolbar above the table. Selection count shown when > 0. Immediate refresh after bulk remove via `onRefresh()`. New props: `onRefresh`, `onToast`.
- [x] **24** *(1.4.0-dev.10)* — Schedules tab didn't update immediately. Root cause: `get_device_metadata()` in scanner.py was missing `schedule_once` from the merge — the field was returned by `read_device_meta()` but never copied into the result dict. Also the default initialization was missing. Fixed both. All schedule operations (save, save-once, delete, toggle) already called `mutateDevices()` — the data just wasn't being served.
- [ ] 26 Tab consistency: make all four tabs (Devices, Queue, Workers, Schedules) look and function consistently. Same header layout pattern (title + count + toolbar with action buttons), same table styling, same empty-state pattern. Mostly the Schedules tab needs to be brought up to match the established patterns — it's missing the sticky table header, the filter/search bar, the consistent column sorting via `SortHeader`, and the TanStack Table integration that the other three tabs use.
- [x] **27** *(1.4.0-dev.13)* — Schedule Once didn't work because the server rejected "now" as being in the past. Relaxed past-date validation to allow up to 60s grace period so "schedule for now" (immediate one-time) works.
- [x] **28** *(1.4.0-dev.13)* — Default date/time for one-time schedule is now "now" instead of tomorrow at 2am. Also removed the `min` constraint on the datetime-local input.
- [x] **29** *(already working)* — Schedule table already drops one-time jobs after execution because `schedule_once` is cleared from the YAML metadata by the scheduler, so the target no longer matches the `t.schedule || t.schedule_once` filter.
- [x] **30** *(already implemented in 1.4.0-dev.8)* — The `schedule_checker` in main.py already auto-clears `schedule_once` from the YAML comment block after successful execution (line 534-536). 

