# UX Review — 1.6.2 Patch-Release Walkthrough

**Review type:** Patch-release walkthrough — spot-check of new/changed surfaces, not a full re-review. Same shape as `archive/UX_REVIEW-1.6.1.md`.
**Method:** Live hass-4 (`1.6.2-dev.40` final dev), dark mode, production fleet (67 devices, 6 workers, real history). Fresh HAOS VM 106 also walked for the empty-state paths (#190 add-device, #191 log-line, truly-empty `/config/esphome`).
**Persona reference:** `dev-plans/USER_PERSONA.md` ("Pat").
**Scope:** only surfaces that changed since 1.6.1 — the bulk of `archive/UX_REVIEW-1.6.1.md`'s walk still applies verbatim.

New / changed surfaces walked:

- **Request diagnostics** (#109, #189) — Workers tab Actions menu + Settings → Advanced → Diagnostics button
- **Queue Clear dropdown** gained **Clear Selected** (#85)
- **Direct-port 401** now renders a styled HTML page for browsers (bug #82/#87 family)
- **Connect Worker** modal Bash + PowerShell snippets include `--network host` (TR.4)
- **Add Device** empty-state first-install works (#190)
- **Scanner missing-config-dir** log line fires once at INFO, no poll spam (#86)

Quality-scale claim retreated `silver` → `bronze` in `manifest.json`; UI itself is unchanged (the claim appears on the HA Integrations card, not in Fleet's UI).

## Findings

No new UX regressions against 1.6.1. Three lightweight observations for 1.6.3 pickup:

- **UX.1 — Request diagnostics lacks a visible in-progress indicator.** Settings → Advanced → Request diagnostics fires a synchronous POST and the button sits at its default state during the ~100 ms network round-trip. Two toasts fire (`Requesting…` then `Downloaded`) so the user does get feedback, but a disabled-while-pending button would close the "did I click it?" ambiguity on slow LAN. For the worker variant — Workers tab Actions → Request diagnostics — the round-trip can take up to 10 s (waits for the worker's next heartbeat), and the 30-s timeout inside `requestWorkerDiagnostics` is silent while running. Either a spinner next to the menu item or an explicit "Requesting from `<worker>`… (up to 30 s)" toast would set expectation.

- **UX.2 — Empty Devices tab on a truly-first-install lacks CTA.** After #190 fixed the underlying Add Device failure, a fresh HAOS user lands on an empty Devices table with the same "No devices yet" copy an unhelpful "scroll looking for a button" experience. A prominent **Add your first device** button (or "Get started" card) at the empty-state would solve the "what do I click first" problem the HAOS first-install flow still presents. Not a 1.6.2 regression — the empty state was equally bare on 1.6.1 — but #105's PyPI fallback newly exposes this state to the HAOS install path.

- **UX.3 — ~~Request diagnostics downloads name collide across repeated clicks in the same second.~~** Resolved during review cycle: `terminal.ts` timestamp suffix extended to millisecond precision (`slice(0, 23)` instead of `slice(0, 19)`) for both `downloadTerminalText` and `downloadTextFile`. PR #87 Copilot thread.

No blocker-class findings. 1.6.2 ships.

## Screenshot review

`docs/screenshot.png` hero is still the canonical shape from bug #17 (1.6.1) — Devices tab + History drawer open + diff view. Unchanged in 1.6.2; the surfaces in the screenshot are visually identical to 1.6.1. No refresh needed for 1.6.2; existing file represents.

## Persona check

Walked Pat through: fresh HAOS install → onboarding → add-on install from add-on store → **no ESPHome builder add-on installed** → server self-bootstraps ESPHome from PyPI (#105) → opens Fleet UI → empty Devices tab → clicks **Add device** → enters name → staged YAML lands in editor → saves → device appears in table. Every step worked end-to-end for the first time across all 1.6.x patch releases; the class of "get stuck on first install" bugs from 1.6.1 (#82 image pull, #83 auth prompt, #105 ESPHome install hang, #190 Add Device, #84 OTA address) is closed.
