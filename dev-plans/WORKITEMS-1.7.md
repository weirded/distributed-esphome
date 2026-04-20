# Work Items — 1.7.0

Theme: **Fleet operator tools + LLM assistance.** Key/value device tags with group-by and filter, declarative worker routing, disk-budget controls, a VS-Code-style file tree editor, plus LLM-powered YAML completion and an ESPHome breaking-change analyzer that scores new releases against the components each managed device actually uses.

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

## Disk Management

LRU-based disk usage controls for both the server and workers. Currently nothing caps the growth of ESPHome version caches, PlatformIO toolchains, compiled firmware, build directories, or job logs. On a worker with limited disk (e.g., a Raspberry Pi), these can silently fill the volume.

### Worker-side

- [ ] **DM.1 Worker disk budget** — new env var `MAX_DISK_USAGE_GB` (default: unlimited). On each job completion, the worker checks total usage of `/esphome-versions/` (versions + builds + PlatformIO). If over budget, evicts in LRU order: oldest unused ESPHome version venvs first (already has `MAX_ESPHOME_VERSIONS` for version count — this adds a size-based cap), then oldest build cache directories, then oldest PlatformIO packages. Logs what was evicted at INFO.
- [ ] **DM.2 Worker disk stats in heartbeat** — add `disk_total_mb`, `disk_used_mb`, `disk_free_mb` (for the `/esphome-versions` mount point) to the worker's `system_info` heartbeat. Server surfaces these on the Workers tab so operators can see when a worker is running low before it fails a compile.
- [ ] **DM.3 Build cache LRU** — the per-target build cache (`/esphome-versions/cache/<target>/`) currently grows unboundedly. Add LRU eviction: track last-access time per target cache dir, evict oldest when total build cache exceeds `MAX_BUILD_CACHE_GB` (env var, default 10GB). The existing `MAX_ESPHOME_VERSIONS` (count-based) stays for version venvs; this adds size-based eviction for the build artifacts.

### Server-side

- [ ] **DM.4 Server disk budget for caches** — `firmware_cache_max_gb` (default 2.0) and `job_log_retention_days` (default 30) live in the Settings store (see 1.6 SP.*). Background task prunes `/data/firmware/` and old job logs on a daily schedule, reading current values from `get_settings()` each run (live-effect). Exposed in the Settings drawer under `Disk management`.
- [ ] **DM.5 Disk usage dashboard** — section on the Workers tab or a new Settings page showing: per-worker disk breakdown (versions, builds, PlatformIO, total), server-side cache sizes (PIO proxy cache, firmware, job logs), and the configured limits. Visual bar showing used/limit per category.

## Worker Constraints

Let users declare which workers can run which jobs. Originated in [issue #59](https://github.com/weirded/distributed-esphome/issues/59) ("Thread devices can't be reached from Windows desktop due to IPv6 limitation — can you auto-detect?"). **Reframed:** instead of trying to probe network reachability (fragile, slow, guesses wrong), let the user express their knowledge of the topology as declarative rules. This also generalizes to every other worker-selection need a user might have — "encrypted devices only go to the on-prem worker", "big configs only go to the beefy worker", "dev YAMLs only go to my laptop".

### Foundation: durable worker identity

The current `client_id` is an auto-generated UUID persisted to `/esphome-versions/.client_id` inside the worker's volume (`client.py:119,213-227`). If the volume wipes, the container gets rebuilt on a different host, or the user blows away their worker setup, they get a new UUID — breaking any saved config that referenced the old one. Worker constraints need a more durable identifier. The answer is: let the user name their workers.

- [ ] **WC.1 `WORKER_NAME` env var** — new optional env on the client (`client.py`). When set, it becomes the worker's primary identifier instead of the auto-UUID. When unset, fall back to the current auto-UUID behavior for backwards compatibility. `WORKER_NAME` values must match `^[a-z0-9][a-z0-9-]{0,63}$` (same slug rules as device names) so they're safe in URLs and UI chips.
- [ ] **WC.2 `WORKER_TAGS` env var** — comma-separated list of free-form tags, e.g. `WORKER_TAGS=ipv6,beefy,on-prem`. Sent at registration and on every heartbeat. Server surfaces them on `/ui/api/workers` for display and for constraint evaluation.
- [ ] **WC.3 Server: name-keyed registry** — `registry.py` accepts a `name` field on `RegisterRequest` (via `protocol.py` — **PROTOCOL_VERSION bump**, see note below). Registry key preference: `name` if provided, else `client_id`. If two workers register with the same `name`, the later one wins (logs a warning about the collision). Existing UUID-keyed workers continue to work unchanged.
- [ ] **WC.4 Protocol extension** — add `name: Optional[str]` and `tags: List[str]` to `RegisterRequest` and `HeartbeatRequest` in both `ha-addon/server/protocol.py` and `ha-addon/client/protocol.py` (byte-identical per PY-6). This is an **additive protocol change** — old workers sending neither field still register fine — so `PROTOCOL_VERSION` stays at its current value per the protocol.py docstring rule ("additive + optional unless PROTOCOL_VERSION is bumped").
- [ ] **WC.5 UI: show worker name + tags** — Workers tab's Hostname column becomes "Name / Hostname": shows `WORKER_NAME` prominently if set, falls back to hostname. New toggleable "Tags" column rendering tags as chips. Connect Worker modal's generated `docker run` command includes `-e WORKER_NAME=<slug>` and an optional `-e WORKER_TAGS=<tags>` pre-filled with a hint.

### Constraint expression

Declarative matching between targets and workers, stored in the per-device `# distributed-esphome:` YAML comment block (same pattern as tags, pin_version, schedules). Constraints are **additive to the existing `pinned_client_id`** — pinning a specific worker on a job still wins over general constraints.

- [ ] **WC.6 Target-side constraint fields** — extend the per-device metadata comment:
  ```yaml
  # distributed-esphome:
  #   worker_requires:       # worker must have ALL of these tags
  #     - ipv6
  #   worker_forbids:        # worker must have NONE of these tags
  #     - cloud
  #   worker_only:           # whitelist by worker name (overrides tags if set)
  #     - home-beefy
  ```
  `read_device_meta` / `write_device_meta` extended to parse + emit these three fields. Surfaced on `/ui/api/targets` as `worker_requires`, `worker_forbids`, `worker_only`.

### Evaluation

- [ ] **WC.7 `claim_next` constraint filter** — in `job_queue.claim_next()`, before a worker can claim a job, check whether its name/tags satisfy the job's target constraints. If not, the job is skipped for that worker and remains PENDING for the next eligible worker to claim. The existing `pinned_client_id` check runs first (explicit pin wins); constraints run second.
- [ ] **WC.8 "No eligible worker" detection** — when a job has been PENDING for > N minutes AND no currently-online worker satisfies its constraints, mark it FAILED with a clear message: *"No eligible worker: target requires tags [ipv6]; online workers: home-pi (tags: []), office-desktop (tags: [beefy])"*. This is the "stuck forever" failure mode — better to fail loudly than hang.

### UI

- [ ] **WC.9 Constraint editor modal** — per-device hamburger menu item "Worker constraints…" opens a modal with three fields (required tags, forbidden tags, whitelisted worker names) plus an "Available tags / workers" hint that lists tags currently in use across the fleet. Saves via the existing `POST /ui/api/targets/{f}/meta` generic endpoint.
- [ ] **WC.10 Queue tab: surface constraint misses** — when a job is PENDING longer than expected and the reason is constraints, the Queue tab's status text shows it (e.g. *"Waiting — no worker tagged `ipv6` is online"*) so the user doesn't stare at a pending job wondering what's wrong.
- [ ] **WC.11 E2E coverage** — mocked Playwright test for the constraint editor modal. Prod hass-4 test: tag one worker with `ipv6`, set `worker_requires: [ipv6]` on a target, trigger compile, verify it lands on the tagged worker (and fails fast with the clear message if no tagged worker is online).

### Notes & non-goals

- **Not auto-detection.** This is deliberately user-declarative. We don't probe reachability, we don't ping from each worker, we don't parse YAML for `manual_ip` to infer things. Users know their network better than we do, and probe-based logic is a maintenance tax.
- **Backwards compatibility.** Workers without `WORKER_NAME` keep UUIDs. Targets without `worker_requires`/`worker_forbids`/`worker_only` accept any worker. Zero breaking changes.
- **Relationship to `pinned_client_id`.** Explicit pin in the UpgradeModal still overrides everything — that's a one-shot manual choice and shouldn't be filtered out by general constraints. Constraints are the persistent default; pins are the override.
- **Related, out of scope:** per-worker `WORKER_CAN_RUN` whitelists (the inverse: worker declares which targets it accepts). Makes sense for shared workers in mixed-trust environments but not needed for the home-lab use case. Revisit in a future release if requested.

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
- [ ] **FT.10 Git status badges** — show modified/untracked badges on files in the tree using `git status --porcelain`. Pairs with 1.6's auto-versioning (AV.*) — the file tree becomes the place Pat sees at a glance which files have uncommitted edits. Fetched once per tree load + re-fetched on save. Small dot or letter glyph next to the filename; hover reveals the status ("modified" / "untracked" / "staged").

## AI/LLM Editor

- [ ] **1.4a Server config** — add-on options for LLM provider, API key, model, endpoint
- [ ] **1.4b Completion endpoint** — `POST /ui/api/ai/complete` proxies to LLM with YAML context
- [ ] **1.4c Inline ghost text** — display LLM suggestions as Monaco inline completions
- [ ] **1.4d Chat endpoint** — `POST /ui/api/ai/chat` for natural language → YAML
- [ ] **1.4e Chat panel in editor** — side panel for prompting, accept/reject generated changes

## ESPHome Release Breaking-Change Analyzer

Given a target ESPHome release, use an LLM to analyze that release's notes against the components each managed device actually uses, and surface per-device breaking-change risk before the user upgrades.

- [ ] **BC.1 Release notes fetcher** — pull ESPHome release notes from the GitHub releases API (fallback: esphome.io changelog); cache under `/data/esphome_releases/<version>.json`
- [ ] **BC.2 Device component inventory** — for each managed device, extract the set of components/platforms in use from its parsed YAML (reuse the existing config cache / `scanner.py` parsing; do not hand-roll)
- [ ] **BC.3 `POST /ui/api/ai/analyze-release`** — input: target version + optional device filter. Sends release notes + per-device component inventory to the configured LLM (reuses the 1.4a provider config). Returns `[{device, risk: none|low|high, affected_components, summary}]`
- [ ] **BC.4 UI entry point** — "Check breaking changes" action on the ESPHome version picker and the Upgrade Outdated flow; results modal grouped by device with expandable per-component detail and a link to the relevant release-notes section
- [ ] **BC.5 Result caching** — key by `(release_version, device_yaml_hash)` so re-opening the modal is instant and LLM calls only happen when something actually changed
