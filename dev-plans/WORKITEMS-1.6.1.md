# Work Items — 1.6.1

Theme: **Home Assistant gold-standard polish.** Lift the add-on toward the highest practical Supervisor security score (AppArmor profile, declared `signed`, digest-pinned bases) and the bundled integration from `bronze` to `gold` on the HA Integration Quality Scale (diagnostics, repairs, system health, reauth/reconfigure flows, ≥95% test coverage). Plus the surface polish reviewers notice first — proper icon/logo sizes, multi-language translations, service-action docs, repo hygiene files.

Background: there is no single "Gold" tier for add-ons in the HA ecosystem — the operational definition for this release is **add-on security stars (max practical) + integration Quality Scale Gold + presentation/repo polish**. Today the security posture is already strong (cosign signatures, SBOM attestations, hash-pinned deps, full `SECURITY.md` threat model); the gap is in declarative surfaces (AppArmor, `signed: true`) and the integration's Gold-tier rules (currently `quality_scale: bronze`).

Some current `config.yaml` flags (`host_network: true`, `hassio_api: true`, `homeassistant_api: true`, `auth_api: true`) are deliberate trade-offs — not gaps to close. Each gets a one-paragraph justification in `DOCS.md` so the lower star count has a written rationale users can read.

## Security score (Supervisor stars)

- [ ] **SS.1 AppArmor profile** — create `ha-addon/apparmor.txt` and add `apparmor: true` to `config.yaml`. Profile must allow: `python3` exec, `/data` rw, `/config/esphome` rw (writes from AV.* auto-commit), `git` exec, `pip install` writes under `/data/esphome-versions/<ver>/`, network egress to PyPI + Supervisor, mDNS sockets (UDP 5353). Iterate against `aa-status` inside the container and the Supervisor add-on log until clean. Stop running unconfined.
- [ ] **SS.2 `signed: true`** — declare in `config.yaml`. Images are already cosign-signed by `publish-server.yml` and `publish-client.yml` via keyless OIDC; this just surfaces the signature in the Supervisor UI badge.
- [ ] **SS.3 Documented privilege exceptions** — new `DOCS.md` subsection "Why this add-on requests these permissions" covering each non-default flag (`host_network`, `hassio_api`, `homeassistant_api`, `auth_api`, `config:rw` map) with a one-line "what we use it for" so the lower star count is justified rather than mysterious.
- [ ] **SS.4 Base image digest pinning** *(closes CF.3, carried from 1.3.1)* — pin both `ha-addon/build.yaml`'s `build_from` map and the worker `ha-addon/client/Dockerfile` `FROM` to `@sha256:...` digests. Refresh on every release after verifying the new digest's CVE bulletin (PY-4 already triggers when the worker base changes; extend the invariant comment to cover the digest refresh).

## Integration: Bronze → Gold

Today `ha-addon/custom_integration/esphome_fleet/manifest.json` declares `"quality_scale": "bronze"`. Gold has 24 rules. The flip to `"gold"` happens in QS.9 only after the others land.

- [ ] **QS.1 Diagnostics support** — new `ha-addon/custom_integration/esphome_fleet/diagnostics.py` exposing `async_get_config_entry_diagnostics`. Returns a redacted dump of coordinator state (workers, queue, devices, settings) using `homeassistant.components.diagnostics.async_redact_data` to scrub the server token. Test: `tests/test_integration_diagnostics.py`.
- [ ] **QS.2 Repairs** — new `repairs.py` seeding three repair issues: (a) `add_on_offline` (server unreachable >N coordinator cycles), (b) `worker_image_stale` (any registered worker is below `MIN_IMAGE_VERSION`), (c) `token_invalid` (401s persist past one cycle). Each gets a translation key in `strings.json`. Use `ir.async_create_issue` / `ir.async_delete_issue` so resolved issues clear themselves on the next coordinator update.
- [ ] **QS.3 System health** — new `system_health.py` surfacing server reachability, ESPHome version, worker count, queue depth in HA's System Health dashboard.
- [ ] **QS.4 Reauthentication flow** — wire `async_step_reauth` in `config_flow.py`. SP.8's token rotation is a real concern now; without reauth, rotating the token via the Settings drawer requires deleting + re-adding the integration. Translation strings + a test under `tests/test_integration_config_flow.py`.
- [ ] **QS.5 Reconfiguration flow** — `async_step_reconfigure` in `config_flow.py` so users can edit server URL / token via the integration's "Configure" button instead of removing and re-creating.
- [ ] **QS.6 Stale-device cleanup** — coordinator's `_async_update_data` should remove devices that have disappeared from the server's targets list. Today they linger forever in the device registry. One DR (device registry) query, one `dr.async_remove_device` per stale entry.
- [ ] **QS.7 Translatable exception messages** — replace any `raise ValueError("...")` / raw-string exceptions in service handlers and the coordinator with `raise HomeAssistantError(translation_domain=DOMAIN, translation_key=...)`. Add the keys to `strings.json` + `translations/en.json`.
- [ ] **QS.8 Test coverage to ≥95%** — depends on **IT.1 / IT.2 / IT.3** in `WORKITEMS-1.6.md` (the Integration Test Refactor that switches from `SimpleNamespace` mocks to a real `pytest_homeassistant_custom_component` `hass` fixture). Without IT.*, the "≥95% coverage" claim is honest but the *quality* of the coverage isn't Gold-grade. Treat IT.* as a precondition — surface them here as a dependency rather than re-listing.
- [ ] **QS.9 Flip `quality_scale` to `gold`** — manifest edit, **last** in the workstream. Only after QS.1–QS.8 land and the upstream rules checker (run `python3 -m script.hassfest --action validate` against the integration if reachable, or the equivalent `homeassistant.scripts.check_config` flow) accepts the manifest claiming `gold`. CI invariant: add a hassfest-run step to the test job so a manifest claiming `gold` fails CI if any rule regresses later.

## Presentation polish

- [ ] **PR.1 Icon at 128×128** — current `ha-addon/icon.png` is 64×64 (half the convention). Re-render at 128×128 PNG. Add an SVG sibling `ha-addon/icon.svg` since the source vector exists at `ha-addon/ui/src/assets/esphome-logo.svg`.
- [ ] **PR.2 Logo at landscape ratio** — current `ha-addon/logo.png` is 192×192 square. HA convention is ~250×100 horizontal. Re-export the wordmark + glyph as a horizontal lockup so it fits the Add-on Store header banner without awkward letterboxing.
- [ ] **PR.3 Service-action documentation** — `ha-addon/custom_integration/esphome_fleet/services.yaml` currently has bare service entries. Add `name:` + `description:` per service AND per parameter for `compile`, `cancel`, `validate`. HA's Developer Tools → Actions page surfaces these directly; today users see an empty UI.
- [ ] **PR.4 Add-on translations beyond `en`** — at minimum `de.yaml` / `es.yaml` / `fr.yaml` under `ha-addon/translations/`, mirroring `en.yaml`. Same for the integration's `translations/` directory. Auto-translate as the seed and accept community PRs to refine. Lower priority than PR.1–PR.3; can slip to a future release if scope is tight.
- [ ] **PR.5 Submit integration branding to `home-assistant/brands`** *(follow-up from 1.6 #58)* — HA's Integrations UI fetches logos from `brands.home-assistant.io/<domain>/*.png`, which requires a PR to [`home-assistant/brands`](https://github.com/home-assistant/brands). Deliverables: `custom_integrations/esphome_fleet/{icon,logo}.png` at 256×256, plus `icon@2x.png` / `logo@2x.png` at 512×512. Source art lives in `ha-addon/ui/src/assets/esphome-logo.svg`; re-export the sizes and open the PR. Today the integration shows as a generic placeholder on the HA Integrations page; this lands the proper ESPHome-Fleet wordmark there. PR.1 + PR.2 should land first so the add-on store and the integration both use the same refreshed artwork.

## Repository hygiene

- [ ] **RH.1 `LICENSE` file at repo root** — `README.md` mentions MIT but there is no `LICENSE.txt`/`LICENSE`. Required by many automated scanners and by GitHub's own license-detection (currently shows "No license"). One file, MIT text, copyright `2024–2026 Stefan Zier`.
- [ ] **RH.2 `CONTRIBUTING.md`** — short doc covering: how to run the test suite (`pytest tests/` + `cd ha-addon/ui && npm run test:e2e`), the `bump-dev.sh` end-of-turn loop, the WORKITEMS bug-numbering convention, the PY/UI/E2E enforced invariants, and a pointer to `CLAUDE.md` for the deeper conventions.
- [ ] **RH.3 `.github/CODEOWNERS`** — single line `* @weirded` (or scoped per directory if more contributors land later). Stops accidental drift if a future contributor opens a PR without explicit reviewer assignment.
- [ ] **RH.4 Optional `ARCHITECTURE.md`** — short outside-reader summary of server/worker tiers + auth model, with a pointer to `CLAUDE.md` for the deep version. The existing `CLAUDE.md` is excellent but framed as Claude-developer guidance, not project-architecture intro. Stretch goal — skip if time is tight.

## Open Bugs & Tweaks

### Carried forward from 1.6

- [ ] **#111** *(carried from 1.6 — formerly #104 before 1.6 reused that slot)* — when config versioning is disabled, we should gray out the config history item in the hamburger menu. As well as any other places that lead us to the history drawer, like the history button in the editor and the various hashes that we show in the queue and job history table.

- [ ] **#112** *(carried from 1.6 — formerly #105 before 1.6 reused that slot)* — when config versioning is disabled, if we don't have the history enabled, we probably need to not show the hashes and hide those columns.

### New in 1.6.1

(populated as new bugs are found during the 1.6.1 cycle)
