# hass-4 Smoke Tests

End-to-end smoke tests that run against the author's hass-4 instance
(`192.168.225.112`) and exercise the full compile + OTA path against a
real ESP device (`cyd-office-info`).

These are intentionally **separate** from the mocked Playwright tests
in `../e2e/`:

- The mocked tests in `../e2e/` run in CI on every push, with API
  responses stubbed via `page.route()`. They're fast and verify UI
  behavior in isolation.
- These hass-4 tests touch real state — they enqueue real compile jobs,
  flash real firmware, and tail real device logs. They are not run in
  CI. They run automatically at the end of `push-to-hass-4.sh` after a
  successful deploy.

## Running

```bash
cd ha-addon/ui

# defaults: HASS4_URL=http://192.168.225.112:8765, HASS4_TARGET=cyd-office-info.yaml
npm run test:e2e:hass-4

# override target device
HASS4_TARGET=living-room.yaml npm run test:e2e:hass-4

# override server URL (e.g. running locally on a different host)
HASS4_URL=http://192.168.1.42:8765 npm run test:e2e:hass-4

# headed mode (watch the browser)
npx playwright test --config=e2e-hass-4/playwright.config.ts --headed
```

## Configuration

| Env var            | Default                       | Description                                       |
|--------------------|-------------------------------|---------------------------------------------------|
| `HASS4_URL`        | `http://192.168.225.112:8765` | Base URL of the running add-on (NOT the HA Ingress URL — talk to the add-on directly) |
| `HASS4_TARGET`     | `cyd-office-info.yaml`        | Filename of the target ESPHome config             |
| `COMPILE_BUDGET_MS`| `480000` (8 minutes)          | Max time to wait for compile + OTA to complete    |
| `EXPECTED_VERSION` | contents of `ha-addon/VERSION`| Add-on version the suite expects on the server. The first test fails fast if `/ui/api/server-info` returns a different version, preventing accidental tests against a stale deploy. |

## Version safety check

Before any other test runs, the suite reads `ha-addon/VERSION` from the
working tree and asserts that the running add-on reports the same
version via `/ui/api/server-info`. This prevents accidentally testing
against a stale deploy after a `git pull`. If the deploy is out of
date, run `./push-to-hass-4.sh` first.

## Test Cases

The test file `cyd-office-info.spec.ts` runs four sequential cases:

1. **Devices tab loads** — header renders, version badge matches the
   expected version, target device row is visible.
2. **Schedule upgrade** — snapshot the latest job ID via `/ui/api/queue`,
   click the row's Upgrade button, poll the API until a new job ID
   appears, then confirm the queue row is visible in the UI.
3. **Compile + log tail** — open the log modal, verify lines stream
   into the xterm terminal, then poll `/ui/api/queue` for the specific
   job ID until it reaches a terminal state. Asserts the final state
   is `success` with `ota_result=success`.
4. **Live device logs** — open the row's hamburger menu, click Live
   Logs, verify the device API streams output into the modal.

Tests run **serially** (`workers: 1`, `fullyParallel: false`) because
they share global state on the real server.

## Why not use HA Ingress?

The add-on exposes port 8765 directly to the host network in addition
to being available through HA Ingress. The `/ui/api/*` endpoints don't
require authentication when accessed directly (this is documented in
`dev-plans/SECURITY_AUDIT.md` finding F-03).

For these smoke tests, talking to the add-on port directly is the
simplest approach: no HA login flow, no Ingress path discovery, no
token juggling. If you want to test the Ingress path itself, you'd
need to set up HA long-lived access tokens and navigate through the
HA frontend.
