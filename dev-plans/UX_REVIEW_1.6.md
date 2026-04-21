# UX Review — 1.6.0 New Surfaces

**Review type:** Hyper-critical pre-ship walkthrough.
**Method:** Live Playwright session against `hass-4` (running `1.6.0-dev.26`) at 1440×900, dark mode, with the production fleet (67 devices, 7 workers, real history).
**Persona reference:** `dev-plans/USER_PERSONA.md` ("Pat" — tech-curious homeowner, 30–150 devices, info-dense over progressive disclosure, allergic to inconsistency, dark-mode default, keyboard-operable).
**Scope:** SP.\* (Settings drawer), AV.\* (Auto-versioning history panel + manual commit), JH.5/6/7 (compile history surfaces). Bug fixes #1–#46 in the same release are spot-checked.

This review only flags problems. The features themselves are mostly good and most of the per-bug fixes (#13–#46) landed cleanly — what's listed below are the rough edges that survived. **Anything tagged 🚫 SHIP-BLOCKER is something Pat would notice in week one and lose trust over. Tagged ⚠️ POLISH items are "we should fix these but they don't justify holding the release."**

---

## Dispositions (added 2026-04-19 post-review)

Queued as WORKITEMS-1.6.md bugs; this index records the disposition for every item the review raised.

| § | Status | Workitem |
|---|---|---|
| 1.1 | FIX | #75 |
| 1.2 | FIX | #76 |
| 1.3 | WONTFIX — review's recommended order is wrong; Config-versioning-first is intentional | ~~#88~~ |
| 1.4 | ALREADY SHIPPED via #51 at dev.26 — works as designed now | #84 |
| 1.5 | FIX | #77 |
| 3.1 | WONTFIX — intentional; commit list is peer content to the diff, not navigation | ~~#89~~ |
| 3.2 | FIX | #78 |
| 3.3 | FIX (parity check — Restart / Copy API Key already done; audit the rest) | #79 |
| 3.4 | ALREADY SHIPPED via #65 at dev.35 (`utils/trigger.tsx`) | #85 |
| 3.5 | WONTFIX — group headers disambiguate; leave as-is | ~~#90~~ |
| 3.6 | ALREADY SHIPPED — `SettingsDrawer` toasts "Setting saved" on every PATCH | #86 |
| 3.7 | FIX — surface bounds from `settings.py` validators | #80 |
| 3.8 | ALREADY SHIPPED — reveal + copy buttons have `aria-label` + `title` (UI-7) | #87 |
| 3.9 | FIX | #81 |
| 3.10 | FIX — make user-configurable with server-locale default (`auto` / `12h` / `24h`) | #82 |
| 3.11 | WONTFIX — keyboard shortcuts aren't a pattern we use anywhere else | ~~#91~~ |
| 3.12 | FIX — is a bug | #83 |

---

## 1. Ship-blocking findings

### 🚫 1.1 Restore-confirmation dialog says the wrong thing about auto-commit

**Where:** History panel → click *Restore* on any commit row.
**What I saw:**

> "The file on disk will be replaced with its content at 315542d. **No new commit will be created (auto-commit is off).**"

The Settings drawer toggle for `Auto-commit on save` was demonstrably **on** at the same moment (verified via `GET /ui/api/settings` → `"auto_commit_on_save": true`).

**Why this matters for Pat:** Pat's threat model with auto-versioning is "Fleet won't surprise me by writing commits I didn't approve." A dialog that **lies** about the current state — "no new commit will be created" when in fact one will — directly undermines that contract. First time Pat does a Restore expecting a clean working tree and gets an extra `revert:` commit they didn't ask for, trust in the entire AV.\* system erodes.

**Fix:** the body copy in `HistoryPanel`'s restore dialog must read the LIVE setting via SWR (same hook the Settings drawer uses), not a stale or default value. Cover with a Playwright test that toggles auto-commit, opens History, opens Restore, asserts the body text matches the live setting.

---

### 🚫 1.2 Manual-commit prompt placeholder shows the legacy raw subject, not the human-readable form

**Where:** History panel → "You have uncommitted changes" banner → click *Commit…* → message field.
**What I saw:** placeholder reads `save: cyd-office-info.yaml (manual)` — the pre-#34 raw form. Meanwhile the actual commits in the list directly below render as the curated `_DEFAULT_SUBJECTS` strings: *"Automatically saved after editing in UI"*, *"Set one-time scheduled upgrade"*, etc.

**Why this matters for Pat:** Pat is the one who flagged inconsistency as a top-tier irritation in `archive/UX_REVIEW-1.5.md` ("notices when 'Upgrade' and 'COMPILING + OTA' refer to the same thing"). Showing the old jargon-ish form as the suggested default while the rest of the surface uses the new human form is exactly the kind of inconsistency that grates. It also implies #34 was incomplete — the developer-facing default is curated, the user-facing default is not.

**Fix:** placeholder should show the manual-commit default subject from `_DEFAULT_SUBJECTS` (`"Manually committed from UI"`). One-line change in the UI; verify with a screenshot Playwright test against the placeholder text.

---

### 🚫 1.3 Settings drawer section ordering is feature-driven, not user-need-driven

**Where:** Settings gear → drawer.
**What I saw:** sections in this order:
1. Config versioning
2. Job history
3. Disk management
4. **Authentication** (server token, require-HA-auth)
5. Timeouts
6. Polling
7. About

**Why this matters for Pat:** Authentication is **foundational** — it's the second thing Pat does after install (after seeing devices populate). The server token is what Pat copies into the `docker run` command for every remote worker. Having Authentication 4th (and a 7-section scroll deep) buries the most-reached-for setting. Worse, Auth is sandwiched between "Disk management" (a niche disk-budget knob) and "Timeouts" (rarely touched) — so Pat scrolls past it twice when scanning for a recognizable section header.

The current ordering reflects the **order features were built**, not the **order Pat reaches for them**.

**Fix (recommended ordering):**
1. Authentication (most-reached, foundational)
2. Config versioning (Pat's main 1.6 surface)
3. Job history
4. Disk management
5. Timeouts
6. Polling
7. About

Add Lucide icons to the section headers (`Lock`, `GitBranch`, `History`, `HardDrive`, `Clock`, `Radar`, `Info`) — matches CLAUDE.md's "Icons: Lucide only" rule, gives Pat a visual scan path, and replicates the Section pattern HA's own settings use.

---

### 🚫 1.4 Compile-history log progress bar still renders as a static `===` strip

**Where:** Queue tab → *History* button → expand any Success row OR Devices row → *Compile history…* → expand a Success row.
**What I saw:**

```
Uploading: [=====================================================] 100% Done...
INFO Upload took 6.65 seconds, waiting for result...
INFO OTA successful
INFO Successfully uploaded program.
```

Bug **#51** explicitly calls this out and is currently `[ ]` (open). The renderer is dumping the literal final state of a `\r`-overwriting tqdm bar rather than collapsing it. The persona's "live logs" surface elsewhere correctly handles `\r` to render an in-place updating bar that ends up as a single `100% Done...` line.

**Why this matters for Pat:** the log excerpt is where Pat reads back what happened. A 60-character row of `=` signs IS a visual artifact that screams "we're shipping an unpolished surface." Inconsistency with the live-log renderer is the same Pat-irritant as 1.2 above.

**Fix:** route `log_excerpt` through the same ANSI/CR-collapsing renderer the Live Logs modal uses. The `utils/ansi.tsx` helper from #36 already handles colour; extend it to honour `\r` (collapse-to-last-segment-on-line) and call it from both surfaces.

---

### 🚫 1.5 "Last compiled" column SUCCESS indicator renders as a tiny bullet

**Where:** Devices tab → column picker → enable *Last compiled*.
**What I saw:** `cyd-office-info` row shows `3m ago ·` — a small mid-line bullet character after the relative time. The JH.6 spec calls for `Xago ✓` (green check) on success, `Xago ✗` (red) on failure. What renders looks more like a stray separator or a missing icon glyph than the documented success badge.

**Why this matters for Pat:** the whole *point* of JH.6 is "scan the Devices tab for stale or red devices at a glance." A tiny bullet doesn't read as a status — it reads as a typo. Pat would have to hover to find the truth.

**Fix:** use the existing `utils/jobState.getJobBadge` (the same function the Queue tab and JH.5 use) so the chip's visual shape and colour are consistent across all three surfaces. Tooltip shows the absolute date + state — already in spec, just needs the visible badge to match.

---

## 2. Real bugs already filed but worth re-emphasising for ship

These are open bugs in `WORKITEMS-1.6.md` that I confirmed are still biting in the live UI. Calling them out here so they don't get triaged "low" by mistake:

| # | Title | Notes |
|---|---|---|
| **#47** | Started + duration blank for cancelled jobs | Both surfaces show `—` for cancelled rows. Not a bug per se but the user explicitly flagged it as confusing. Fill at least `started_at` (we have it) and show `cancelled` as the duration explanation, e.g. `cancelled before start` / `0s (cancelled)`. |
| **#49** | "Time picker is super jank" | Confirmed. Clicking the "Last 30 days" pill drops you straight into a Custom range picker that shows weekday headers cut off, no month/year label, and a `To: 23:59` time field. The promised preset-pill row (24h / 7d / 30d / 90d / 1y) is missing entirely. Pat hits this on every history-window change. |
| **#51** | Progress bar in history is messed up | Confirmed (see 1.4 above — promoted to ship-blocker). |
| **#52** | Mono vs regular font inconsistency | Confirmed. Commit hash is mono; everything else is sans. Inconsistent with how the Queue tab's row layout treats hashes (also mono there but row-density differs). |
| **#53** | Sorting in history modal doesn't change SQL | Could not confirm from UI alone — the `Finished ↓` arrow is visible and clickable, but proving it doesn't push down to SQLite needs a network-trace check. Worth running before ship. |
| **#54** | Window-presets vs infinite scroll incoherence | Counterpoint: presets are a SQL-window filter, infinite scroll is page-load. They're not conceptually contradictory — they could coexist if presented as "SQL filter window" + "loading more rows within that window". The user's read of "doesn't make much sense" is real though, because the *visual* presentation doesn't communicate the difference. Surface "Showing 26 rows from the last 30 days" near the row counter, not just "Showing 26 rows". |

---

## 3. New polish findings (not previously filed)

### ⚠️ 3.1 History-panel diff editor is cramped vertically

**Where:** AV.6 history drawer.
**What I saw:** the Monaco DiffEditor sits at ~330px tall — about 17 lines of YAML. Configs at hass-4 routinely run 100+ lines (the BMS, the matter test, the gate controllers). Pat will scroll the diff editor scroll-within-a-drawer-within-the-page, three nested scroll contexts.

**Fix:** make the diff editor consume the visible drawer height minus the From/To bar and a 1-line commit-list teaser. Move the commit list to a collapsible "Commits ▾" footer or to a left rail. The diff IS the headline content; commit list is navigation.

---

### ⚠️ 3.2 History drawer covers the underlying tab but doesn't darken/disable it

**Where:** AV.6, JH.5 drawers.
**What I saw:** the drawer covers ~70% of viewport width but the Devices table on the left is still rendered at full opacity, stale (workers/devices keep updating in the background, badges flicker). Pat's eye keeps darting back to the still-live table.

**Fix:** add the standard shadcn Sheet `overlay` prop with a 40–60% black overlay over the underlying app. Other modal surfaces in the app (Restore dialog) already do this; the drawer is the odd one out.

---

### ⚠️ 3.3 "Greyed-out menu items have no tooltip explaining why"

**Where:** Devices row hamburger → *Restart* (greyed) and *Copy API Key* (greyed) on devices that lack a `restart_button` or an `api.encryption.key`.
**What I saw:** both greyed, no `title=` / no tooltip. Pat hovers, gets nothing, clicks (no-op or disabled), guesses.

**Fix:** add the same `title=` pattern archive/UX_REVIEW-1.5.md flagged for icon buttons. Strings: *"Add a `button.restart` to this YAML to enable Restart from the UI"* / *"Set `api.encryption.key` to enable API access"*. Also matches CLAUDE.md's "Disable, don't fail" rule — currently we disable but don't tell them how to enable.

---

### ⚠️ 3.4 Trigger-source label inconsistency: "HA action" vs "HA"

**Where:** Queue tab vs Compile History modal.
**What I saw:** Live Queue tab → trigger column reads `🏠 HA action` (full label). Compile History modal → trigger column reads `HA` (truncated, no icon). Same data, two different shapes.

**Fix:** use the same renderer (a single React component, e.g. `<TriggerLabel job={...} />`) on both surfaces. Pat's "allergic to inconsistency" preference makes this a small irritant.

---

### ⚠️ 3.5 Two history items in the hamburger ("Compile history…" + "Config history…") could collide

**Where:** Devices row hamburger.
**What I saw:** under the **Device** group: *Compile history…* (JH.5). Under the **Config** group: *Config history…* (AV.6). The disambiguation works because of the group headers, but a Pat scanning quickly will see "two history items" and pause.

**Fix (small):** add lightweight Lucide icons next to each — `History` (clock-with-arrow) on Compile history, `GitBranch` on Config history. The icons reinforce the section grouping faster than the indented headers do.

---

### ⚠️ 3.6 Settings drawer has no save-confirmation feedback

**Where:** Any setting change (toggle, number input).
**What I saw:** no toast, no checkmark, no "saved" indicator. The header reads "Changes take effect immediately" in small grey type — but that's a STATIC string, not a confirmation of the specific change.

**Fix:** ephemeral inline state per row — a brief checkmark or "Saved" pill that appears for ~1.5s after the PATCH succeeds. Or a single sonner toast for the field name. The current design technically works (next request reflects the change) but Pat's fingers don't know whether the toggle "took" without poking at another part of the UI.

---

### ⚠️ 3.7 No min/max hints in numeric Settings inputs

**Where:** Job timeout, OTA timeout, Worker offline threshold, Device poll interval, Retention (days), Firmware cache size (GB), Job log retention (days).
**What I saw:** plain `<input type="number">` with no helper text about valid ranges. Pat sets `Job timeout` to `0` — what happens? Sets it to `5` (way too low) — what happens?

**Fix:** add `(default 600, min 60, max 7200)` to the helper text under each numeric setting. Server-side the validators in `settings.py` already know these bounds — surface them. Same shape as how the spec calls out `0 = unlimited` for Retention.

---

### ⚠️ 3.8 Authentication section's "Server token" reveal/copy buttons have no tooltips

**Where:** Settings → Authentication.
**What I saw:** masked password field, eye-icon (reveal), clipboard-icon (copy). Both icon-only with no `title=` / no `aria-label` visible to a hover. CLAUDE.md UI-7 explicitly says icon-only buttons need both `aria-label` AND `title`.

**Fix:** add `aria-label="Show server token"` + `title="Show server token"` to the eye, `aria-label="Copy server token to clipboard"` + matching `title=` to the clipboard. UI-7 is an enforced invariant — this might already fail `check-invariants.sh` if it's grep-aware enough.

---

### ⚠️ 3.9 "Restore" button is shown on every commit row including HEAD itself

**Where:** AV.6 commit list.
**What I saw:** every row has a Restore button — including the topmost (most recent) commit, where Restore is a no-op (`git checkout HEAD -- file` against an unchanged file). Pat clicks; nothing visible happens; trust dings.

**Fix:** disable Restore (with `title="Already at this version"`) when the row is HEAD AND the working tree is clean for that file. The data to compute this is already on the page (HEAD is the first row's hash; `has_uncommitted_changes` is on `Target`).

---

### ⚠️ 3.10 Times in Queue tab use 12-hour AM/PM, mixed with relative-time everywhere else

**Where:** Queue tab Start/Finish columns.
**What I saw:** `08:42:41 PM` / `1m ago`. Pat is plausibly European (per persona) and uses 24-hour time daily.

**Fix:** match the relative+absolute format used in the History panel commit list (`1h ago` over `Apr 18, 19:34`). 24-hour. Locale-aware via `Intl.DateTimeFormat` if we want to be properly global. At minimum, drop the AM/PM.

---

### ⚠️ 3.11 No keyboard shortcuts documented or available on the new drawers

**Where:** Settings drawer, History panel, Compile history drawer, Compile History modal.
**What I saw:** `Esc` closes drawers (good). But nothing else: no `↑/↓` to navigate commit list, no `c` to open commit dialog, no `?` to show shortcuts. Pat keyboards.

**Fix:** at minimum, document `Esc` close in the drawer headers. Stretch: implement `↑/↓` + `Enter` to set From/To on commit rows; `r` to Restore the focused row.

---

### ⚠️ 3.12 Scheduled-once jobs that get cancelled show in history with "—" for everything except finished_at

**Where:** Compile history drawer + Queue History modal.
**What I saw:** rows like `Cancelled · 22m ago · — · Scheduled (once) · 2026.4.0 · 315542d`. Worker is `—`, duration is `—`, started is `—`. Pat sees these and asks "did this even happen?"

**Fix:** for Scheduled+Cancelled, render the trigger as `Scheduled (once) — cancelled before start` and drop the `—` placeholders. The data we have ABOUT the cancelled scheduled job is the schedule itself + the cancellation time + the reason. Render that. Currently we render the absence.

(This is bug #47 with extra context.)

---

## 4. Things 1.6 got right (so we keep them)

Don't undo these:

- **The "Uncommitted" yellow pill on the device name** (#16). Genuinely the kind of always-visible-at-a-glance signal Pat wants.
- **AV.6 history panel as a Sheet, not a modal-in-modal**. Lets Pat keep the Editor open underneath when desired.
- **`_DEFAULT_SUBJECTS` curated commit messages** (#34). Reads like an activity feed in `git log`. *Don't regress to raw `action: filename` form.* (See 1.2 above for where this regressed for the placeholder text.)
- **JH.5 stats strip** ("16 total · 9 ok · 7 cancelled · avg 33s · last 30d") — exactly the dense, scannable summary Pat wanted from the original WORKITEMS spec.
- **The Commit-hash buttons that open AV.6 preset to that hash** (#41). Three different surfaces (Queue tab Commit column, JH.5 row, JH.7 row) all do the same thing — that consistency is rare and good.
- **Restore confirmation as a real shadcn Dialog** (#15) with destructive-styled action button. Don't ever put it back to `window.confirm`.
- **Two-side-by-side Monaco DiffEditor with `useInlineViewWhenSpaceIsLimited: false`** (#12). Read-quality is high.

---

## 5. Pre-ship recommended actions

In priority order (highest-bang-per-fix first):

1. **Fix 1.1** (Restore-dialog auto-commit lie) — single-component fix, high trust impact. **30 min.**
2. **Fix 1.2** (Commit prompt placeholder) — one-line UI change. **10 min.**
3. **Fix 1.4 / #51** (progress bar artifact in history logs) — refactor to share the live-log renderer. **2–3 hr.**
4. **Fix 1.5** (Last compiled column success badge) — swap to `getJobBadge`. **30 min.**
5. **Fix 1.3** (Settings drawer section ordering + icons) — restructure + add 7 icons. **1 hr.**
6. **Fix #49** (jank time picker) — replace bare calendar with a real preset row + a polished custom range. **3–4 hr.**
7. **Fix 3.7** (numeric setting min/max hints) — pull bounds from `settings.py` validators, render in help text. **45 min.**
8. **Fix 3.8** (icon-button labels — UI-7 invariant) — quick audit + 2-line fix per button. **20 min.**
9. **Fix 3.4** (Trigger label consistency) — extract to one shared component. **1 hr.**
10. **Fix 3.10** (24-hour time in Queue) — locale-aware formatter + spec test. **45 min.**

**Total**: roughly one focused day of work. Items in 3.\* that aren't on the list are nice-to-haves; defer to a 1.6.1 polish pass if time is tight, but **don't ship 1.6 with 1.1, 1.2, 1.4, 1.5 unfixed** — those four are the ones that actively erode Pat's trust.

---

---

*Reviewer's overall take: 1.6 is genuinely a strong release — auto-versioning + job history is the most user-noticeable jump in product capability since the original distributed-compile work. The four ship-blocking findings are all SMALL fixes (a misread setting, a stale string, a renderer reuse, a badge swap), but they're at exactly the spots Pat looks at first when learning a new feature. Burn one focused day on items 1–5, sit on the rest until 1.6.1.*
