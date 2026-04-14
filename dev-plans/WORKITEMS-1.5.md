# Work Items — 1.5.0

Theme: **Editor and config management.** Turn the built-in editor into a real development environment with file browsing, automatic version history, and URL import. Every YAML save is auto-versioned via a local git repo — users get history, diff, and rollback for free with zero config.

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

## Auto-Versioning (local git, zero config)

Every save creates a git commit automatically. Users get per-file history, diff, and rollback without touching git or configuring anything. The config directory becomes a local git repo on first startup; existing git repos are left intact.

**Why git:** Diff is free (`git diff`), history is free (`git log --follow`), rollback is `git checkout <hash> -- <file>` + a new commit, Monaco already has a diff editor in the bundle, and the `git` binary ships in the HA add-on base image (zero image size cost). The alternative (copy-on-write snapshots + DIY diff) is more code and worse tooling.

- [ ] **AV.1 Auto-init** — on server startup, if `/config/esphome/` is not a git repo, run `git init` + `git add -A` + initial commit "Initial commit by distributed-esphome". If it's already a git repo (user set it up themselves), skip init. Add `.gitignore` for `secrets.yaml` and `.esphome/` if not already present. Log the outcome at INFO.
- [ ] **AV.2 Auto-commit on save** — after every file-writing operation (editor save, rename, duplicate, pin, schedule, delete), run `git add <file>` + `git commit -m "<action>: <file>"` in a background task. Debounce window of 2s so rapid saves (e.g., save + pin in quick succession) coalesce into one commit. Commit author set to `"HA User <ha@distributed-esphome.local>"`. Non-blocking: save returns immediately, commit happens async.
- [ ] **AV.3 History endpoint** — `GET /ui/api/files/{path}/history` — returns `[{hash, message, date, lines_added, lines_removed}]` via `git log --follow --stat -- <path>`. The `--follow` flag tracks renames. Paginated (default 50 entries).
- [ ] **AV.4 Diff endpoint** — `GET /ui/api/files/{path}/diff?from=<hash>&to=<hash|HEAD>` — returns unified diff string via `git diff <from> <to> -- <path>`. If `to` is omitted, diffs against working tree (uncommitted changes).
- [ ] **AV.5 Rollback endpoint** — `POST /ui/api/files/{path}/rollback` body `{hash}` — runs `git checkout <hash> -- <path>` then auto-commits as "Revert <file> to <short-hash>". Returns the restored file content. Invalidates the scanner config cache.
- [ ] **AV.6 History panel in editor** — sidebar or dropdown in the editor modal showing per-file commit history (AV.3). Each entry shows date, message, and `+N/-M` diff stat. Click an entry → opens Monaco diff editor (current vs that version, via AV.4). "Restore this version" button calls AV.5.
- [ ] **AV.7 Config Diff on compile** — when a compile job is enqueued, record the current HEAD hash on the job (new `Job.config_hash` field). The "what changed since last compile" diff is `git diff <last_job_hash> <current_hash> -- <target>`. Replaces the snapshot-file approach (old 1.5a/1.5b) — no `/data/config_snapshots/` directory needed.
- [ ] **AV.8 Diff viewer in editor** — Monaco diff editor component. Used by AV.6 (history comparison) and AV.7 (changes since last compile). Reuse `@monaco-editor/react`'s `DiffEditor` — it's already in the bundle, just not imported.
- [ ] **AV.9 Git status in file tree** — if the file tree editor (FT section) lands in the same release: show modified/untracked badges on files using `git status --porcelain`. If FT doesn't land, defer this to when it does.
- [ ] **AV.10 Tests** — unit tests: auto-init on empty dir, auto-init skips existing repo, auto-commit creates a commit with correct message, debounce coalesces rapid writes, history endpoint returns correct entries, diff endpoint returns correct diff, rollback restores content + creates a new commit. Integration test: save via editor API → verify `git log` shows the commit.

## GitHub Sync (optional remote)

Connect the local git repo to a GitHub (or any git remote) for backup and team collaboration. Private repos work identically to public. This is stretch scope for 1.5.0 — can slip to 1.6.0 if auto-versioning alone fills the release.

**Auth options:** GitHub Personal Access Token (HTTPS) or SSH deploy key. Stored in add-on options (encrypted at rest by HA Supervisor). No OAuth flow needed — PATs are simpler and work for private repos.

- [ ] **GS.1 Remote configuration** — add-on options: `git_remote_url` (string, e.g. `https://github.com/user/esphome-configs.git`), `git_remote_token` (secret string, PAT for HTTPS auth), `git_remote_ssh_key` (secret string, for SSH auth). On startup, if configured, run `git remote add origin <url>` (or update if remote exists). Validate connectivity with `git ls-remote`.
- [ ] **GS.2 Push** — `POST /ui/api/git/push`. Runs `git push origin main`. Called automatically after each auto-commit batch (configurable: after every commit, every N minutes, or manual-only). Auth via credential helper for HTTPS or SSH key file for SSH. Surfaces errors (auth failure, force-push rejected, network) via the `/ui/api/info` response so the UI can show a banner.
- [ ] **GS.3 Pull** — `POST /ui/api/git/pull`. Runs `git pull --rebase origin main`. Called on startup (if remote configured) and on-demand via UI button. On conflict: abort the rebase, keep local, log the conflict at WARNING, surface it in the UI as "Remote has changes that conflict with local edits — resolve manually or force-push".
- [ ] **GS.4 Sync status UI** — indicator in the header or settings page showing: last push time, last pull time, sync errors. "Push now" / "Pull now" buttons.
- [ ] **GS.5 `.gitignore` management** — ensure `secrets.yaml` is always in `.gitignore` (auto-add on init and on remote config). Warn in the UI if `secrets.yaml` has been committed (it contains WiFi passwords and API keys).

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

## Firmware Download

After a successful compile, extract the firmware binary and make it downloadable from the UI. Foundation for remote compilation in a later release.

- [ ] **3.1a Worker extracts firmware binary** — read .bin after compile, POST to server
- [ ] **3.1b Server stores firmware** — `/data/firmware/<target>/`, metadata endpoint
- [ ] **3.1c Download button on device row** — `GET /ui/api/targets/{f}/firmware`

## PlatformIO Package Cache Proxy

Optional caching proxy on the server that intercepts workers' PlatformIO downloads. First worker to compile a given platform/toolchain fetches from the internet; every subsequent worker gets it from the server over LAN in seconds. Eliminates the biggest time sink in cold compiles (~200-400MB of toolchains downloaded per platform per worker).

```
Worker --HTTP--> Server :8766 --HTTPS--> registry.platformio.org / github.com
                    |
              /data/pio-cache/
              (LRU, disk-limited)
```

Enabled via add-on option `pio_cache_enabled: true` (default off). Workers detect the proxy URL from the server info response and set `HTTPS_PROXY` on the ESPHome subprocess. Workers that can't reach the proxy (e.g., running outside the LAN) fall back to direct downloads transparently.

- [ ] **PC.1 Caching proxy listener** — new `aiohttp` app on a second port (e.g., 8766), started conditionally when `pio_cache_enabled` is set. Handles standard HTTP proxy `CONNECT` requests: opens upstream HTTPS connection, streams response to the worker, writes the response body to `/data/pio-cache/<sha256(url)>` on first request. Subsequent requests for the same URL serve from disk. Only caches responses from `*.platformio.org` and `github.com/platformio/*` — all other traffic is passed through uncached.
- [ ] **PC.2 Cache storage + LRU eviction** — `/data/pio-cache/` directory. Each cached file has an access-time timestamp updated on every hit. Background task runs eviction when total size exceeds `pio_cache_max_gb` (add-on option, default 5GB). Evicts least-recently-accessed files first until under the limit. Cache stats exposed via `/ui/api/server-info` (`pio_cache_size_mb`, `pio_cache_entries`).
- [ ] **PC.3 Worker integration** — worker reads `pio_proxy_url` from the `/api/v1/workers/register` or heartbeat response (server advertises it when enabled). Sets `HTTPS_PROXY=<url>` on the `subprocess_env` passed to ESPHome. Falls back to no proxy if the field is absent or the proxy is unreachable (connectivity check with a 2s timeout on job start).
- [ ] **PC.4 Add-on options** — `pio_cache_enabled` (bool, default false), `pio_cache_max_gb` (float, default 5.0), `pio_cache_port` (int, default 8766). Documented in `DOCS.md` and `config.yaml` schema.
- [ ] **PC.5 Cache management UI** — server info panel or settings section showing: cache enabled/disabled, current size / limit, entry count. "Clear cache" button. Workers tab shows per-worker "Proxy: yes/no" indicator.
- [ ] **PC.6 Tests** — unit tests: proxy caches a GET response, second request serves from disk, LRU eviction removes oldest when over limit, non-platformio URLs pass through uncached. Integration test: two sequential `pip install platformio && pio pkg install` calls, second is faster.

## Disk Management

LRU-based disk usage controls for both the server and workers. Currently nothing caps the growth of ESPHome version caches, PlatformIO toolchains, compiled firmware, build directories, or job logs. On a worker with limited disk (e.g., a Raspberry Pi), these can silently fill the volume.

### Worker-side

- [ ] **DM.1 Worker disk budget** — new env var `MAX_DISK_USAGE_GB` (default: unlimited). On each job completion, the worker checks total usage of `/esphome-versions/` (versions + builds + PlatformIO). If over budget, evicts in LRU order: oldest unused ESPHome version venvs first (already has `MAX_ESPHOME_VERSIONS` for version count — this adds a size-based cap), then oldest build cache directories, then oldest PlatformIO packages. Logs what was evicted at INFO.
- [ ] **DM.2 Worker disk stats in heartbeat** — add `disk_total_mb`, `disk_used_mb`, `disk_free_mb` (for the `/esphome-versions` mount point) to the worker's `system_info` heartbeat. Server surfaces these on the Workers tab so operators can see when a worker is running low before it fails a compile.
- [ ] **DM.3 Build cache LRU** — the per-target build cache (`/esphome-versions/cache/<target>/`) currently grows unboundedly. Add LRU eviction: track last-access time per target cache dir, evict oldest when total build cache exceeds `MAX_BUILD_CACHE_GB` (env var, default 10GB). The existing `MAX_ESPHOME_VERSIONS` (count-based) stays for version venvs; this adds size-based eviction for the build artifacts.

### Server-side

- [ ] **DM.4 Server disk budget for caches** — new add-on options for each cache directory: `firmware_cache_max_gb` (default 2.0), `job_log_retention_days` (default 30). Background task prunes `/data/firmware/` and old job logs on a daily schedule. Exposed in server info.
- [ ] **DM.5 Disk usage dashboard** — section on the Workers tab or a new Settings page showing: per-worker disk breakdown (versions, builds, PlatformIO, total), server-side cache sizes (PIO proxy cache, firmware, job logs), and the configured limits. Visual bar showing used/limit per category.

## Import

- [ ] **2.1c Create device: import from URL** — fetch config from GitHub/project URL

## Rebrand: ESPHome Fleet

The product has grown beyond its original "distribute ESPHome compiles to faster machines" identity — 1.4 added fleet-scale management (version pinning, scheduled upgrades, device tags, Schedules tab). The current name "Distributed ESPHome" overweights the compile mechanism and underweights the actual user value. Rebrand to **"ESPHome Fleet"**.

**Scope: soft rebrand, user-facing only.** Every user-visible string changes; no internal identifiers change. Zero breaking changes for existing installs — no re-install, no re-register, no lost config, no new Docker image paths, no moved repo.

**What stays the same:** repo name (`weirded/distributed-esphome`), Docker image names (`esphome-dist-server`, `esphome-dist-client`), add-on slug (`esphome_dist_server`), Python module names, logger names, custom integration domain (`distributed_esphome` from 1.4.1 HI.*), and the YAML comment marker (`# distributed-esphome:` — parsed from users' existing YAML files; changing it would be a breaking migration).

- [ ] **RB.1 config.yaml** — `name: "ESPHome Distributed Build Server"` → `name: "ESPHome Fleet"` (line 1, add-on store display + add-on page header). `panel_title: "ESPH Distributed"` → `panel_title: "ESPHome Fleet"` (line 19, HA sidebar label). Review `description:` and update if it overweights "distributed."
- [ ] **RB.2 UI header + HTML title** — `App.tsx:482` `<span>Distributed Build</span>` → `<span>Fleet</span>` (header now reads `ESPHome [logo] Fleet v1.5.0-dev.N`). `ui/index.html:7` `<title>ESPHome Distributed Build</title>` → `<title>ESPHome Fleet</title>`. Also update `server/static/index.html:7` for completeness (gets regenerated on next `npm run build`).
- [ ] **RB.3 README.md** — heading (`# Distributed ESPHome` → `# ESPHome Fleet`), image alt text, ASCII diagram (`ESPH Distributed` → `ESPHome Fleet`), install instructions (`**ESPHome Distributed Build Server**` → `**ESPHome Fleet**`), sidebar reference (`**ESPH Distributed**` → `**ESPHome Fleet**`), and rewrite the opening tagline/blurb to position "ESPHome Fleet" as the product with distributed compile as one capability among many (version pinning, scheduled upgrades, tags).
- [ ] **RB.4 DOCS.md** — heading `# ESPHome Distributed Build Server` → `# ESPHome Fleet`. Sidebar reference `**ESPH Distributed**` → `**ESPHome Fleet**`. Review opening blurb for stale framing.
- [ ] **RB.5 repository.json** — `"name": "Distributed ESPHome"` → `"name": "ESPHome Fleet"` (HA add-on store display name).
- [ ] **RB.6 CHANGELOG.md entry** — add a callout to the 1.5.0 section: *"Rebrand: now called ESPHome Fleet. Same add-on, same Docker images, no migration needed — just a new name that better describes what the tool does."* User-facing framing only; don't list `panel_title` changed etc.
- [ ] **RB.7 CLAUDE.md project overview** — rewrite line 7: `"ESPHome Fleet (internally: distributed-esphome) manages fleets of ESPHome devices — offloads compilation to remote workers, schedules upgrades, pins versions per device, and organizes devices via tags. Runs as a Home Assistant add-on with a built-in local worker."` Briefly note the naming convention: user-facing docs/UI say "ESPHome Fleet"; code identifiers, repo, and Docker paths keep the `distributed_esphome` / `esphome-dist-*` names.
- [ ] **RB.8 Dockerfile labels + startup log + compose comment** — `Dockerfile:7` `io.hass.name`, `Dockerfile:8` `io.hass.description`, `rootfs/etc/services.d/esphome-dist-server/run:2` startup echo, `server/main.py:962,1031` INFO log lines ("Starting/Shutting down"), `docker-compose.worker.yml:1` header comment. **PY-4 trigger** (Dockerfile changes) — bump `IMAGE_VERSION` + `MIN_IMAGE_VERSION` when this lands.

**Verification:** deploy to hass-4 and confirm: HA sidebar reads "ESPHome Fleet", add-on page header reads "ESPHome Fleet", UI top nav reads `ESPHome [logo] Fleet v1.5.0-dev.N`, browser tab title reads "ESPHome Fleet", `ha addons logs` shows "Starting ESPHome Fleet" on restart, and the GitHub README renders with the new heading.

## Open Bugs & Tweaks

