import { defineConfig } from '@playwright/test';

/**
 * Playwright config for smoke tests against the author's hass-4 instance.
 *
 * Run with:
 *   npm run test:e2e:hass-4
 *
 * Defaults to http://192.168.225.112:8765. Override with:
 *   HASS4_URL=http://other-host:8765 npm run test:e2e:hass-4
 */
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
  },
});
