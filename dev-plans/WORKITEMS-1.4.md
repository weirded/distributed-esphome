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

## Create Device

Minimal "new" + "duplicate" flow. Deliberately simple: no platform/board/WiFi wizard (that can come later in 1.7 if it earns its keep). The whole interaction is one shared modal + the existing editor.

**Shared modal:** single text input "Device filename" with `.yaml` auto-appended, Save/Cancel buttons. Used by both entry points. Validates: non-empty, no path separators, no collision with existing file, matches `^[a-z0-9][a-z0-9-]*$` (ESPHome name constraint).

**New device flow:**
1. "+ New Device" button at the top of the Devices tab (next to the bulk action dropdowns)
2. Opens the shared modal
3. On save: server writes a minimal stub YAML with `esphome: { name: <filename-without-extension> }` pre-filled, then UI opens the editor on the new file

**Duplicate device flow:**
1. "Duplicate…" item in the per-row hamburger menu
2. Opens the shared modal pre-filled with `<source>-copy` as the default name
3. On save: server reads the source file, rewrites the top-level `esphome.name` to match the new filename, writes to the new path, then UI opens the editor on the new file

- [x] **CD.1 Minimal stub generator** *(1.4.0-dev.22)* — `scanner.create_stub_yaml(name)` uses `yaml.safe_dump` (PY-1) and appends a `# Add board, platform, and components here.` guidance comment. Three unit tests: name round-trips through `safe_load`, the output parses cleanly, and the guidance comment is present.
- [x] **CD.2 Duplicate helper** *(1.4.0-dev.22)* — `scanner.duplicate_device(config_dir, source, new_name)` reads source, rewrites `esphome.name`, and when `name` is a `${substitution}` reference it rewrites the substitution entry instead — so files that indirect through `substitutions.name` keep the indirection intact. Raises `FileNotFoundError`/`ValueError` on bad input. Documented that `safe_dump` drops comments (deliberate). Six unit tests covering: simple name rewrite, field preservation, substitution rewrite, missing source, invalid YAML, source without esphome block.
- [x] **CD.3 Create endpoint** *(1.4.0-dev.22)* — `POST /ui/api/targets` body `{filename, source?}`. Strips optional `.yaml` suffix, validates slug regex `^[a-z0-9][a-z0-9-]*$` + max-64-char length, uses `safe_resolve` to block path traversal, rejects collision, dispatches to `create_stub_yaml` or `duplicate_device`, writes the file, and returns `{target: "<name>.yaml", ok: true}`. Seven server-side integration tests (stub, .yaml normalization, collision, path traversal, invalid slug, duplicate, missing source).
- [x] **CD.4 NewDeviceModal** *(1.4.0-dev.22)* — new `src/components/NewDeviceModal.tsx`. Props: `mode: 'new' | 'duplicate'`, `sourceTarget?`, `existingTargets`, `onCreate`, `onClose`, `onToast`. Client-side slug validation matches the server regex + checks for collision against the known target list, with inline error. Enter key submits when valid. Button label dynamic: `Create` vs `Duplicate`.
- [x] **CD.5 "+ New Device" button** *(1.4.0-dev.22)* — placed in the Devices tab toolbar `.actions` div next to the Upgrade dropdown. Opens the modal in `mode="new"`.
- [x] **CD.6 "Duplicate…" hamburger item** *(1.4.0-dev.22)* — added to the per-row device context menu under the Config section, next to Rename. Opens the modal in `mode="duplicate"` with the source target name pre-filled as `<source>-copy`.
- [x] **CD.7 E2E coverage** *(1.4.0-dev.22)* — `ha-addon/ui/e2e/create-device.spec.ts` adds six mocked tests: toolbar button opens modal; new-device flow creates + opens editor; slug validation blocks uppercase/underscores; collision with an existing target disables the Create button; hamburger Duplicate item opens the modal with pre-filled `<source>-copy`; duplicate flow creates + opens editor. Full mocked suite now runs 43 tests (was 37). Fixture mock for `POST /ui/api/targets` echoes the requested filename back so the editor opens on the correct target.

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
- [ ] **SU.7 Harden the scheduler loop** — replace the 60s fixed-tick `schedule_checker()` with a next-fire-driven loop. Reviewed APScheduler and aiocron as alternatives; decided against both. APScheduler would introduce a second source of truth alongside the YAML comment (its job registry), defeating the point of storing schedules in the config itself; its misfire tracking and next-fire cache would reset every time we rebuilt jobs from YAML on scan. aiocron is a thin wrapper around `croniter` that buys us nothing we don't already have. Keeping DIY preserves the single source of truth and matches the 1.3.1 hardening ethos (harden with tests rather than library substitution). Concrete changes:
  - **Next-fire-driven sleep** — on each wake, compute next fire time for every enabled schedule, sleep until the earliest one (capped at 60s so config changes land promptly). Eliminates the up-to-60s delay between when a schedule is due and when it fires.
  - **Sub-minute resolution** — naturally falls out of the next-fire sleep. Tests that advance a frozen clock to verify a `*/1 * * * *` schedule fires at 60s intervals exactly.
  - **Jitter** — optional `schedule_jitter_seconds: 120` per-device meta that offsets the fire time by a random ±N seconds. When 50 devices are all `0 2 * * *`, this spreads them across 2 minutes instead of thundering-herd enqueueing in one tick.
  - **Misfire grace window** — explicit `schedule_misfire_grace_seconds` (default 300). If the server was down and `now > next_fire + grace`, log it and skip (don't fire late); if within grace, fire once and skip the intermediate missed fires (matches current behavior, made explicit).
  - **In-memory next-fire cache** — dict `{target: next_fire_datetime}` rebuilt on config scan and on any `/ui/api/targets/{f}/schedule` mutation. O(1) lookup for the Schedules tab "next run" column instead of recomputing on every `/ui/api/targets` request.
  - **History ring buffer** — in-memory `{target: [(fired_at, job_id, outcome)] * N}` populated by the scheduler on enqueue and by a job completion listener. Powers SU.6 without adding persistence (history survives until server restart, which is acceptable for a "did Sunday 2am fire?" debugging view).
  - **Tests** — `tests/test_scheduler.py`: frozen-clock advances through cron ticks and asserts correct fire times; misfire grace boundaries; jitter is within bounds; next-fire cache stays consistent with YAML edits; history ring buffer caps at N. Follows the B.3 `test_check_timeouts_behavior_is_purely_deadline_based` pattern — pure deadline-vs-clock assertions, no sleep.

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
- [x] **26** *(1.4.0-dev.14)* — Tab consistency: rewrote Schedules tab to use TanStack Table with SortHeader, search/filter input, sticky table headers via `.table-wrap`, and the same card + toolbar layout as Devices/Queue/Workers tabs. Checkbox selection now uses TanStack row selection. Empty state wrapped in the same card container.
- [x] **27** *(1.4.0-dev.13)* — Schedule Once didn't work because the server rejected "now" as being in the past. Relaxed past-date validation to allow up to 60s grace period so "schedule for now" (immediate one-time) works.
- [x] **28** *(1.4.0-dev.13)* — Default date/time for one-time schedule is now "now" instead of tomorrow at 2am. Also removed the `min` constraint on the datetime-local input.
- [x] **29** *(already working)* — Schedule table already drops one-time jobs after execution because `schedule_once` is cleared from the YAML metadata by the scheduler, so the target no longer matches the `t.schedule || t.schedule_once` filter.
- [x] **30** *(already implemented in 1.4.0-dev.8)* — The `schedule_checker` in main.py already auto-clears `schedule_once` from the YAML comment block after successful execution (line 534-536). 
- [x] **31** *(1.4.0-dev.16)* — Added "Latest" option to the ESPHome version dropdown in the UpgradeModal (value: empty string, shown as `Latest — currently <default>`). For schedule saves, the selected version is now threaded through `onSaveSchedule`/`onSaveOnce` and applied to the device pin: "Latest" unpins the device (so it tracks the server default at run time), a specific version pins to that version. The scheduler already resolves `pin_version or get_esphome_version()` at fire time, so "Latest" schedules now correctly track whatever is currently installed.
- [x] **32** *(1.4.0-dev.15)* — Schedules tab cell rendering now matches the other tabs. Device cell uses the `device-name` + `device-filename` CSS classes (bold 600 + monospace muted filename) inside a fragment, identical to DevicesTab and QueueTab. Schedule/version cells use inline `fontFamily: monospace` instead of Tailwind utility classes. Removed all Tailwind `text-[Npx]` utilities from cells so they inherit the base table cell typography.
- [x] **33** *(1.4.0-dev.16)* — Timezone bug in one-time schedule default. `datetime-local` inputs expect a local wall-clock value (no timezone). The default was built with `new Date().toISOString().slice(0, 16)` which returns UTC, so west-of-UTC users saw "now" displayed many hours in the future. Fixed by building the default from local `getFullYear/getMonth/...Hours` components. The submit path (`new Date(onceDate).toISOString()`) already parses the datetime-local value as local and converts to UTC for storage, so no server-side change was needed.
- [x] **34** *(1.4.0-dev.20)* — Moved the Now/Scheduled mode radios in UpgradeModal below the Worker + Version selectors so the "what to upgrade to" choice comes before the "when to run it" choice. Also made the dialog title dynamic: `Upgrade — X` in Now mode, `Schedule Upgrade — X` in Scheduled mode.
- [x] **35** *(1.4.0-dev.20)* — Added HA device deep-link to the HA column in the Devices tab. When a device is matched to HA by MAC, we now also capture the HA device_id (via the Supervisor template API — added `ha_mac_to_device_id` to the HA entity poller), thread it through `_ha_status_for_target`, and expose it as `ha_device_id` on the targets response. The Devices tab HA column renders `Yes ↗` as a clickable link that opens `/config/devices/device/<id>` in a new tab. The URL is built by `haDeepLink(path)` in `utils.ts`, which uses `window.top.location.origin` when inside HA Ingress and falls back to `:8123` on the same hostname when running standalone.
- [x] **36** *(1.4.0-dev.20 — verified working)* — "Schedule Upgrade..." button in the hamburger menu was already present and functional: it opens the unified UpgradeModal in Scheduled mode (via `onSchedule(t) → handleOpenUpgradeModal(t, 'schedule')`). Verified end-to-end via Playwright on hass-4. Also added a dynamic dialog title — `Schedule Upgrade — X` vs `Upgrade — X` — so the user can tell which mode they're in.
- [x] **37** *(1.4.0-dev.20)* — Fixed the three "Remove Schedule" actions that weren't actually removing schedules: (a) server DELETE `/ui/api/targets/{f}/schedule` now also removes `schedule_once` (it used to only touch `schedule`, `schedule_enabled`, `schedule_last_run`, so one-time schedules stuck around forever); (b) DevicesTab bulk "Remove Schedule from Selected" filter now includes devices with `schedule_once` (previously only checked `schedule`); (c) UpgradeModal's "Remove existing schedule" path in App.tsx now also closes the modal on success.
- [x] **38** *(1.4.0-dev.20)* — Renamed the version dropdown option from "Latest — currently X" to "Current (X)". The previous "Latest" label was technically incorrect because newer versions may exist.
- [x] **39** *(1.4.0-dev.19)* — **Schedules never fired in production.** Root cause: `croniter>=1.3` was added to `ha-addon/server/requirements.txt` in the scheduler PR but `scripts/refresh-deps.sh` was never rerun, so `requirements.lock` never picked it up. The Dockerfile installs the lock via `--require-hashes`, so the production image had no `croniter`. `schedule_checker` catches `ImportError` and `return`s with a warning log, so the task silently stopped running — no exceptions, no scheduler. CI tests passed because CI installs from `requirements.txt` directly. Fix: (a) regenerated `requirements.lock` (now contains `croniter==6.2.2`), (b) added a new invariant **PY-8** to `scripts/check-invariants.sh` — every direct dep in `requirements.txt` must also be pinned in `requirements.lock`, so this class of bug fails CI instead of shipping, (c) added a `/ui/api/_debug/scheduler` diagnostic endpoint (task state + last tick + tick count + last error) to make silent-task failures observable in future.
- [x] **40** *(1.4.0-dev.23)* — Schedule column on the Devices tab now also renders `schedule_once` values (previously only checked `schedule`, so one-time schedules showed as "—"). Extracted `formatCronHuman()` into `utils.ts` so both DevicesTab and SchedulesTab humanize cron expressions identically. Removed `fontFamily: monospace` from the SchedulesTab Schedule cell so it matches the proportional font used by the other columns.
- [x] **41** *(1.4.0-dev.23)* — HA column deep-link now works for (a) unmanaged rows (devices HA knows about but we don't have YAML for — the "Yes" indicator in the HA column is now a clickable link too) and (b) offline managed devices that don't have a live MAC in the poller right now. Server: the HA entity poller now additionally builds an `entity_id → device_id` and derives `ha_name_to_device_id: dict[str, str]`; `_ha_status_for_target` uses it as a fallback when the MAC path doesn't produce a device_id (which is the common case for offline devices).
- [x] **42** *(1.4.0-dev.23)* — Cancelling out of the editor on a just-created device now deletes the stub file. Added `onSaved` prop to EditorModal that fires right before `onClose` for Save/Save-and-Upgrade success paths. App.tsx tracks unsaved new-device targets in a ref (`unsavedNewTargetsRef`); the editor's `onClose` handler checks the ref and calls `deleteTarget(target, false)` if the close happened without a save. Works for both "+ New Device" and "Duplicate…" flows.
- [x] **43** *(1.4.0-dev.23)* — Duplicating a YAML containing `!include` (or any custom ESPHome tag like `!secret`, `!lambda`, `!extend`, `!remove`) used to fail because stdlib `yaml.safe_load` refused to parse unknown tags. The user saw this as a toast "Source invalid: could not determine a constructor for the tag '!include'" — which they reasonably read as a JavaScript error about a missing include file. Fix: `scanner.duplicate_device` now uses a custom `SafeLoader`/`SafeDumper` pair with a multi-constructor for the `!` tag prefix — it wraps arbitrary tagged scalars/sequences/mappings in an opaque `_Tagged` placeholder and re-emits them on dump, so custom tags round-trip cleanly. Two new unit tests (`!include`/`!secret` preservation, plus combined substitution-rewrite-with-include).
- [ ] 44 Small tweak to the editor and logs windows. They should take most of the visible space on the page with a small border around them. 