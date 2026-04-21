# Contributing to ESPHome Fleet

Thanks for taking the time — a quick tour of how this repo works so you can get a PR landing without surprises.

## How this project is built

ESPHome Fleet is **vibe-coded** — most of the code, tests, docs, and release checklists are produced by a single developer working alongside Claude Code (`claude.ai/code`) as the primary authoring tool. The maintainer drives scope and design decisions; the agent does the typing, writes the tests, catches the invariant violations, and keeps the cross-referenced documentation in lockstep with the code. That workflow shapes a few things you'll notice in the repo:

- **`CLAUDE.md`** at the repo root is the load-bearing design document. It's written to be loaded into the agent's context on every turn, so it's long, opinionated, and specific — "don't do this because we tried it in 1.3 and it broke X." It is also the single best single-file reference for humans; read it before making non-trivial changes.
- **Comments are denser than typical** — the narrative of *why* a branch exists, who reported the bug it fixes, and why a particular shape was picked over an obvious alternative is in-tree rather than in a scattered wiki. Assume the comments are load-bearing for future refactors.
- **Enforced invariants** (see below) do the work that a human reviewer would do on a larger team: grep-checkable rules that fail CI instead of relying on reviewer vigilance.
- **Every turn ships a dev-build** (`-dev.N`) deployed to a local HA test instance with a real hardware smoke test, so regressions are caught in minutes, not weeks.

You do not need to use Claude (or any AI) to contribute — the code is plain Python + TypeScript, the invariants are grep-checkable, and the tests tell you when something is off. But the project's shape — dense comments, invariant checks, parallel docs that must stay in sync — is easier to grok if you know the authoring workflow it came from.

## Quick orientation

- **`develop`** is the trunk. Every change lands here first; `-dev.N` versions live on this branch. Open your PR against `develop`, not `main`.
- **`main`** holds tagged stable releases (`vX.Y.Z`). Don't push to it directly — releases flow through a PR from `develop`.
- **`CLAUDE.md`** at the repo root is the deep reference for conventions, enforced invariants, and the design philosophy. If something in here is terse and you want the "why," that's where the longer version lives.
- **`dev-plans/`** — everything release-scoped. See the next section.

## Planning docs: `dev-plans/`

The `dev-plans/` directory is where scope, bug tracking, audits, and the release process all live. It's indexed by **[`dev-plans/README.md`](dev-plans/README.md)**, but here's what each file is for:

- **`WORKITEMS-X.Y.md`** — one per release. Mixes work items (planned features, marked `[x]` when done) and bug fixes (checkboxes with `**#NNN**` IDs and `*(X.Y.Z-dev.N)*` version tags). The file for the **current** release is the one to edit — that's where new bugs get filed under *Open Bugs & Tweaks* and where in-progress features live. The current release is named at the top of `dev-plans/README.md`.
- **`WORKITEMS-future.md`** — backlog without committed scope. Ideas that might land in a future release but haven't been selected.
- **`archive/`** — `WORKITEMS-*.md` for every shipped release. Historical reference only; don't edit.
- **`RELEASE_CHECKLIST.md`** — step-by-step release process (version bump, changelog, security doc refresh, PR to `main`, tag, cleanup). Don't improvise a release — the checklist encodes hard-won lessons about what to update when.
- **`SECURITY_AUDIT.md`** — the project's security posture. 21 individual findings (F-01 through F-NN) with severity ratings, status, and remediation notes. A `**Refresh note (date, X.Y.Z)**` paragraph at the top summarises every cycle's deltas. Read it before making security-relevant changes; update it when your change closes or opens a finding.
- **`USER_PERSONA.md`** — "Pat," the target user. Scope / UX / copywriting tiebreaker when it's not obvious whether a feature is worth the effort.
- **`UX_REVIEW_X.Y.md`** — per-release UX walkthrough with numbered findings (`UX.N`) that feed the next release's WORKITEMS.

**Bug numbering.** Bugs are global and monotonic across releases — never reset. When you fix bug #NNN, check the box with the exact dev-build that shipped the fix: `- [x] **#NNN** *(X.Y.Z-dev.N)* — description`. Feature work items use workstream codes (`AV.1`, `SS.2`, `QS.3`) instead of numeric IDs so the two don't collide.

**Never reshuffle workitems between releases without an explicit ask** (from the maintainer, in the PR thread). Don't move action items in/out of the current release, to/from `WORKITEMS-future.md`, or to/from `archive/` unprompted. Scope decisions are the maintainer's call — surface a concern, wait for the decision. The only edits you make without prompting are: checking off items you just completed, filing new bugs under the current release's *Open Bugs & Tweaks*, and updating bug status in place.

## Running the tests

Three suites, all should pass before you push:

```bash
# 1. Python unit + integration tests (server + worker + integration logic).
pytest tests/

# 2. Frontend build + typecheck.
cd ha-addon/ui && npm run build

# 3. Mocked Playwright end-to-end tests. Runs against a production
#    build of the UI with every API route stubbed — no backend required.
cd ha-addon/ui && npx playwright test
```

A handful of extras that CI runs — worth having locally if you're editing the touched areas:

- `ruff check ha-addon/server/ ha-addon/client/` — Python lint (zero warnings bar).
- `mypy ha-addon/server/ --ignore-missing-imports` / `mypy ha-addon/client/ --ignore-missing-imports` — type check.
- `bash scripts/check-invariants.sh` — grep-based enforcement of the architectural rules documented in `CLAUDE.md` → Enforced Invariants.

## End-of-turn / end-of-PR loop

The project uses a dev-rev versioning scheme to keep every push identifiable:

1. Make your code changes.
2. `bash scripts/bump-dev.sh` — increments `-dev.N` across `ha-addon/VERSION`, `ha-addon/config.yaml`, and `ha-addon/client/client.py` in one shot.
3. `./push-to-hass-4.sh` — optional for external contributors; maintainers use it to deploy to a local Home Assistant test instance and run the `e2e-hass-4` Playwright smoke suite.
4. Commit + push to your branch.

## Enforced invariants

Some rules are enforced mechanically by `scripts/check-invariants.sh` (runs in CI and blocks the merge). The full list lives in `CLAUDE.md` → Enforced Invariants; highlights:

- **UI-1** — No `fetch()` outside `ha-addon/ui/src/api/`. All HTTP goes through the api layer.
- **UI-2** — No Tailwind `@apply`. Utility classes in JSX; CSS files only for things Tailwind can't express.
- **UI-3** — No `any` in new TypeScript. Use `unknown` or a real type.
- **PY-6** — `ha-addon/server/protocol.py` and `ha-addon/client/protocol.py` must stay byte-identical.
- **PY-8** — Every direct dep in `requirements.txt` must appear in `requirements.lock`. Run `bash scripts/refresh-deps.sh` after any `requirements.txt` edit.
- **PY-10** — `tests/test_integration_*.py` (without a `_logic` suffix) must import `pytest_homeassistant_custom_component`.

If you trip one of these, CI will tell you which. The fix is always to comply with the invariant; don't add `# noqa` / `// eslint-disable` without a reason comment per **PY-5**.

## PR process

1. Open the PR against `develop`.
2. CI runs lint + tests + the mocked Playwright suite + the real-ESPHome compile-test matrix.
3. Address every review comment (Copilot bot and/or human reviewer) in the same push. Resolve each review thread after the fix lands — an unresolved thread looks like an open concern even after the code is fixed. See `CLAUDE.md` → PR Review Loop for the `gh api graphql` incantations.
4. For items you want to defer: file a work-item in the relevant `dev-plans/WORKITEMS-*.md`, reply to the review comment with a pointer, then resolve the thread.

## Where to ask

- Questions about **how** to do something → `CLAUDE.md` is the best single-file reference.
- Questions about **what** to do → `dev-plans/WORKITEMS-X.Y.md` for the current release, `dev-plans/USER_PERSONA.md` for scope/UX decisions.
- Anything else → open a GitHub issue.
