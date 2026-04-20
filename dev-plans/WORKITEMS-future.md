# Work Items — Future / Advanced Features

Items with less certainty on scope or priority. Will be shaped into a release when the time comes. Releases are scope-driven, not time-boxed (see `CLAUDE.md` → Project Tracking) — items graduate from here into a specific `WORKITEMS-X.Y.md` file only when they're selected for a release, not on a calendar.

Section order here is not a priority signal.

## GitHub Sync (optional remote)

Connect the local git repo to a GitHub (or any git remote) for backup and team collaboration. Private repos work identically to public. Pairs naturally with 1.6's auto-versioning (AV.*) — once every save is a git commit, pushing upstream is the obvious next step.

**Auth options:** GitHub Personal Access Token (HTTPS) or SSH deploy key. Stored in add-on options (encrypted at rest by HA Supervisor). No OAuth flow needed — PATs are simpler and work for private repos.

- [ ] **GS.1 Remote configuration** — add-on options: `git_remote_url` (string, e.g. `https://github.com/user/esphome-configs.git`), `git_remote_token` (secret string, PAT for HTTPS auth), `git_remote_ssh_key` (secret string, for SSH auth). On startup, if configured, run `git remote add origin <url>` (or update if remote exists). Validate connectivity with `git ls-remote`.
- [ ] **GS.2 Push** — `POST /ui/api/git/push`. Runs `git push origin main`. Called automatically after each auto-commit batch (configurable: after every commit, every N minutes, or manual-only). Auth via credential helper for HTTPS or SSH key file for SSH. Surfaces errors (auth failure, force-push rejected, network) via the `/ui/api/info` response so the UI can show a banner.
- [ ] **GS.3 Pull** — `POST /ui/api/git/pull`. Runs `git pull --rebase origin main`. Called on startup (if remote configured) and on-demand via UI button. On conflict: abort the rebase, keep local, log the conflict at WARNING, surface it in the UI as "Remote has changes that conflict with local edits — resolve manually or force-push".
- [ ] **GS.4 Sync status UI** — indicator in the header or settings page showing: last push time, last pull time, sync errors. "Push now" / "Pull now" buttons.
- [ ] **GS.5 `.gitignore` management** — ensure `secrets.yaml` is always in `.gitignore` (auto-add on init and on remote config). Warn in the UI if `secrets.yaml` has been committed (it contains WiFi passwords and API keys).

## HA Native Updates

Make the per-device update flow behave like HA's stock [`esphome` integration](https://www.home-assistant.io/integrations/esphome/) — surfaced in **Settings → Updates**, clickable from the HA frontend update card, alongside HA Core / add-on / HACS updates. Extends HI.3 from 1.4.1 (which delivered the basic `UpdateEntity` per managed device) with the polish that makes HA-native update UX actually feel native: release notes, progress reporting, skip-version persistence, and "update all" coalescing.

**Trigger path:** user clicks Install in HA's update card → HA calls `update.install` service on `update.esphome_fleet_<device>` → our `EsphomeFleetUpdate.async_install()` → `POST /ui/api/compile` → job lands in Fleet's queue → progress reports back via coordinator polling → `in_progress` reflects on the HA entity. No separate Fleet UI for updates — HA's update card is the one surface.

Scope: pure `custom_integration/esphome_fleet/` work. No add-on UI changes, no worker changes.

| Area | HI.3 in 1.4.1 | UE.* later |
|---|---|---|
| `UpdateEntity` exists | ✅ | — |
| `installed_version` + `latest_version` (global) | ✅ | — |
| Install button → compile API | ✅ | — |
| `release_url` (points at ESPHome's changelog) | ❌ | ✅ |
| `release_summary` (breaking changes snippet) | ❌ | ✅ |
| `entity_picture` (device-specific icon) | ❌ | ✅ |
| `in_progress` / `update_percentage` wired to queue state | ❌ | ✅ |
| Pinned-version awareness in `latest_version` | ❌ | ✅ |
| "Skip this version" persists across polls | ❌ | ✅ |
| "Update all" coalesces into one batch compile run | ❌ | ✅ |

- [ ] **UE.1 ESPHome release notes fetcher** — coordinator gains a 24h-cached fetch of ESPHome's GitHub releases metadata (`api.github.com/repos/esphome/esphome/releases/tags/<version>`). No auth needed (public API; unauth rate limit is 60/hr, this is <1 req/day). Returns `release_url` and a parsed `release_summary` (first paragraph or the "breaking changes" section if present). Cache keyed by `<version>`; eviction on coordinator reload.
- [ ] **UE.2 Wire release metadata on entities** — `EsphomeFleetUpdate` entity sets `release_url` and `release_summary` from UE.1's cache for the current `latest_version`. HA's update card renders these under the "Install" button as expected.
- [ ] **UE.3 `entity_picture`** — pick a device-specific image. Start simple: one icon per platform family (esp32 / esp8266 / rp2040 / …) derived from the target's `platform` / `board`. Future extension: let the user set an explicit `entity_picture_url` in the `# distributed-esphome:` comment block (same pattern as `tags`, `pin_version`, `schedule`), and have the entity prefer that if set.
- [ ] **UE.4 Progress reporting** — wire `in_progress: True` on the entity when the user-initiated compile job is PENDING or WORKING; derive `update_percentage` from either the worker's status_text (if it carries a percent) or from elapsed-vs-expected compile time. Clear `in_progress` when the job reaches any terminal state. Enables HA's update card progress bar.
- [ ] **UE.5 Pinned-version awareness** — if the target has `pinned_version` set in its YAML metadata, the entity's `latest_version` is the pinned version (not the global default). HI.3 already handles the compile-time pin resolution; UE.5 is the display-side counterpart so HA doesn't show "Update available → 2026.4.0" to a user who deliberately pinned a device to 2026.3.3.
- [ ] **UE.6 Skip-version persistence** — HA's `UpdateEntity` natively supports a "Skip" action that writes to HA's own state store (`skipped_version`). The coordinator must not clobber that when it refreshes `latest_version`. Verify the entity reports the HA-stored skipped version correctly and the "Update available" badge stays suppressed until a newer version ships. Mostly a *don't-break-what-HA-gives-you-for-free* task, plus a test.
- [ ] **UE.7 "Update all" coalescing** — when HA fires `update.install` on every `update.esphome_fleet_*` entity concurrently (the Updates card's "install all" button does this), the coordinator should batch them into a single compile run with a shared `run_id`, rather than N independent compile calls. Use Fleet's existing `POST /ui/api/compile` which already accepts a target list + returns a `run_id`. Batch window: ~2 seconds after the first incoming install call.
- [ ] **UE.8 Tests** — new `tests/test_integration_update_entities.py` covering: `release_url` format + cache behavior, `release_summary` extraction from typical ESPHome release notes markdown, `in_progress` transition on job state changes, pinned-version display, skip-version persistence, update-all batching. Extends the coverage that HI.12 already laid down for the integration scaffold.

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

## Import

- [ ] **2.1c Create device: import from URL** — fetch config from GitHub/project URL

## Config versioning refinements

- [ ] **Move archive under git tracking (from 1.6 #62).** Today `delete` renames a YAML into `.archive/` (which the fresh-init gitignore excludes) and commits the delete as a plain "file removed" entry; restore renames back and commits as a plain "file added". That's easy to reason about but drops the file's history on a delete-then-restore. Alternative: un-ignore `.archive/`, swap the raw `Path.rename` for `git mv`, and commit the archive as a move — `git log --follow` then threads the file's history across the archive/restore boundary. Cost: `.archive/` contents start showing up in the repo (YAML-only, small, but visible in `git status`). Evaluate whether history continuity is worth the extra tracked surface — decision point when the file-tree editor lands (which makes `.archive/` directly browsable anyway).

## LLM-Augmented UX

Introduce an optional LLM backend to generate content that currently falls back to hand-curated templates. First use case (from 1.6 bug #34): replace the static `"Automatically saved after editing in UI"` auto-commit subject with an LLM-generated one-line summary of the actual diff ("Tuned PWM duty cycle", "Added wifi fallback AP", etc). Opt-in — no LLM calls unless the user configures a provider + key. Candidate providers: Anthropic, OpenAI, local Ollama. Scope a dedicated release (naming TBD) when we're ready to commit to the operational cost / privacy tradeoffs.
