# home-assistant/brands submission

Staged artwork for the PR to [`home-assistant/brands`](https://github.com/home-assistant/brands) that registers ESPHome Fleet with HA's Integrations UI. Files here are laid out the way that repo expects them — copy the whole `custom_integrations/esphome_fleet/` directory into the equivalent path of a `home-assistant/brands` fork, open a PR, link back to this repo.

## Files

| Path | Size | Purpose |
|---|---|---|
| `custom_integrations/esphome_fleet/icon.png` | 256×256 | 1× integration icon |
| `custom_integrations/esphome_fleet/icon@2x.png` | 512×512 | 2× retina icon |
| `custom_integrations/esphome_fleet/logo.png` | 500×200 | 1× landscape wordmark |
| `custom_integrations/esphome_fleet/logo@2x.png` | 1000×400 | 2× retina wordmark |

All four are rendered from `ha-addon/ui/src/assets/esphome-logo.svg` + a Helvetica/Helvetica-Bold "ESPHome Fleet" wordmark via the ImageMagick one-liners documented at the bottom of `dev-plans/RELEASE_CHECKLIST.md`. Regenerate them from the SVG rather than editing the PNGs directly — that keeps the add-on's own `ha-addon/icon.png` / `ha-addon/logo.png` and the integration's `ha-addon/custom_integration/esphome_fleet/icon.png` / `logo.png` on one consistent source of truth.

## Status

Files are staged here but the `home-assistant/brands` PR has **not** been filed yet — tracked as **PR.5** in `dev-plans/WORKITEMS-1.6.1.md`. Until the PR is merged, HA's Integrations page renders the integration as a generic placeholder. The integration-local copies under `ha-addon/custom_integration/esphome_fleet/{icon,logo}.png` carry the wordmark in the interim.
