# ESPHome Fleet — UX / UI Review (1.5.0-dev.75)

**Reviewer perspective:** experienced UX/UI specialist. **Target audience for the product:** home-automation power users — the kind of person who tolerates (and wants) high information density, multiple simultaneous views, keyboard shortcuts, and advanced knobs, but also notices inconsistency, stale copy, and sloppy terminology faster than a casual user would.

**Methodology.** Live inspection of `http://hass-4.local:8765/` at `v1.5.0-dev.75` using Playwright: every primary tab (Devices, Queue, Workers, Schedules), every modal (Upgrade — Now + Scheduled, Editor, Secrets, Connect Worker), the bulk-action dropdowns, the per-row hamburger menu, the column picker, streamer mode, and light mode. Screenshots attached in `.playwright-mcp/ux-*.png`. Cross-referenced against `ha-addon/ui/src/` source (types, component labels, badge helpers, e2e fixtures) to ground every "I noticed this" observation in a file reference.

**How to read this document.** Findings are grouped by surface so you can read them in context. Each finding has:
- **What I saw** (live behavior),
- **Why it matters** (UX rationale),
- **Suggested fix** (or options where there's a real choice).

The last two sections are a **Terminology Audit** (all over-the-fleet inconsistencies in one place) and a **Prioritized Recommendations** table (you pick which release to slot each into).

---

## 🟢 Shipped in 1.5.0-dev.76

The first round of UI polish work landed. Findings addressed (see the `## UI Polish (from UX review)` section in `WORKITEMS-1.5.md` for implementation notes per item):

| UX_REVIEW § | WORKITEMS ID | Status |
|---|---|---|
| §2.2 — Schedules empty-state stale copy | WI **UX.1** | ✅ FIXED (1.5.0-dev.76) |
| §3.12 + §5 — column-header casing / sort indicator consistency | WI **UX.2** | ✅ FIXED (1.5.0-dev.76) |
| §4.1 — state-badge case (Queue ↔ Workers) | WI **UX.3** | ✅ FIXED (1.5.0-dev.76) |
| §4.2 — Retry button color | WI **UX.4** | ✅ FIXED (1.5.0-dev.76) |
| §4.4 — Triggered column enrichment | WI **UX.5** | ✅ FIXED (1.5.0-dev.76) — `retry_of` linkage deferred to 1.6 |
| §4.5 — Worker cell slot-suffix visual | WI **UX.6** | ✅ FIXED (1.5.0-dev.76) |
| §7.1 — Upgrade-modal `<any>` placeholder | WI **UX.7** | ✅ FIXED (1.5.0-dev.76) |
| §7.2 — Merge radio groups into one 3-option Action selector | WI **UX.8** | ✅ FIXED (1.5.0-dev.76) |
| §8.2 — Connect Worker default container name rebrand | WI **UX.9** | ✅ FIXED (1.5.0-dev.76) |
| §8.4 — Docker Compose tab in Connect Worker + retire `docker-compose.worker.yml` | WI **UX.10** | ✅ FIXED (1.5.0-dev.76) |
| §11.1 — Disabled hamburger-item tooltips | WI **UX.11** | ✅ FIXED (1.5.0-dev.76) |
| §12.2 — UI-7 invariant: icon-only buttons need `aria-label` AND `title` | WI **UX.12** | ✅ FIXED (1.5.0-dev.76) |
| §12.3 — Button padding / height audit | WI **UX.13** | ✅ FIXED (1.5.0-dev.76) — audit surfaced no mismatches post-UX.4/UX.6 |

**Important scope note on §3.3 / §14.1 (core-action vocabulary).** The **case-normalization half** shipped as WI UX.3 (all badges / states / cells are sentence case now). The **full Deploy / Build / Schedule Deploy rename** proposed in the report did NOT ship — we kept "Upgrade" as the primary action vocabulary, and the modal now uses the new single-selector action labels `Upgrade Now / Download Now / Schedule Upgrade` (WI UX.8). If the full DevOps-style rename becomes interesting later, it's a strictly additive change.

Unshipped findings still stand — see the Prioritized Recommendations section below, with done items struck through.

---

## 🔵 Pat-lens refresh (2026-04-16)

The original review was written before `dev-plans/USER_PERSONA.md` pinned down the target user. Re-reading through Pat's lens — tech-curious homeowner on HA OS, 30–100+ devices, latest-stable ESPHome, reaches the UI from their phone over Tailscale/Nabu Casa/Cloudflare, streamer mode used for GitHub screenshots, European as often as American — a few findings shift priority and a handful of gaps open up that the original review didn't call out. This section captures the deltas; the body (§1–§15) stays as-is because the observations themselves are still accurate.

### Findings that were underweighted

| Original finding | Shipped weight | Pat weight | Why the shift |
|---|---|---|---|
| §13.2 Mobile Devices-table is unusable | Medium-large | **High** | Pat reaches the UI from their phone over Tailscale / Nabu Casa for triage ("is anything offline?"). Not 5% of usage, closer to 15–25%. Mobile needs to *answer a question*, not just "degrade usefully." |
| §10.1 + §8.1 Streamer mode gaps (Secrets + Connect Worker token) | Small-medium | **High** | Streamer mode's real purpose is GitHub-issue attachments (per USER_PERSONA). Every surface a screenshot could originate from — not just the two I called out — needs a streamer-mode pass. |
| §3.9 Pinned-version indicator | Medium | **High** | Pat pins devices to bridge ESPHome version transitions — a daily-to-weekly concern for a 100-device fleet on latest-stable. Current single-icon affordance underserves the use case. |
| UE.* HA-native Updates (backlog reference, not a finding) | Medium | **High** | Pat uses HA Assist and the unified Updates card. Fleet entities in HA aren't a side quest — they're part of Pat's primary daily surface. |
| §11.1 Disabled-item tooltips (already shipped as WI UX.11) | Medium | **High priority pattern going forward** | Every "Disable, don't fail" surface should get this treatment, not just the row hamburger. Pat reads tooltips and it respects their intelligence. Keep the pattern live. |

### Findings that were overweighted

| Original finding | Original weight | Pat weight | Why the shift |
|---|---|---|---|
| §1.1 Header clutter | Medium | **Low** | Pat parses the header correctly; calling it "10 things to worry about" is more reviewer-hyperbole than user-pain. |
| §1.2 Dev-version pill semantic states | Small | **Low** | Pat knows whether they're on `develop` or stable. The pill's job is "remind me which I'm on," which it already does. |
| §5.2 "Score: 196554" legend | Small | **Low** | Pat can infer it's a benchmark; meaningless-to-newbie is not a Pat concern. |
| §8.2 Container-name rebrand for new `docker run` | Small (XS) | **Low** (shipped anyway, fine) | Pat's existing workers have the old name and won't be recreated. Only affects brand-new adds. |
| §8.3 `--label com.distributed-esphome.version=…` | Small | **Drop** | Pat runs their own tooling; doesn't need us to annotate for Portainer. |
| §3.1 Target-vs-Device distinction | Medium | **Low-medium** | Pat already knows. The value is for filtering *to* unmanaged devices when auditing, not for conceptual education. Keep the idea, drop the "teach the distinction" framing. |

### Findings the original review missed (new recommendations)

Numbered **UX.46+** to continue the existing sequence:

#### UX.46 — Locale-aware date / time / number formatting

**Effort:** M. **Pat tie-in:** European Pats are half (or more) of the audience. `02:42:50 PM` reads as "what an American time format" to a user who thinks in 24h. Dates like `2026-04-17 08:30` are safe ISO-8601; time-of-day is the pain point.

**What's wrong today.** All timestamps render in US-locale 12-hour AM/PM. Date sub-labels (e.g. `1m ago`) don't expose the underlying absolute time consistently.

**Suggested fix.** Honor `navigator.language` / `Intl.DateTimeFormat` defaults — a German browser gets `14:42:50`, an American browser gets `02:42:50 PM`. Absolute timestamps use `Intl.DateTimeFormat(undefined, { dateStyle: 'short', timeStyle: 'medium' })` — the browser produces "correct for me." Tooltips can still always show full ISO-8601 + IANA tz for engineers troubleshooting across zones. Not a new i18n framework; just use the standard one the browser already ships.

#### UX.47 — Keyboard-first table navigation

**Effort:** M. **Pat tie-in:** Pat has the UI open on a monitor and spends real time in it. Mouse-only is slow at 100 devices.

**What's missing.** No `j` / `k` row navigation. No `/` to focus the search box. No `Shift+Click` or `Shift+Space` for range-select on checkboxes. No `Enter` on a focused row to open the hamburger. No `Esc` out of deep focus back to the tab level.

**Suggested fix.** Add a small global keyboard-shortcut layer: `/` focuses the current tab's search, `j`/`k` move row selection, `Space` toggles checkbox, `Shift+Space` range-toggles, `Enter` opens primary action, `?` shows a shortcut cheat-sheet overlay. Scope this to the four list-tabs plus modals. Lucide-ified keyboard-icon hints on hover for discoverability.

#### UX.48 — Smart search across multiple fields

**Effort:** S-M. **Pat tie-in:** Search is the first thing Pat reaches for at scale. "Where's that BMS sensor?"

**What's limited today.** The `Search devices…` box matches the visible `friendly_name` / slug string. No structured search.

**Suggested fix.** Match across: friendly name, slug, IP address, area, tags, comment, network type, running version, pinned version. Prefix syntax for power users: `area:garage`, `version:2026.3.3`, `offline`, `pinned`, `tag:thread`. Also: URL-persist the query in `?q=` so Pat can bookmark "show me all offline kids-room devices." Grep-pane-like instant results. No full-text index required — in-memory client-side filter across ~100 rows is trivial.

#### UX.49 — Log modal at compile-log scale

**Effort:** M. **Pat tie-in:** Pat reads compile logs when things fail. ESPHome compile output runs 5–20k lines for a non-trivial target.

**What's painful.** No line numbers. No line-level anchor links. No search within the log. No "jump to error" button. Scrolling is the only navigation. Copying the log to a forum post doesn't preserve timestamps or highlights.

**Suggested fix.**
- Line numbers + a mini-map (even a simple one) so Pat can see where the long compile phases live.
- `Ctrl+F`-equivalent in-log search (Monaco's built-in search is free if the modal uses Monaco).
- "Jump to first error / warning" button — scan for `error:`, `warning:`, `Traceback`, `FAILED`, `E:` prefixes.
- "Copy as markdown" — wraps the relevant section in triple-backticks with the job's target + version + timestamp at the top, ready for forum/GitHub paste.
- "Download full log" for the logs too long to eyeball.

#### UX.50 — Full streamer-mode audit (all screenshot-capable surfaces)

**Effort:** M. **Pat tie-in:** Streamer mode's primary use case is **bug-report screenshots for GitHub**, not YouTube streams. Which means *any surface that could appear in a screenshot attached to a bug report* needs to honor the toggle.

**Audit candidates** (in addition to UX.9 Secrets values and UX.31 Connect Worker token):
- **Live Logs modal** — device logs stream WiFi credentials during DHCP log lines, BLE bindkeys in mac-address-printing lines, mqtt usernames in mqtt-client log output.
- **Validate output** — `esphome config <file>` prints the fully-substituted YAML on success, which means secrets substituted from `!secret` show as literals.
- **Editor diagnostics panel** — YAML parse errors can include token values.
- **Server-info panel** (if one lands) — could leak bearer tokens.
- **Device hamburger `Copy API Key`** — already gated to users who click; but if Pat accidentally clicks, the clipboard has the key. A "just-copied, hiding in 5s" animation in streamer mode is cheap.
- **Worker `Connect Worker` compose/bash emissions** — already flagged. Make sure the mobile/narrow version blurs too.

Ship as a one-time invariant-style audit: grep the source for all places values reach the DOM, and gate each through a `maskWhenStreamerMode` helper. Add new invariant **UI-8**: any `innerText` / `dangerouslySetInnerHTML` render of a value containing a `<password>` / `<key>` / `<token>` / `<mac_address>` token must route through that helper.

#### UX.51 — Narrow-viewport triage surface (phone over Tailscale)

**Effort:** L. **Pat tie-in:** Pat opens the UI on their phone to answer a single question: "is anything broken?"

**What's missing today.** The mobile fallback (UX.29 / §13.2) is a full card-layout Devices table. That's the right answer for *daily use from a phone*, but Pat's mobile use is *triage*. A 100-row paginated card list isn't the fastest path to "anything offline / anything erroring."

**Suggested fix.** Add a mobile-first **Triage view** (surfaced automatically under ~768px, with a toggle to force-show on desktop too for the "status dashboard" case):
- Big traffic-light: green "all good" / amber "3 devices offline, 1 compile failed" / red "something actively wrong."
- Below, three collapsed lists: **Offline devices** (N), **Failed recent compiles** (N), **Stale-image workers** (N). Each collapses to a summary when empty.
- Pull-to-refresh (or tap to refresh — skip gesture handling unless it's trivial).
- Single tap on any row jumps to the full desktop view's entry for that device/job/worker.

This is the mobile view that actually serves Pat; the card-layout version (UX.29) is an upgrade for when Pat needs to *act* from mobile, which is rarer.

#### UX.52 — Friendly-name vs slug display policy

**Effort:** XS. **Pat tie-in:** Pat's devices have both a YAML filename (slug like `cyd-office-info`) and a `friendly_name` from the YAML (like "Office Info Display"). Both show on every row today — friendly name bold, slug muted underneath. That's ~2× the vertical space on every row at 100-row scale.

**What's not optimal.** Once Pat has set a `friendly_name` for every device (which they have), the slug is redundant display-chrome. But it's *occasionally* useful — for git commit messages, for finding the source file in a terminal.

**Suggested fix.** Column-picker toggle: "Show device slug" (default **off** for new users; persists across reloads). When off, the row shows only `friendly_name`, reclaiming a line. Hover-tooltip still shows the slug for occasional lookup. Devices without a `friendly_name` set fall back to showing the slug prominently (so new-device onboarding still works).

### Deltas to the Prioritized Recommendations tables

Pat's lens collapses the table into two rankings rather than the current four-tier-by-effort structure. The effort tiers are still right; the priorities within them shift. Consolidated Pat-priority summary:

**Pat-critical (should land in 1.6):**
- UX.29 + **UX.51** — mobile story (triage view + card layout)
- UX.13 — bulk-action selection bar (daily ops at scale)
- UX.16 — filter-chip row on Devices
- **UX.48** — smart search
- **UX.50** — full streamer-mode audit
- UX.22 — active-compile chip on Devices rows
- **UX.46** — locale-aware date/time

**Pat-high (nice to have in 1.6, otherwise 1.7):**
- UX.14 — Workers-tab one-row-per-worker
- UX.15 — Workers platform chips
- UX.23 — Target vs Device chip (the *filter*, not the teaching)
- UX.24 / UX.25 — Schedules polish
- UX.31 — streamer-mode token masking (subsumed by UX.50)
- UX.34 — Queue ETA for pending jobs
- **UX.47** — keyboard navigation
- **UX.49** — log modal at scale

**Pat-low (ship when convenient):**
- UX.5 — `HA` / `Net` header renames
- UX.10 — tab-badge format standardization
- UX.11 — unsaved-changes marker
- UX.12 — Monaco spellcheck disable
- **UX.52** — friendly-name-only toggle
- UX.32 — column-picker grouping + saved views
- UX.43 — row-hover highlight

**De-prioritized / drop (not worth Pat's time):**
- ~~UX.41~~ — Score legend
- ~~UX.37~~ — dev-version pill semantic states
- ~~UX.19~~ — editor button split-button refactor (the current three buttons are fine; Pat uses them)
- ~~UX.26~~ — full header reorganization (too disruptive for the gain)
- ~~UX.30~~ — light-mode header parity (Pat's on dark)

(Original UX.N → UX.45 rankings in §16 still stand for anyone who wants the effort-tiered view; this section is the Pat-weighted overlay.)

---

## 1. Global header

### 1.1 The header is dense with actions of wildly different frequency

Left to right today: `[ESPHome] [Fleet]` brand, `v1.5.0-dev.75` version pill, `ESPHome 2026.4.0 ▼` version dropdown, circular-refresh icon, `Secrets`, theme toggle, streamer-mode toggle, `ESPHome Web ↗`, server-online dot.

**What I saw.** Nine controls in the header; all compete for attention with the ESPHome Fleet brand.

**Why it matters.** Mixed frequency = clutter. The version pill (`v1.5.0-dev.75`) is *extremely* useful to the maintainer diagnosing a hass-4 bug, less so to an end user who sees "dev.75" and wonders what's unstable. `ESPHome Web ↗` is a once-a-year action (serial-flash a bricked device) currently given equal weight to `Secrets`, which is weekly. The server-online green dot has no label, no tooltip, and no affordance ("how do I know it's *my* server?"). Power users can parse all of this; new users read it as "10 things to worry about at the top of my screen."

**Suggested fix.**
- Group the header into three regions with tighter visual grouping: `[brand + version]` (left), `[Secrets | ESPHome Version dropdown | Refresh]` (center, primary actions), `[Theme | Streamer | ESPHome Web | Status]` (right, utilities).
- Add a `title` tooltip to the green server-dot: "Fleet server online — v1.5.0-dev.75 — last check 2s ago". Same for the Fleet/ESPHome Web separation.
- Consider demoting the dev-version pill to a tooltip on the brand ("ESPHome Fleet — v1.5.0-dev.75"). On a stable release build it could disappear entirely.
- Move `ESPHome Web ↗` to a "…" overflow menu at the right edge with other rarely-used utilities (eventually: "Changelog", "Debug logs", "Keyboard shortcuts", "Docs").

### 1.2 The dev-version pill has no semantic state

**What I saw.** `v1.5.0-dev.75` is always rendered identically regardless of whether this is a stable tag, a dev build, a pre-release, or something else.

**Why it matters.** Power users running `-dev.N` builds do want to know. But they also want to know when they're out of date.

**Suggested fix.** Two states:
- Stable (no `-dev`): muted gray pill, `v1.5.0`.
- Dev: accent pill + optional "⚠ dev build" tooltip.
- Add an `Update available` badge (amber) when the server knows a newer tag is on PyPI/GHCR. Re-uses the PyPI refresher we already have.

### 1.3 ESPHome version dropdown is great but its state is ambiguous

**What I saw.** `ESPHome 2026.4.0 ▼` opens a dropdown of all released versions plus a `Show betas` toggle. Refresh icon next to it triggers an immediate PyPI re-fetch.

**Why it matters.** Power-user feature, works well. But the relationship between *selected* version (the global default the server installs / suggests) and *pinned* versions on specific devices (overrides) isn't visible from here. And there's no indication when the list was last refreshed.

**Suggested fix.**
- Add last-refreshed time to the dropdown header ("PyPI list • refreshed 12 min ago").
- When any devices are pinned to a different version, show a small count badge beside the dropdown: "ESPHome 2026.4.0 ▼ [3 pinned]". Clicking jumps to a filtered Devices view.
- The dropdown's "Current (2026.4.0)" header row and the actual `2026.4.0` row below it are visually redundant — consider showing "Current" only as a chip on the real version row.

---

## 2. Tab bar

### 2.1 Tab badges use four different formats

| Tab | Badge seen during review |
|---|---|
| Devices | `65/67` (online/total) |
| Queue | `0`, then `1 active`, then `3 done` |
| Workers | `7/7`, then `4/4`, then `6/6` |
| Schedules | `0` |

**What I saw.** Ratios on two tabs (`65/67`, `7/7`), a prose-count on Queue (`1 active` / `3 done`), a bare number on Schedules (`0`).

**Why it matters.** The user's eye scans the top nav to answer "is anything wrong / active?" Four different formats means four different mental parses. "0" on Schedules could be "no schedules configured" or "no schedules fired recently" — ambiguous.

**Suggested fix.** Standardize on a single convention:
- **Ratio** (`online/total`) for stateful lists where offline is a real state: Devices, Workers.
- **Count of attention-worthy items** for activity lists: Queue shows only non-terminal count ("1 active", hide when 0), Schedules shows "N scheduled" or blank.
- Never mix "1 active" / "3 done" on the same tab label — the label mutates with unrelated state. Pick *active* as the badge, move "done" to the tab's own toolbar.

### 2.2 Schedules tab's empty state points to a menu item that no longer exists

**Status:** ✅ FIXED (1.5.0-dev.76) — WI UX.1. Copy rewritten to: *"No devices have a schedule configured — click **Upgrade** on a device, then choose **Scheduled**."*

**What I saw.**
```
"No devices have a schedule configured — open a device's menu and choose 'Schedule Upgrade...'"
```
`ha-addon/ui/src/components/SchedulesTab.tsx:319`

But the device context menu (`DeviceContextMenu.tsx:122`) explicitly says:
> `// #93: "Schedule Upgrade…" removed — accessible via the Upgrade [modal]`

**Why it matters.** The empty-state copy is stale. A user following the instruction will hunt for a menu item that was deliberately removed. This is a real bug, not a nit.

**Suggested fix.** Rewrite:
> "No devices have a schedule configured — click **Upgrade** on a device, then choose **Scheduled**."

Even better: make the link actionable — include a button in the empty state that opens the Upgrade modal for the first device with "Scheduled" pre-selected.

---

## 3. Devices tab

### 3.1 "Devices" tab conflates two concepts the types layer carefully separates

**What I saw.** Per `types/index.ts:38` and `types/index.ts:127`:
> *"Distinct from `Target` above: a Target is a YAML config we manage; a Device is something physically out there. `compile_target` links the two when we can match a discovered device to one of our YAMLs. Unmanaged devices (real ESPHome hardware with no local YAML) have `compile_target: null`."*

In the UI, the tab is labeled "Devices" and holds both. A toggle in the column picker called "Show unmanaged devices" controls whether the tab-less "unmanaged" rows appear.

**Why it matters.** The conceptual split is *exactly* the power-user's mental model — "YAMLs I own vs. hardware on my network." Hiding it reads as simplification but costs clarity. Terms drift: "managed device" vs "target" vs "YAML" vs "device" all refer to the same thing depending on context.

**Suggested fix.** Pick one term and stick. Options:
- **(Recommended)** Keep "Devices" as the tab label, but render a small glyph/chip beside each row: `YAML` chip for managed targets, `Discovered` chip for unmanaged. Sort/filter by it. Users who want either exclusive view can use a column filter.
- Or, split into two tabs: "Managed" + "Discovered". Clearer at the cost of a UI click.

Whichever wins, cross-pollinate the term into every label, tooltip, empty state, and action name. Pick a term and grep the codebase.

### 3.2 Three controls per row is one too many

**What I saw.** Every row ends with `[Upgrade] [Edit] [⋮]`. 67 rows × three buttons = 201 clickable elements visible on load.

**Why it matters.** Dense tables are fine; power users want density. But three-up-front+hamburger is the common anti-pattern — it means the hamburger is mostly tertiary (Delete, Rename, Duplicate) while the frequent actions (Upgrade, Edit) got promoted out. The problem: the hamburger *also* contains Live Logs, which is probably more-frequent than Edit for many users.

**Suggested fix.** Audit by frequency. Live Logs + Upgrade are clearly the top two; Edit, Restart, Rename, Duplicate, Delete, Pin/Unpin all follow. Several workable patterns:

- **Two buttons + hamburger, frequency-aware:** `[Upgrade] [Logs] [⋮]` — promote Live Logs, demote Edit into the hamburger. Edit is rarer for established fleets than logs.
- **One primary button + hover-reveal row actions:** only `[Upgrade] [⋮]` when not hovered, everything else reveals on row hover. Less clutter on idle, still fast on hover. A common pattern in HA itself.
- **Bulk-select driven:** if you select multiple rows, a contextual action bar slides in at the bottom with all batch actions. Per-row buttons can shrink to just hamburger.

The right answer needs a real usage audit (telemetry), but anything is better than three buttons-plus-hamburger on every row.

### 3.3 The "Upgrade" action is named for a case that isn't always true

**What I saw.** The row-level `[Upgrade]` button opens a modal titled "Upgrade — <device>". The modal has a **Compile + OTA** / **Compile + Download** radio pair. If the user picks "Compile + Download (no OTA)", the confirm-button text updates to "Compile & Download" — but the modal title remains "Upgrade — <device>". Also, nothing in the word "Upgrade" means "re-compile unchanged YAML", which is one of the most common reasons for running it.

**Why it matters.**
1. **Title drift**: the *action* changed but the *title* didn't.
2. **Misleading vocabulary**: "Upgrade" implies a version bump. Running `compile + OTA` without a version change is really "re-flash" or "deploy" or "push firmware." Users think "I don't need to upgrade anything, just re-flash" and hesitate.
3. **Inconsistency**: the Queue-tab state badge for the same operation says `COMPILING + OTA` (also mixed case elsewhere: `Compiling + OTA`). Three different words for the same lifecycle phase.

**Suggested fix.** Rename the action primitive to something unambiguous. Candidates:
- **`Deploy`** — clearest, matches DevOps vocabulary. The modal then has `Deploy` vs `Compile only (no flash)`. The *Schedule* variant is "Scheduled Deploy". Everything aligns.
- **`Flash`** — strong ESPHome community term. Action: `Flash`, with sub-options `Compile + flash` (default), `Compile only (download binary)`.
- **`Build`** — fine, but conflates compile step vs OTA step.

Whatever you pick, update the modal title dynamically: `{Deploy|Schedule Deploy|Compile & Download} — <device>`. And resolve "Compiling + OTA" vs "COMPILING + OTA" across badges.

### 3.4 Bulk-action surface is split across two dropdowns and neither mentions selection count

**What I saw.**
- `[Upgrade ▼]` button opens: *Upgrade All*, *Upgrade All Online*, *Upgrade Outdated* (disabled), *Upgrade Selected*.
- `[Actions ▼]` button opens: *Schedule Selected...*, *Remove Schedule from Selected*.

**Why it matters.**
- "Upgrade Outdated" is disabled — but no tooltip explains *why*. Power users lose a minute debugging whether they're doing it wrong. (Actual reason: no devices currently match the "needs_update" heuristic. State it.)
- "Upgrade Selected" lives under `Upgrade` while "Schedule Selected" lives under `Actions`. These are two parts of the same story (bulk operations on checked rows). They shouldn't be in separate dropdowns.
- Neither button reflects the current selection count. If you check 5 rows, the button still reads `[Actions ▼]`, not `[Actions (5)]`.

**Suggested fix.**
- Merge into a single **`Bulk Actions ▼`** dropdown when nothing is selected, or collapse both dropdowns and replace with a **sticky selection bar** when anything is selected: `"5 selected [Upgrade] [Schedule] [Validate] [Tag] [Delete] [×]"` docked at the top or bottom of the table. The pattern GitHub, Linear, and Notion all use. Clarifies "this acts on the 5 things I have checked."
- For non-selection bulk ("Upgrade All Online"), a small `[More ▼]` chip on the toolbar suffices.
- Add tooltip to any disabled bulk option: *"No devices are behind the selected ESPHome version."*

### 3.5 Column picker exposes 11 column options but no grouping and no "save view"

**What I saw.** Checkboxes: Status, HA, IP, Net, Version, IP Config, AP, Schedule, Area, Comment, Project, + "Show unmanaged devices" switch. Defaults: 5 data columns + Schedule, Version visible; 4 more available.

**Why it matters.** Good that it exists. Missing:
- No section headers. At 11 items, "Status / Connectivity / Metadata" grouping would help.
- No way to save or share a view ("My audit view"). Power users will want this.
- The toggle `Show unmanaged devices` lives alongside columns — it's not a column, it's a row filter. Inconsistent.

**Suggested fix.**
- Group: *Connectivity* (Status, HA, IP, Net, IP Config, AP), *Firmware* (Version, Schedule), *Metadata* (Area, Comment, Project).
- Move `Show unmanaged` to its own filter chip in the toolbar (or as a segmented control: `[Managed] [Discovered] [All]`).
- Eventually add saved column sets ("Audit view", "Compile state", "Thread/Matter only").

### 3.6 Column headers `HA`, `Net` are too terse for non-regulars

**What I saw.** Short headers are fine for power users but `HA` and `Net` are too short even for them.

**Why it matters.** `HA` is ambiguous (Home Assistant / High Availability). `Net` is ambiguous (Network type? Netmask? Internet reachability?). Once you know, you know — but there's no reason to force "once you know."

**Suggested fix.** `In HA` / `Network` (or `Net type`). Keeps width acceptable. Same in the column picker.

### 3.7 HA column value: `Yes [↗]` is an odd composite

**What I saw.** The HA column renders `Yes` plus a small external-link icon. Clicking the icon opens the device in Home Assistant.

**Why it matters.** The word "Yes" with a link icon reads as "yes, with an afterthought." The click target is actually just the link. The cell would be tighter as either:
- Just the icon with tooltip "Open in Home Assistant" (most cells), and a muted `—` for devices that aren't mapped.
- Or a pill: `In HA [↗]` consistent across online/linked states.

For devices where HA status is "unknown" (`—`), a tooltip should explain *why* (mDNS miss, HA API down, not yet polled).

### 3.8 IP column mixes plain IPs with address-source annotations inconsistently

**What I saw.** Most rows show `192.168.227.120` + `via mDNS` as a tiny muted sub-line. A few rows show `192.168.227.152` + `wifi.use_address`. A few show just the IP. "matter-test" shows `matter-test.local` (hostname, no IP).

**Why it matters.** The sub-line is great power-user info ("how did we get this IP?"). But the value set is leaked straight from `Device.address_source` — `'mdns'`, `'mdns_default'`, `'wifi_use_address'`, `'ethernet_use_address'`, `'openthread_use_address'`, `'wifi_static_ip'`, `'ethernet_static_ip'` (per `types/index.ts:23`). Some show as prose ("via mDNS"), some as literal values ("wifi.use_address"). Users end up seeing three "languages" in one column.

**Suggested fix.** Normalize to prose for all cases:
- `via mDNS`, `WiFi static IP`, `Ethernet static IP`, `WiFi fixed address`, `Ethernet fixed address`, `OpenThread fixed address`, `mDNS (default)`.
- Hover tooltip shows the raw source value for debugging.
- For unresolved hostnames (`matter-test.local`), show hostname in the main line with "not resolved" sub-line.

### 3.9 Pinned-version indicator is a single tiny icon

**What I saw.** `cyd-office-info` row shows `2026.4.0 [pin-icon]` in the Version column. The icon is ambiguous — is the version pinned *to* this value, or is it a "please pin this" button?

**Why it matters.** Pinning is a power-user feature but the UI should make state obvious at a glance.

**Suggested fix.**
- Show pinned version as a distinct chip: `2026.4.0 [📌 pinned]` where the chip has a tooltip "Pinned to 2026.4.0 — Fleet will not auto-upgrade." Same chip style as the `BUILT-IN` pill on workers.
- When pinned version differs from the globally-selected version, render it in a warning/caution color and add "Global default: 2026.4.1 (pinned here)".

### 3.10 `nanoc6-1` row has `HA: —` (neither Yes nor No)

**What I saw.** Most rows show `Yes` in the HA column, Matter Test is offline and shows `—`. But `nanoc6-1` (Family Room Ceiling Fan) is online and shows `—` too. No explanation visible.

**Why it matters.** "—" reads as "null/unknown" but there's no indication *why* this one is unknown. Is it excluded from HA? Is it a fresh device not yet polled? Silent ambiguity.

**Suggested fix.** Tooltip: `No 'api:' block in YAML` / `Offline — HA status last confirmed <time>` / `Device not yet polled`.

### 3.11 No visible filter-chip row

**What I saw.** Search input exists. But filters today are: toggle-columns + show-unmanaged + search-text. No "online only", "needs update", "no pinned version", "in area X".

**Why it matters.** At 67 devices this is already painful. At 200+ devices (larger installs the product could support) it becomes unusable.

**Suggested fix.** A filter-chip row between the toolbar and the table. Chips: `Online`, `Offline`, `Needs update`, `Has schedule`, `Pinned`, `Unmanaged`, `Area: <dropdown>`, `Network: wifi|eth|thread`. Each chip toggles on click, AND-together. Persist in `?filters=...` URL param so users can bookmark views.

### 3.12 Sort indicator inconsistency

**Status:** ✅ FIXED (1.5.0-dev.76) — WI UX.2. Global `th { text-transform: uppercase }` dropped; Workers-tab sortable columns migrated to the shared `SortHeader` so they now match Devices/Queue/Schedules' sort-glyph style.

**What I saw.** Hostname column header on Workers tab shows a sort-up triangle (`▲`). Other sortable columns on Devices tab don't show a visible indicator unless sorted.

**Why it matters.** Users have to discover which columns sort by clicking.

**Suggested fix.** Show a faded indicator on every sortable header; highlight + direction on the active sort column. Already shipped via `SortHeader` component (QS.21) — confirm it's used uniformly and the faded state is actually rendered.

---

## 4. Queue tab

### 4.1 State badge case inconsistency: `COMPILING + OTA` vs `Compiling + OTA`

**Status:** ✅ FIXED (1.5.0-dev.76) — WI UX.3. Dropped the `uppercase` utility from `BADGE_BASE` in `utils/jobState.ts`; Workers-tab Current Job cell switched to the same `getJobBadge` component as Queue. Badges render identically everywhere.

**What I saw.**
- Queue-tab State cell: `COMPILING + OTA` (all caps, outlined, purple).
- Workers-tab Current Job cell: `Compiling + OTA` (title case, not a badge).

**Why it matters.** Same state, two typographies. Power users notice.

**Suggested fix.** Pick one case for state labels and apply everywhere. `Compiling + OTA` (sentence case) reads better; ALL CAPS is aggressive for a standard state. Keep the badge styling (colored pill) in the Queue tab since it's the primary state-exposure surface; the Workers-tab cell can reuse the same badge component.

### 4.2 Retry button is orange (warning color)

**Status:** ✅ FIXED (1.5.0-dev.76) — WI UX.4. `Retry ▼` trigger now uses the success green (`bg-[#14532d] text-[#4ade80]`) matching the per-row Rerun button. Orange/amber reserved for genuine warnings.

**What I saw.** The `Retry ▼` dropdown trigger is a warning orange, visually weighted equal to or above the neutral `Clear ▼` to its right.

**Why it matters.** Retry isn't a warning action — it's reruns-last-failed. Orange in this UI otherwise signals "caution" (image-stale, destructive, attention). Using it for a neutral action drains meaning from orange elsewhere.

**Suggested fix.** Retry should be primary/accent or neutral; use orange/amber only for warnings (image stale, version behind global default, schedule paused). `[Retry ▼]` in the same neutral outline as `[Clear ▼]` is fine.

### 4.3 Clear dropdown labels are semantically adjacent but visually similar

**What I saw.** `Clear ▼` → `Clear Succeeded`, `Clear All Finished`, `Clear Entire Queue`.

**Why it matters.** "Succeeded" vs "All Finished" — a user has to think: "is Finished = Succeeded + Failed + Cancelled?" The label alone doesn't tell them. "Clear Entire Queue" is highlighted and sounds destructive.

**Suggested fix.**
- More explicit labels: `Clear succeeded (N)`, `Clear all finished — success + failure + cancelled (N)`, `Clear everything (N)`.
- Show the row count inline so users can judge before clicking.
- Consider promoting "Clear succeeded" to a direct button (the common case) and keeping the "…" for the rarer bulk operations.
- Confirm dialog on "Clear everything" (verify this exists).

### 4.4 Triggered column is too terse to be useful

**Status:** ✅ FIXED (1.5.0-dev.76) — WI UX.5. Relabeled `User` → `Manual` (HA-user attribution follows with AU.*). Recurring rows: `Recurring · Daily 03:00` with tooltip of the raw cron + tz. One-time rows: `Once @ <timestamp>` with full ISO in tooltip. `🔄 Retry of #<id>` deferred to 1.6 (no `retry_of` field on the wire contract yet).

**What I saw.** `👤 User` with a person icon.

**Why it matters.** "User" is almost never useful information on its own. Which user? When was it scheduled (if it was)? For power users, audit trail matters.

**Suggested fix.** Surface more:
- `👤 Manual` (when a human clicked Upgrade)
- `👤 stefan` (after AU.* auth ships — show the HA user's name)
- `📅 Recurring @ 03:00` (from a cron schedule)
- `📅 Once at 2026-04-17 08:30` (from a one-time schedule)
- `🔄 Retry of #abc123` (when retried)

Each with a tooltip showing full context and a hover-to-highlight on the parent schedule / original job.

### 4.5 Worker cell's slot suffix `/2` is ambiguous

**Status:** ✅ FIXED (1.5.0-dev.76) — WI UX.6. Queue + Workers tabs now render the slot on a muted second line (`AI-MacBook-Pro.local` / `slot 2`) with a tooltip *"Build slot 2 of 2 on this worker."* Single-slot workers render just the hostname.

**What I saw.** Worker column shows `AI-MacBook-Pro.local/2`. No explanation that `/2` is "slot 2 of this worker's concurrent build slots."

**Why it matters.** Users new to the concurrency model think `/2` is a version number, a retry count, an index, etc.

**Suggested fix.** Visual separation: `AI-MacBook-Pro.local · slot 2` or `AI-MacBook-Pro.local` (hostname) + a small muted `slot 2` beneath. Tooltip: "Build slot 2 of 2 on this worker."

### 4.6 Start/Finish times format drifts

**What I saw.** Start Time: `02:42:50 PM` + `1m ago`. Finish Time: italic `Elapsed 1m 3s`. Two different format systems in two adjacent columns.

**Why it matters.** Power users want absolute timestamps for logs/correlation; casual users want relative. Do both consistently.

**Suggested fix.** `<timestamp>` + `<relative>` stacked, consistently in each time column. For "still in progress", Finish column shows `— still running (1m 3s elapsed)`. No italics — it reads as "tentative" and structured data shouldn't be italicized. Tooltip gives ISO-8601 + local timezone.

### 4.7 No indication of worker load / queue depth ahead of a pending job

**What I saw.** A PENDING job shows "Pending" with no ETA. A WORKING job shows the worker name + elapsed. No "5 jobs ahead in queue" for pending.

**Why it matters.** If you kick off 10 compiles at once, you want to know where in line each one is.

**Suggested fix.** For PENDING rows, show `Position: 3 of 8 in queue` and an ETA estimate (`~2m 30s until start`) based on recent average compile time. Low-priority, fills a real gap.

---

## 5. Workers tab

### 5.1 Secondary "slot rows" are visually broken

**What I saw.** Each worker with N slots renders as N rows: slot 1 has the full platform / status / version / slots / cache data, slots 2..N show just `<hostname>/N  Idle` — a nearly-empty row with no platform badge, no status dot, no uptime, no version.

**Why it matters.** On first look it reads as "a second worker that didn't register properly." Row-level visual scanning gets confused. The slot split is an implementation detail (each slot is a worker connection), not something the user thinks about that way.

**Suggested fix.**
- **(Recommended)** One row per worker. Show slot state as a progress indicator inside the row: `● ● ○` (2 of 3 slots busy) or `[busy: cyd-office-info] [idle] [idle]`. The `[- N +]` count control stays the same.
- Or, keep N rows per worker but make the visual relationship explicit: indent the slot 2..N rows, bracket them with a left rail, and label them `↳ slot 2`, `↳ slot 3`.

### 5.2 "Score: 196554" has no legend

**What I saw.** Platform cell shows `Score: 196554 · CPU: 5.6%`. No explanation of what Score is.

**Why it matters.** It's a custom benchmark number — meaningless without context.

**Suggested fix.** Tooltip or legend: "CPU benchmark — higher is faster. 100k is baseline Pi 4; 300k+ is a modern desktop." Or drop the number and show a descriptive chip: `Fast` / `Medium` / `Slow` derived from the score.

### 5.3 Platform cell is a wall of prose

**What I saw.** 4-5 lines of free text: OS / CPU / arch / score / disk. Small font, similar weight for all lines, no structure.

**Why it matters.** High information density is good — unparseable density is not. Scanning "which worker has the most free disk?" across 7 rows means reading 5 lines × 7 rows of prose.

**Suggested fix.** Inline chips instead of prose:
```
[Debian 13]  [12×i5-12500T]  [31 GB RAM]  [Disk 80% free]  [Score 196k]
```
One row, same pixels, scannable. Each chip has a tooltip with full detail.

### 5.4 Uptime format inconsistency

**What I saw.** `up 53s`, `up 21s`, `up 2s`. Good short form. But elsewhere in the app, relative times are `1m ago` / `43s ago` / `Elapsed 1m 27s`. Three different phrasings for relative time.

**Why it matters.** Minor but visible to power users.

**Suggested fix.** Pick one: "online for 53s" or "up 53s" or "connected 53s ago". Use across all three places.

### 5.5 "Clean Cache" button is conspicuous; Remove/Pause are missing

**What I saw.** Every worker row has a `Clean Cache` button. No `Remove worker`, no `Pause worker`, no `Rename` action visible on the Workers tab.

**Why it matters.** Clean Cache is a maintenance operation — rarely used. Remove is often needed after a worker host is retired. Pause is valuable when a worker is acting up and you want to idle it without terminating it.

**Suggested fix.** Per-worker hamburger menu: `Clean cache`, `Pause / Resume` (or wire the `[- 0 +]` slot control), `Remove`, `View logs` (placeholder for future), `Rename` (once durable identity ships in WC.1). Demote `Clean Cache` into that menu.

### 5.6 Slot counter doesn't communicate state clearly

**What I saw.** `[- 2 +]` where the number is the max parallel jobs. No indication of how many slots are currently busy, no visual difference when the worker is at capacity.

**Why it matters.** You set slots to 3 on the big worker and 1 on the Pi. You want a glance to tell you "is the Pi maxed out?"

**Suggested fix.** Show busy/total: `[- 1/3 +]` (cursor on the number, `+`/`−` still adjust max). Or a separate visual indicator (bar or dots) showing `2/3 busy`.

### 5.7 "BUILT-IN" pill on local-worker is a nice touch — extend the pattern

**What I saw.** `local-worker` row has a `BUILT-IN` pill, differentiating it from connected workers.

**Why it matters.** Positive — this works. But once workers get names + tags (WC.*), we'll want many more of these kinds of chips.

**Suggested fix.** Make the pill a formal pattern: `BUILT-IN`, `REMOTE`, `TAGS: ipv6, beefy`, `PAUSED`, `STALE IMAGE`. Workers-tab would gain a Tags column that renders them consistently.

### 5.8 No worker-image-version indicator visible on my live view

**What I saw.** Version column shows `1.5.0-dev.75`. Per `ImageStaleBadge` in `WorkersTab.tsx:125-161`, a red "image stale" badge should appear when workers are behind `MIN_IMAGE_VERSION`. None visible in my review — all workers happen to be current.

**Why it matters.** The badge is good; the mitigation it points at is a gap (addressed by the WU.* plan in `WORKITEMS-1.6.md`). When stale, users should see the literal `docker pull && docker restart <name>` in the tooltip (per that plan).

**Suggested fix.** Confirmed in WU.2 (queued). Also add a build date below the version once IMAGE_BUILD_DATE ships: `1.5.0-dev.75` / `built 2026-04-16`.

---

## 6. Schedules tab

### 6.1 Empty state links to nonexistent menu item (see §2.2)

Already covered — most impactful finding in the review.

### 6.2 Columns are reasonable but lack schedule-specific context

**What I saw.** Device, Schedule, Status, Last Run, Version.

**Why it matters.** Good basics. Missing:
- **Next Run** — probably the most important schedule column. When does it next fire? (Even if it's recurring, knowing "next run: tomorrow 03:00 PDT" is valuable.)
- **Kind** — Recurring vs One-time. Today this is inferred from the Schedule string. Make it a chip.
- **Enabled/Paused** — schedules can be disabled. Show with a pause glyph and an inline toggle.

**Suggested fix.** Add `Next Run` column (default visible). Add `Kind` chip inside the Schedule column. Move `Status` to be a chip with states `Active`, `Paused`, `One-time`.

### 6.3 No bulk pause

**What I saw.** `Actions ▼` dropdown on the toolbar. I didn't see its contents populated in the empty state. Per WORKITEMS there are patterns for `Schedule Selected` / `Remove Schedule from Selected`. A `Pause Selected` / `Resume Selected` isn't visible.

**Why it matters.** Pausing all schedules for a weekend outage is a normal home-lab need.

**Suggested fix.** Add `Pause / Resume` as bulk actions, gated on multi-select. Also a global `Pause All Schedules` toggle in the toolbar, useful for maintenance windows.

---

## 7. Upgrade modal

### 7.1 "Worker" default `<any> — let the scheduler pick` is coder-y

**Status:** ✅ FIXED (1.5.0-dev.76) — WI UX.7. Now reads `Any available worker (auto)` with hover tooltip *"Fleet will pick the fastest available worker at compile time."*

**What I saw.** The Worker select defaults to `<any> — let the scheduler pick` (angle brackets).

**Why it matters.** `<any>` is literal placeholder syntax from code samples; it leaks into the UI. Power users tolerate it, but the label "let the scheduler pick" could just be the state.

**Suggested fix.** `Any available worker (auto)` with a tooltip "Fleet will pick the fastest available worker at compile time." Remove angle brackets.

### 7.2 Two radio groups with related options feels like a wizard

**Status:** ✅ FIXED (1.5.0-dev.76) — WI UX.8. Collapsed into one 3-option Action selector: `Upgrade Now` (default) / `Download Now` / `Schedule Upgrade`. Single `action` state variable; modal title + confirm-button label mirror the selected verb. E2E specs rewritten to match.

**What I saw.** Group 1: `Now | Scheduled`. Group 2: `Compile + OTA | Compile + Download (no OTA)`. Group 2 only shows when group 1 = Now.

**Why it matters.** Two groups conceal that you're really picking one of three actions:
1. Compile and flash now.
2. Compile and download now.
3. Compile and flash on schedule.

**Suggested fix.** Merge into one segmented control with three options, or a single Select:
- `Deploy now`
- `Download only (no flash)`
- `Schedule deploy...`

Picking "Schedule deploy..." expands the schedule sub-form inline. Fewer nested branches, one clear chain of thought.

### 7.3 Version picker: `Current (2026.4.0)` row duplicates the real version row

**What I saw.** Dropdown shows `Current (2026.4.0)` as a label-row, then `2026.4.0` (highlighted) below, then earlier versions. Two visual representations of the same thing.

**Why it matters.** Redundant, slightly confusing ("which one do I click?").

**Suggested fix.** Show "Current" as a chip on the version row itself: `2026.4.0 [Current]`. Drop the header row.

### 7.4 Inline cron preview is great for power users

**What I saw.** `Cron: 0 2 * * * (America/Los_Angeles)` rendered live below the schedule controls.

**Why it matters.** This is the kind of power-user polish that differentiates the product. Tiny but high-value.

**Suggested fix.** Keep this. When a user clicks "Advanced (cron)" (haven't traced the exact flow), let them hand-edit the expression AND give them a human preview ("Every day at 02:00 America/Los_Angeles") alongside. Reuse `formatCronHuman` from `utils/cron.ts`.

### 7.5 No "remove existing schedule" shortcut inside the modal

**What I saw.** In Scheduled mode for a device that already has a schedule: title "Schedule Upgrade — <device>", Save Schedule button, Cancel. If user wants to *remove* the schedule, they have to navigate to Schedules tab.

**Why it matters.** Friction for a common operation. Per `PT.2` spec, a "Remove existing schedule" button was planned. Didn't see it in this review.

**Suggested fix.** When editing an existing schedule, show a tertiary `Remove schedule` button in the modal footer. (PT.2 suggests this already exists for devices with an active schedule — confirm and surface broadly.)

---

## 8. Connect Worker modal

### 8.1 Server token is shown in plaintext and streamer mode doesn't blur it

**What I saw.** A shared Bearer token is displayed readably in the `SERVER TOKEN` field. Opening the modal with streamer mode ON: token still visible.

**Why it matters.** Streamer mode is for screencasts/screenshares. Its purpose is defeated if opening the onboarding flow leaks the auth token.

**Suggested fix.**
- Blur the `SERVER TOKEN` field value when streamer mode is on. A small "reveal" eye button toggles it.
- Also blur the token inside the generated `docker run` command block when streamer mode is on. Use `<TOKEN>` placeholder instead.
- `[Copy]` still works and copies the real value to clipboard. Users can copy without visually exposing.

### 8.2 Container-name default uses the pre-rebrand name

**Status:** ✅ FIXED (1.5.0-dev.76) — WI UX.9. Default `containerName` now `esphome-fleet-worker`. Existing containers unaffected; only newly-copied `docker run` / compose snippets use the new name.

**What I saw.** Default `CONTAINER NAME: distributed-esphome-worker`.

**Why it matters.** Per the rebrand rules (`CLAUDE.md`), code identifiers stay `distributed_esphome` but user-facing strings are `ESPHome Fleet`. The container name is a user-facing identifier: shows up in `docker ps`, container logs, dashboards, health checks. It's the piece of code-generated config the user sees most.

**Suggested fix.** Change default to `esphome-fleet-worker`. Existing containers with old names keep running unchanged; this only affects newly-copied `docker run` commands. Same change to the `docker-compose.yml` example (`WU.*` plan, now deferred to DOCS but the name should match).

### 8.3 The full `docker run` command has no `--label` provision for auto-update

**What I saw.** Generated command: `-e VARS`, `-v volumes`, `image:tag`. No labels.

**Why it matters.** The user decided against Watchtower/wud auto-update (see `WORKITEMS-1.6.md` WU.1–3). Fine. But a generic `--label com.distributed-esphome.version=X` would help the user's own tooling (Portainer, Dockge, etc) recognize Fleet workers. Low-cost addition.

**Suggested fix.** Add `--label com.github.weirded.distributed-esphome.version=<image-tag>` (or similar) so any user-side tool can identify Fleet-managed containers. Opt-out if you decide it's pointless — this is a nice-to-have.

### 8.4 No Docker Compose variant

**Status:** ✅ FIXED (1.5.0-dev.76) — WI UX.10. Connect Worker modal now has three format buttons (`Bash | PowerShell | Docker Compose`). Compose branch emits a live-from-server `docker-compose.yml` snippet. Retired static `docker-compose.worker.yml` from repo root.

**What I saw.** Only `docker run -d ... ` one-liner, toggled between Bash and PowerShell.

**Why it matters.** A meaningful fraction of home-lab users use Compose exclusively. They copy your `docker run` and have to hand-translate.

**Suggested fix.** Add a third tab alongside `Bash | PowerShell`: `Docker Compose`. Emits a `docker-compose.yml` snippet with the same envs/volumes/restart policy. Copy button works the same way.

### 8.5 Subtle helpful touches that work well

- The "Run this command on any Docker host that has network access to your ESP devices (port 3232 for OTA)" footer is exactly right for the target audience.
- The `$(hostname)` default for HOSTNAME is clever — the command resolves at docker-run time.
- The Restart Policy dropdown is a nice hedge against the inevitable "why did my worker die and not come back" support question.

---

## 9. Editor modal

### 9.1 Button colors assign weight inversely to expected frequency

**What I saw.** Top bar: `[Save]` (primary, purple) / `[Save & Upgrade]` (green) / `[Validate]` (neutral).

**Why it matters.**
1. Green is usually reserved for "complete a primary happy-path action." `Save & Upgrade` is a compound action, not the primary editor action — `Save` is.
2. `Save` is primary purple, which visually means "do this first." But if you hit `Save & Upgrade`, you arguably *also* save — which is more aligned with "press this and move on."
3. Three buttons with three colors and one subtle dismiss (the `×`) means four competing visual weights in the top bar.

**Suggested fix.** One primary, two secondary:
- `[Save]` primary (purple).
- `[Validate]` secondary (neutral outline).
- `[Save & Upgrade ▼]` — a *split button*: primary action `Save & Upgrade`, dropdown contains `Save & Deploy (download only)`, `Save & Validate`, `Save & Deploy later...`. This reduces the default count and makes the compound actions discoverable without making them equal in weight.
- Or keep three flat buttons but all same weight/neutral; `[×]` close gets a confirm on unsaved changes.

### 9.2 No keyboard shortcuts displayed

**What I saw.** No hints for Cmd/Ctrl+S, Cmd/Ctrl+Shift+V, Cmd/Ctrl+Shift+S.

**Why it matters.** Power users live in the editor. Every good editor's toolbar shows the keyboard shortcut in the tooltip.

**Suggested fix.** Add tooltips with keybindings. Enable the shortcuts themselves (Cmd+S saves). A `?` help overlay listing shortcuts is a cheap win.

### 9.3 No unsaved-changes indicator

**What I saw.** Header shows `cyd-office-info.yaml` — no `●` marker for unsaved changes, no "modified" chip.

**Why it matters.** Essential editor feedback. Close the modal by accident → lose work.

**Suggested fix.** Show `cyd-office-info.yaml ●` when unsaved. Close button prompts: "Discard unsaved changes?" with options (Cancel, Discard, Save).

### 9.4 No diff preview before Save

**What I saw.** You edit, click Save, done. No "here's what's changing" before commit.

**Why it matters.** Power users want to *see* diffs before pressing Save on production config. Especially relevant once AV.* (auto-versioning) ships in 1.6.

**Suggested fix.** A `[View diff]` button in the footer before Save commits. Uses Monaco's built-in DiffEditor which is already in the bundle (per QS.22 notes). Reuses the same component AV.8 plans to use.

### 9.5 Monaco shows spellcheck wavy underlines on YAML keys (in Secrets modal)

**What I saw.** Secrets modal — Monaco renders red wavy underlines under `wifi_ssid`, `mira_cielo_*_mac`, etc.

**Why it matters.** Looks like "errors" at a glance. Actual errors get the same visual treatment, so a real validation error is harder to spot against a sea of spellcheck noise.

**Suggested fix.** Disable Monaco's browser spellcheck for YAML / secrets. Keep it on for text-like fields (rename, comment) where it's useful.

---

## 10. Secrets modal

### 10.1 Secrets shown in plaintext, streamer mode ignored

**What I saw.** `secrets.yaml` modal renders every credential fully visible. Streamer mode is toggle-ignored here.

**Why it matters.** This is the worst streamer-mode gap. The Connect Worker modal at least arguably shows only a bearer token; the Secrets view shows every WiFi password, every OTA password, every API token.

**Suggested fix.**
- When streamer mode is on, mask every VALUE in secrets.yaml (replace the quoted string with `"•••••••"` visually). Keep keys visible. The Save path still writes the real values (stored in state, not the visual).
- Add a per-value eye toggle for manual reveal.
- Add a modal-level banner when streamer mode is on: "Values hidden for streaming. Toggle the eye icon to reveal."

### 10.2 No search within secrets

**What I saw.** Monaco editor with 24 lines of secrets. To find `ota_password_2` in a 200-line file, Ctrl+F or page-scroll.

**Why it matters.** Fine today at 24 lines. Becomes painful as secrets grow (every BLE device's bindkey, every API token). Monaco has Ctrl+F built in — but it's not obvious.

**Suggested fix.** Add a hint in the toolbar: "Ctrl+F to search." Or a real filter input above the editor. Also mention "changes here apply to every device; run Compile to propagate" so users know saves aren't silent.

### 10.3 No warning about the blast radius of changes

**What I saw.** Save button sits in the top-right. Clicking saves. No banner, no confirmation.

**Why it matters.** Changing `wifi_password` and pressing Save affects every device on the fleet the next time they're compiled. This is high-blast-radius.

**Suggested fix.** Inline banner at the top of the modal: "Changes to secrets.yaml affect every device that references these keys. Run Upgrade All Online after saving to apply." Non-blocking but informative.

---

## 11. Row-level hamburger (DeviceContextMenu)

### 11.1 Menu items are well-organized but some states are opaque

**Status:** ✅ FIXED (1.5.0-dev.76) — WI UX.11. Disabled items now carry reason tooltips. `Restart` already had one (from #14). New: `Copy API Key` disabled → *"This device has no `api:` block with an encryption key. Add `api: { encryption: { key: ... } }` to enable."* Audit confirmed no other hamburger items are conditionally disabled.

**What I saw.** Hamburger items for `cyd-office-info`:
- **Device** section:
  - Live Logs
  - Restart *(disabled)*
  - Copy API Key *(disabled)*
- **Config** section:
  - Unpin version (2026.4.0)
  - Rename
  - Duplicate…
  - Delete *(red)*

**Why it matters.** Good structure with section headers. But `Restart` and `Copy API Key` are disabled with no visible tooltip. The user has to guess why.

**Suggested fix.** Tooltips on disabled items:
- `Restart` disabled: "This device's YAML has no `button: platform: restart` entry."
- `Copy API Key` disabled: "This device has no `api:` block with an encryption key."

This is the "Disable, don't fail" rule from `CLAUDE.md` — but the hover tooltip should also *explain* the disable, not just be a silent gray.

### 11.2 No "Compare with last deploy" / "View compile history"

**What I saw.** Menu doesn't include any historical lookups.

**Why it matters.** JH.* in 1.6 plans history drawer. Worth flagging here that the row menu is where those items will land.

**Suggested fix.** Noted; already in backlog as JH.5.

### 11.3 Destructive items lack confirm-before-execute (verify)

**What I saw.** `Delete` is red. I did not click it in this review. Rename — unclear if undo exists.

**Why it matters.** Delete on 67 devices = lots of chances for accidental fat-finger. Rename changes the YAML filename which propagates to HA entity IDs.

**Suggested fix.** Verify `Delete` prompts. If not, add confirm: "Delete cyd-office-info.yaml? This removes the config but not the device itself." Rename: show before/after preview including the new filename + "HA entity IDs won't change automatically" footnote if relevant.

---

## 12. Cross-cutting: visual consistency

### 12.1 Light mode applies to body but not header

**What I saw.** Header stays dark when body goes light. This might be deliberate (like VS Code's title bar) but is not called out anywhere.

**Why it matters.** Inconsistent theming = jarring. If it's intentional, a tiny "pro" — but then it needs to be cohesive with an always-dark accent strip across the whole page, which is a different design.

**Suggested fix.** Either make the header follow the theme (full light mode), or document as a deliberate "always-on navigation bar" choice. I recommend full light mode parity; the header in light mode looks unfinished rather than intentional.

### 12.2 Icons don't all have hover tooltips

**Status:** ✅ FIXED (1.5.0-dev.76) — WI UX.12. New **UI-7** invariant in `scripts/check-invariants.sh` flags any button/trigger with `aria-label=` but no `title=` (and vice versa). Existing icon-only buttons audited — all have both. CLAUDE.md's Enforced Invariants list updated with UI-7.

**What I saw.** Some icon-only buttons have tooltips (theme toggle, streamer mode), some don't (refresh ESPHome versions has aria-label but no visible tooltip on hover, "More actions" hamburger is also aria-label only).

**Why it matters.** `aria-label` is the right thing for screen readers but sighted users benefit from visible tooltips too. QS.2 addressed aria-label presence; it didn't ensure `title=` for hover.

**Suggested fix.** Add a new invariant (call it **UI-7**): every icon-only button MUST have both `aria-label` and `title` (or a shadcn `<Tooltip>` wrapper). Grep-enforceable via `check-invariants.sh`.

### 12.3 Button padding / height is close-to-uniform but not pixel-identical

**Status:** ✅ FIXED (1.5.0-dev.76) — WI UX.13. Audit found no remaining mismatches after WI UX.4 (Retry pill sync) and WI UX.6 (slot-row relayout). All row-action buttons and DropdownMenuTrigger replicas confirmed using `size="sm"` tokens.

**What I saw.** QS.27 normalized toolbar button heights. Rows are mostly aligned. A few stragglers (e.g., `Cancel` vs `Log` vs `Edit` in Queue row actions column look slightly different weights).

**Why it matters.** Minor. Only worth fixing if you land another consistency sweep.

**Suggested fix.** Ensure `components/ui/button.tsx` variants are applied consistently across rows. Probably a one-hour audit.

### 12.4 Table row hover highlight is subtle to absent

**What I saw.** Hovering a Devices-tab row showed minimal visual highlight (couldn't screenshot a hover state via Playwright cleanly — observed indirectly).

**Why it matters.** On dense tables, the hover highlight is how users track which row they're about to act on. Without it, clicking the wrong `Upgrade` button is easy.

**Suggested fix.** Strengthen row-hover background (subtle but clearly visible). Cursor `pointer` on any hoverable cell area.

### 12.5 No visual "active compile" breadcrumb outside Queue tab

**What I saw.** When a compile is running, you only know via the Queue tab badge (`1 active`). On Devices tab, the target being compiled shows no visual indicator.

**Why it matters.** Power users running 10 compiles want to see at a glance which rows are active.

**Suggested fix.** On Devices tab, overlay a small spinner or "Compiling…" chip on the row matching a WORKING queue job. Already-shipped event-bus WS (HI.*) makes this realtime; just need the UI hook.

### 12.6 Toast notifications — not observed in this review

**What I saw.** No toast fired during my nav; the test environment didn't generate user-facing events I could provoke without risking real device OTAs.

**Why it matters.** Bulk operations per workflow guidance "batch operations get one toast" — confirm this is consistent; no toast flood.

**Suggested fix.** Tested in e2e specs already; keep that discipline. Consider a `Toast.history` side-pane where a user can re-read recent toasts they missed.

---

## 13. Mobile viewport (390×844, iPhone 14 Pro size)

### 13.1 Horizontal-scroll header works (bug #1 fixed), but tab bar also horizontally scrolls

**What I saw.** Header is horizontally scrollable (fix per bug #1). Tab bar does too — `Devices | Queue | Workers | Schedules` plus badges overflow off screen. Works but the transition isn't obvious.

**Why it matters.** It's discoverable once you know, but on a first visit users don't realize you can swipe the tab bar.

**Suggested fix.** Fade/mask on the right edge of the tab bar when content overflows. Visually hints "more over here." Same pattern for the header.

### 13.2 Device table at mobile width is unusable

**What I saw.** At 390px viewport, the Devices table has the Status column clipped to `Onlir` / `1m ag`, with `Upgrade` + `Edit` buttons still at full size taking half the row width. Other columns (IP, HA, Net, Version) are off-screen right.

**Why it matters.** The target audience uses this from desktop 95% of the time, but mobile needs to at least *degrade usefully* — "I'm on my phone, which devices are offline?" should be answerable.

**Suggested fix.** Below 768px, switch the table to a card layout:
- Each device a card: device name + status + IP.
- Swipe-right on the card reveals actions (Upgrade / Edit / hamburger).
- Tap the card expands it to show the other columns.

Completely different layout, but the only way a dense desktop table transitions cleanly to mobile. This is a medium-lift item; keep the desktop table as primary experience.

### 13.3 Toolbar wraps awkwardly on mobile

**What I saw.** `+ New Device`, `Upgrade ▼`, `Actions ▼` wrap onto two lines. The column toggle sits on a third line by itself.

**Why it matters.** Visually unresolved.

**Suggested fix.** At narrow widths, collapse toolbar into a single `⋮` menu holding all bulk actions + column picker. New Device stays as a floating `+` FAB at bottom-right.

---

## 14. Terminology Audit

This is the most important cross-cutting section for a vocabulary-sensitive codebase.

### 14.1 Actions on a device / target

| Place in UI | Term used |
|---|---|
| Per-row button | `Upgrade` |
| Per-row button after selecting Download | `Compile & Download` |
| Bulk action | `Upgrade All / Upgrade All Online / Upgrade Outdated / Upgrade Selected` |
| Modal title (Now) | `Upgrade — <device>` |
| Modal title (Scheduled) | `Schedule Upgrade — <device>` |
| Queue state (Queue tab) | `COMPILING + OTA` |
| Queue state (Workers tab Current Job) | `Compiling + OTA` |
| Modal radio | `Compile + OTA` / `Compile + Download (no OTA)` |
| Toast (implied) | `Compile-and-download queued for <target>` (from FD.3) |
| Badge (done, download) | `Ready` (from jobState.ts:108) |
| Badge (done, OTA) | (probably `Success`?) |
| Badge (pending OTA after compile success) | `OTA Pending` (jobState.ts:115) |

**Problem.** Same operation shows as "Upgrade", "Compile + OTA", "COMPILING + OTA", "Compiling + OTA" depending on where you look. Users should not have to infer that all these words mean the same thing.

**Recommended normalization.** Adopt a small, consistent vocabulary:
- **Deploy** (or **Flash** — pick one; I recommend **Deploy** as it's HA-native) = the whole compile-and-OTA lifecycle. Button says `Deploy`, modal says `Deploy — <device>`.
- **Build** = compile only, no OTA. Used for "Compile + Download" today. Modal shows `Build & Download`, button `Build`.
- **Schedule Deploy** = scheduled variant. Modal title `Schedule Deploy — <device>`.
- State names (all sentence case): `Pending`, `Building`, `Flashing`, `Succeeded`, `Failed`, `Cancelled`, `Timed out`.
- Badge labels: `Queued`, `Building`, `Flashing`, `Done`, `Failed`, `Cancelled`, `Timed out`.
- Download-only success → `Binary ready` (clearer than `Ready`).

Pick the vocabulary, then one PR that mass-renames: buttons, modal titles, toast strings, badge labels, queue-state enum `to_display()`, Playwright test selectors.

### 14.2 Entities

| Internal (code) | User-facing (UI) | Notes |
|---|---|---|
| `Target` (TypeScript) | "Device" on the Devices tab | Types distinguish; UI doesn't |
| `Device` (TypeScript) | "Device" (under "Unmanaged" divider when `compile_target: null`) | Same label, different meaning |
| `Worker` (registry + UI) | "Worker" | Consistent |
| `client_id` (code) | (hidden) | OK — internal |
| `HA entity` | `In HA: Yes/—` + deep-link | Good |
| `job` (code + API) | `Job` / `Queue entry` | The Queue tab calls them "jobs" only implicitly |

**Problem.** "Device" is overloaded. The code carefully separates Target vs Device; the UI presents them as one concept.

**Recommended fix.** Either commit to "Device" as the universal UI term (and carry the YAML/Discovered chip per §3.1), or introduce "Target" into the UI for managed entries. Don't leave it implicit — at least one tooltip, one help section, and one filter chip should call out the distinction.

### 14.3 States and lifecycle

| Code enum | UI rendering (observed) | Notes |
|---|---|---|
| `JobState.PENDING` | "Pending" / "Queued"? | Didn't observe directly |
| `JobState.WORKING` | `COMPILING + OTA` / `Compiling + OTA` / `Compiling` | Three variants |
| `JobState.SUCCESS` (OTA) | presumably `Succeeded` | Verify |
| `JobState.SUCCESS` (download) | `Ready` | From jobState.ts:108 |
| `JobState.FAILED` | `Failed` | Verify |
| `JobState.TIMED_OUT` | See CR.4 in WORKITEMS-1.5 — dead write, never observed | Latent |
| `JobState.CANCELLED` | Observed in monitor logs; UI badge? | Verify |

**Recommended fix.** Match the vocabulary from §14.1. Add a legend somewhere (maybe a `?` button on the Queue toolbar that opens a small state-reference panel).

### 14.4 Schedule language

| Place | Term |
|---|---|
| Upgrade modal radio | `Now` / `Scheduled` |
| Scheduled mode sub-radio | `Recurring` / `One-time` |
| Cron preview | `Cron: 0 2 * * *` (raw) |
| Human preview (if shown) | `Every day at 02:00` (from formatCronHuman) |
| Schedules tab columns | `Schedule`, `Status`, `Last Run` |
| Empty state copy | "'Schedule Upgrade...'" — **stale, menu item removed** |

**Recommended fix.** Consistency + the §6.1 / §2.2 empty-state rewrite.

### 14.5 Icon usage

| Action | Icon seen | Notes |
|---|---|---|
| Refresh | circular arrow (`↻`) | Good |
| External link | arrow-to-top-right | Good |
| Pin | pushpin | Good — but only appears next to version, not as a per-row chip |
| More actions | three-dot vertical `⋮` | Good |
| Columns | sliders/settings icon | Good |
| Streamer mode | eye / eye-crossed | Good |
| Theme | sun / moon | Good |
| Delete | (red text, no icon) | A trash icon would help |
| Live Logs | (no icon, menu text) | A terminal/log icon would help |

**Recommended fix.** Lucide everywhere (CLAUDE.md rule, already established). Consider adding icons to menu items that lack them.

### 14.6 CONTAINER NAME is pre-rebrand

Already covered (§8.2). `distributed-esphome-worker` → `esphome-fleet-worker`.

### 14.7 Header brand fragmentation

**What I saw.** Logo + "ESPHome" + (separator) + "Fleet". The brand is "ESPHome Fleet" but visually it reads as two words separated.

**Why it matters.** Adequate today but worth noting. If `ESPHome` the company ever asks about trademark, the visual separation helps.

**Suggested fix.** None needed now. Keep as-is.

---

## 15. Accessibility spot-checks

### 15.1 Icon-only buttons have aria-label (QS.2 verified)

Observed: `Switch to light mode`, `Enable streamer mode (blur sensitive data)`, `Refresh ESPHome versions`, `Toggle columns`, `More actions` — all have real `aria-label`. 

### 15.2 Table is a proper `<table>` (semantic HTML, good)

Confirmed in the Playwright accessibility tree: `rowgroup`, `row`, `columnheader`, `cell` roles all present.

### 15.3 Focus visibility — not tested exhaustively

Suggestion: keyboard-only test pass. Tab through the Devices tab, confirm focus rings are visible on every interactive element including row checkboxes, row action buttons, hamburger, bulk-action dropdowns.

### 15.4 Dropdown focus trap

Radix handles this correctly (tested implicitly via Escape-closes-menu). 

### 15.5 Live-region for async updates

**Gap.** SWR polls at 1 Hz and updates silently. Screen-reader users won't hear "3 jobs now pending" when the Queue tab badge changes. No `aria-live` region observed.

**Suggested fix.** Add an `aria-live="polite"` region for meaningful state changes: job completions, new failures, worker goes offline. Keep announcements terse.

---

## 16. Prioritized Recommendations

Each finding mapped to a suggested workitem prefix (**UX.N**) so you can slot them into releases later. Ordered approximately by impact / effort ratio.

> **Status column added 2026-04-16.** Items with ✅ shipped in 1.5.0-dev.76 under the `UI Polish (from UX review)` section of `WORKITEMS-1.5.md`. **Strikethrough = fully addressed.** 🟡 = partial. "WI UX.N" refers to the WORKITEMS item ID, which is *not* the same numbering as this report's UX.N — the two sequences diverged because WI was sized at 13 items while the report's table has 45.
>
> Two additional findings were shipped that are not in the table below (they were flagged in the body only): **§3.12** (sort-indicator consistency, WI UX.2) and **§4.5** (worker-cell slot suffix, WI UX.6). Also shipped: **§4.1** badge-case (WI UX.3), **§8.2** container name (WI UX.9), **§11.1** hamburger tooltips (WI UX.11), **§12.3** button-height audit (WI UX.13) — each noted inline in the finding itself.

### High impact, low effort (quick wins — grab soon)

Status legend: ✅ shipped in 1.5.0-dev.76 (WI = the WORKITEMS-1.5.md item ID, which may not match the report's UX.N numbering). Unchecked items remain open for scheduling.

| Ref | Area | Finding | Effort | Status |
|---|---|---|---|---|
| ~~**UX.1**~~ | §2.2 | Rewrite Schedules empty state (pointer to removed menu item is a real bug) | XS | ✅ WI UX.1 |
| **UX.2** | §7.3 | Drop `Current (2026.4.0)` duplicate row in Upgrade version picker | XS | — |
| ~~**UX.3**~~ | §4.2 | Neutralize Retry button color (not a warning) | XS | ✅ WI UX.4 (shipped as **green**, not neutral — matches the other "do-it-again" buttons per your guidance) |
| ~~**UX.4**~~ | §11.1 | Add tooltips to disabled hamburger items explaining *why* | XS | ✅ WI UX.11 |
| **UX.5** | §3.6 | Rename column headers `HA` → `In HA`, `Net` → `Network` | XS | — |
| ~~**UX.6**~~ | §8.2 | Change Connect Worker default container name to `esphome-fleet-worker` | XS | ✅ WI UX.9 |
| **UX.7** (partial) | §3.3, §14.1 | Rename the core action vocabulary to `Deploy`/`Build`/`Schedule Deploy`; normalize badge case across Queue + Workers tab | S | 🟡 partial — case normalization shipped as WI UX.3; the full Deploy/Build rename was not taken. Modal-action labels unified as `Upgrade Now / Download Now / Schedule Upgrade` in WI UX.8. |
| **UX.8** | §4.3 | Clear dropdown: add counts, clearer labels (`Clear succeeded (N)` etc.), confirm on "Clear everything" | S | — |
| **UX.9** | §10.1 | Streamer mode blurs Secrets modal values + Connect Worker token field | S | — |
| **UX.10** | §2.1 | Standardize tab-badge format (ratios for stateful lists, attention-count for activity) | S | — |
| **UX.11** | §9.3 | Add unsaved-changes `●` marker + discard-confirm on editor close | S | — |
| **UX.12** | §9.5 | Disable Monaco spellcheck on YAML files | XS | — |

### High impact, medium effort

| Ref | Area | Finding | Effort | Status |
|---|---|---|---|---|
| **UX.13** | §3.4 | Merge bulk-action dropdowns into a single selection-aware action bar | M | — |
| **UX.14** | §5.1 | Workers tab: one row per worker; inline slot-state indicators instead of N rows | M | — |
| **UX.15** | §5.3 | Platform cell → structured chips instead of prose | M | — |
| **UX.16** | §3.11 | Add filter-chip row on Devices tab (Online / Needs update / Pinned / Area / Network) | M | — |
| ~~**UX.17**~~ | §4.4 | Triggered column: richer display (Manual / HA user / cron / one-time / retry-of) | M | ✅ WI UX.5 (retry-of deferred to 1.6) |
| ~~**UX.18**~~ | §7.2 | Merge "Now/Scheduled" + "Compile+OTA/Download" into single 3-option action selector | M | ✅ WI UX.8 |
| **UX.19** | §9.1 | Editor button weight/split-button refactor: one primary, compound actions under dropdown | M | — |
| ~~**UX.20**~~ | §12.2 | New invariant UI-7: icon-only buttons require both `aria-label` and `title`/Tooltip | XS (invariant) + M (audit) | ✅ WI UX.12 |
| **UX.21** | §5.5 | Per-worker hamburger menu (Clean Cache + Pause/Resume + Remove + Rename) | M | — |
| **UX.22** | §12.5 | Show an in-progress chip on Devices rows that have a WORKING job | M | — |

### Medium impact, medium-to-large effort

| Ref | Area | Finding | Effort | Status |
|---|---|---|---|---|
| **UX.23** | §3.1 | Target vs Device distinction surfaced in UI (chip + filter) | M | — |
| **UX.24** | §6.2 | Schedules tab: add `Next Run` column, Kind chip, Enabled toggle | M | — |
| **UX.25** | §6.3 | Bulk pause/resume on Schedules tab + global "Pause all" maintenance toggle | M | — |
| **UX.26** | §1.1 | Header reorganization + demote `ESPHome Web ↗` to overflow menu | M | — |
| **UX.27** | §3.10 | HA column cell enrichment: tooltips explaining `—` state per device | S | — |
| ~~**UX.28**~~ | §8.4 | Add Docker Compose tab to Connect Worker modal | M | ✅ WI UX.10 (plus retired `docker-compose.worker.yml`) |
| **UX.29** | §13.2 | Mobile: switch Devices table to card layout below 768px | L | — |
| **UX.30** | §12.1 | Light mode parity for the header (or document as intentional) | S | — |
| **UX.31** | §8.1 | Streamer-mode masking of server token in Connect Worker (code block + plain field) | S | — |

### Lower priority / stretch

| Ref | Area | Finding | Effort | Status |
|---|---|---|---|---|
| **UX.32** | §3.5 | Column-picker grouping + saved views | M | — |
| **UX.33** | §3.2 | Row-action audit: hover-reveal pattern or Logs-promoted variant | M | — |
| **UX.34** | §4.7 | Queue Pending row ETA / position indicator | M | — |
| **UX.35** | §10.2, §10.3 | Secrets modal: search hint + blast-radius banner | S | — |
| **UX.36** | §9.4 | Editor: diff preview before Save (pairs with AV.* in 1.6) | M | — |
| **UX.37** | §1.2 | Dev-version pill: semantic states (stable / dev / update available) | S | — |
| **UX.38** | §9.2 | Editor keyboard-shortcut tooltips + `?` help overlay | S | — |
| **UX.39** | §13.1 | Mobile: fade mask on tab bar overflow edges | XS | — |
| **UX.40** | §15.5 | `aria-live` region for async state changes | S | — |
| **UX.41** | §5.2 | "Score" legend or replacement | XS | — |
| **UX.42** | §5.6 | Slot counter: show busy/total inline | S | — |
| **UX.43** | §12.4 | Stronger row-hover highlight | XS | — |
| ~~**UX.44**~~ | §7.1 | "Worker" default label: `Any available worker (auto)` instead of `<any>` | XS | ✅ WI UX.7 |
| **UX.45** | §7.5 | "Remove schedule" tertiary button inside Schedule modal | XS | — |

### Out-of-scope flags (not in the above lists)

These are findings deliberately NOT queued because they overlap with existing workitems:
- **AV.*** auto-versioning + diff viewer — already in 1.6.
- **JH.*** job history drawer — already in 1.6.
- **WC.*** worker names + tags — already in 1.6. Pair with UX.14 (slot visualization) and UX.21 (per-worker menu) when implemented.
- **WU.*** worker update docs + stale badge tooltip — already queued in 1.6 CR.18 follow-ups.
- **UE.*** HA native update entities — already in 1.6.

---

## 17. Things that are working well (credit where due)

- **Shadcn + Base UI primitives** across modals / dropdowns / menus. Consistent interaction model.
- **Hamburger menu state lifted out of row cells** (bug #2 / #71 memory) — drop-down stays open across SWR polls.
- **Streamer mode exists at all** — most OSS tools don't think about this.
- **Device / Target split in types** is a great foundation for a future UI refinement.
- **ESPHome version dropdown with per-version search + beta toggle + refresh** — exactly the right power-user affordance.
- **Inline cron preview** in Schedule modal.
- **Built-in pill** on `local-worker` row.
- **`$(hostname)` default** in Connect Worker HOSTNAME field — preserves shell-time resolution.
- **The Queue tab's triggered-column icon vocabulary** (person icon for User) is the right start.
- **Empty state on Schedules exists** (even if it needs a copy fix).
- **`via mDNS` / `wifi.use_address` IP-source exposure** is exactly the right power-user hint.
- **HA deep-link icon on every managed device** — tiny but high-value.
- **`Pinned version` marker** even as a small icon.

---

## 18. Appendix — what I did NOT cover

Items I would want to include in a deeper review but are out of scope for this pass:

- **Full keyboard navigation sweep** — Tab order, focus rings, reachability of every action.
- **Axe-core / WCAG compliance check** — color contrast ratios, reduced-motion respect, `prefers-reduced-motion`.
- **Real device interaction** — I did not trigger a real compile-and-OTA during this review (production smoke is the `cyd-office-info` target which is the designated test device, but still production traffic).
- **Log viewer / Live Logs modal** — would need to trigger a log stream.
- **Validate endpoint UX** — clicking Validate in the editor shows what? Banner? Modal?
- **Error states I couldn't provoke** — what does a failed compile look like in the Queue? A stale-image worker badge? A 5xx server response?
- **Network-throttled experience** — the 1 Hz SWR polling behavior over a slow VPN.
- **Performance profiling** — React DevTools flame graph of DevicesTab on a 200-device fleet.

Each deserves its own pass. Suggested cadence: one accessibility pass per quarter, one full UX pass per release cycle.

---

*End of review. Screenshots: `.playwright-mcp/ux-01.png` through `ux-20.png`.*
