# Work Items — 1.6.0

Theme: **LLM-powered assistance.** Use LLMs to help write ESPHome YAML and to proactively surface breaking changes in new ESPHome releases against the user's actual device fleet.

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
