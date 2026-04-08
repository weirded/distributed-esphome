# Release Checklist

Use this checklist when preparing a stable release from `develop` → `main`.
Copy the checklist into a GitHub issue or scratch file and check items off as you go.

---

## Pre-release (on `develop`)

### Claude can do

- [ ] Run full test suite, fix any failures: `pytest tests/`
- [ ] Run mypy on server and client:
  ```
  mypy ha-addon/server/ --ignore-missing-imports
  mypy ha-addon/client/ --ignore-missing-imports
  ```
- [ ] Build the frontend, fix any errors: `cd ha-addon/ui && npm run build`
- [ ] Bump version: `bash scripts/bump-version.sh X.Y.Z`
- [ ] Write changelog entry in `ha-addon/CHANGELOG.md`:
  - Add `## X.Y.Z` section
  - Source material: `dev-plans/WORKITEMS-X.Y.md` — has both completed work items and the bug fixes for the release
  - Group by category (features, improvements, bug fixes)
  - Consolidate dev-iteration noise into clean user-facing descriptions
- [ ] Update `README.md` — ensure feature list, config tables, and architecture match current state
- [ ] Update `ha-addon/DOCS.md` — ensure HA add-on panel docs match current features and options
- [ ] Audit both docs for stale content — remove outdated diagrams, references to removed features, and anything that duplicates what the code already says
- [ ] Update `ha-addon/config.yaml` — verify `description`, `map`, `ports`, `options`, `schema` reflect any new config
- [ ] Review `dev-plans/WORKITEMS-X.Y.md` — mark completed items, move any deferred items to the next release file
- [ ] Grep for TODO/FIXME/HACK in changed files — resolve or document as known issues

- [ ] Playwright smoke test against hass-4 (after deploy):
  - [ ] All three tabs load with data
  - [ ] Device search/filter works
  - [ ] Column picker opens, toggles columns
  - [ ] Queue tab shows jobs, badges render
  - [ ] Workers tab shows workers with status dots
  - [ ] Editor modal opens, Monaco renders
  - [ ] Log modal opens, xterm renders
  - [ ] Dark/light theme toggle switches correctly
  - [ ] No console errors on any tab

### You need to do

- [ ] Deploy to hass-4 for smoke test: `./push-to-hass-4.sh`
- [ ] Read the changelog draft — does it accurately represent what users care about?
- [ ] Manual smoke test (things Playwright can't verify):
  - [ ] Compile a device end-to-end, watch log stream, OTA succeeds
  - [ ] Live device logs connect to a real device
  - [ ] Editor autocomplete triggers on real config
- [ ] Check for any unreleased config changes that need migration notes
- [ ] Decide: are all `develop` commits release-worthy, or cherry-pick?

---

## Release (merge to `main`)

### Claude can do

- [ ] Create release branch if needed: `git checkout -b release/X.Y.Z develop`
- [ ] Final commit with version + changelog + docs on `develop` (or release branch)
- [ ] Verify pre-push hook passes: tests, mypy, changelog entry present
- [ ] Merge to main: `git checkout main && git merge develop` (or merge release branch)
- [ ] Push to main: `git push origin main`
  - Pre-push hook runs automatically (tests + mypy + changelog check)
  - GHCR images build automatically on push to main
- [ ] Tag the release: `git tag vX.Y.Z && git push origin vX.Y.Z`
- [ ] Verify GitHub Actions pass: `gh run list --branch main --limit 3`
- [ ] Verify GHCR images published: `gh api /orgs/{owner}/packages/container/{name}/versions --jq '.[0]'`

---

## Post-release

### Claude can do

- [ ] Start next dev cycle on `develop`:
  ```
  git checkout develop
  bash scripts/bump-dev.sh
  ```
- [ ] Create the next release file: `dev-plans/WORKITEMS-X.Y+1.md` (copy structure from previous file, leave items unchecked)

### You need to do

- [ ] Update HA add-on repo (if using a separate repo for distribution)
- [ ] Verify the add-on updates cleanly on hass-4 from the published image
- [ ] Post release notes if desired (GitHub release, Reddit, Discord)

---

## Version files kept in sync by `scripts/bump-version.sh`

| File | Field |
|------|-------|
| `ha-addon/VERSION` | Entire file content |
| `ha-addon/config.yaml` | `version:` field |
| `ha-addon/client/client.py` | `CLIENT_VERSION` constant |

## Pre-push hook (`.githooks/pre-push`)

Runs automatically on push:
- `pytest tests/` (excluding e2e)
- `mypy` on server + client
- On `main` branch only: verifies `CHANGELOG.md` has a `## X.Y.Z` entry matching VERSION
