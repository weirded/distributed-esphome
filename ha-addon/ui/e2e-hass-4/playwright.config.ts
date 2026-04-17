import { defineConfig } from '@playwright/test';

/**
 * Playwright config for smoke tests against the author's hass-4 instance.
 *
 * Run with:
 *   npm run test:e2e:hass-4
 *
 * Defaults to http://192.168.225.112:8765. Override with:
 *   HASS4_URL=http://other-host:8765 npm run test:e2e:hass-4
 *
 * AU.7: when HASS4_ADDON_TOKEN is set (push-to-hass-4.sh reads it
 * from the hass-4 host and exports it), every test automatically
 * authenticates — both the `request` fixture (`extraHTTPHeaders`) and
 * the browser page (sessionStorage injected via `addInitScript` in
 * the global setup below, picked up by the UI's apiFetch helper).
 */
const hass4AddonToken = process.env.HASS4_ADDON_TOKEN || '';

export default defineConfig({
  testDir: '.',
  // Compile + OTA can take a while on real hardware
  timeout: 10 * 60_000,
  expect: { timeout: 30_000 },
  retries: 0,
  // Run serially — they touch real state, so don't parallelize
  workers: 1,
  fullyParallel: false,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: process.env.HASS4_URL || 'http://192.168.225.112:8765',
    headless: true,
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',
    // Real network may be slower than localhost
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
    // AU.7: /ui/api/* requires a Bearer on port 8765 since 1.5.0.
    // `extraHTTPHeaders` applies to the `request` fixture AND to every
    // fetch/XHR the browser page makes (including SWR polls) — both the
    // Playwright APIRequestContext and the BrowserContext pick it up.
    extraHTTPHeaders: hass4AddonToken
      ? { Authorization: `Bearer ${hass4AddonToken}` }
      : {},
  },
});
