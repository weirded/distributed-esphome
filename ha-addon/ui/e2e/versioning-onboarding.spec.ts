import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// #98 — first-login onboarding modal. Fires when
// ``versioning_enabled === 'unset'`` on the settings payload.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  // Override the default fixture (which ships ``'on'`` so the rest of
  // the suite stays green) to the unset state this spec cares about.
  // The mock handler in fixtures.ts merges PATCH updates into an
  // internal map, so a later PATCH from the modal flips us out of
  // 'unset'; we re-route here to keep the GET consistent until the
  // first PATCH lands.
  const settingsState = {
    versioning_enabled: 'unset',
    auto_commit_on_save: true,
    git_author_name: 'HA User',
    git_author_email: 'ha@distributed-esphome.local',
    job_history_retention_days: 365,
    firmware_cache_max_gb: 2.0,
    job_log_retention_days: 30,
    server_token: 'test-token-abc',
    job_timeout: 600,
    ota_timeout: 120,
    worker_offline_threshold: 30,
    device_poll_interval: 60,
    require_ha_auth: true,
    time_format: 'auto',
  } as Record<string, unknown>;
  await page.route('**/ui/api/settings', async (route) => {
    if (route.request().method() === 'PATCH') {
      const body = JSON.parse(route.request().postData() ?? '{}') as Record<string, unknown>;
      Object.assign(settingsState, body);
      return route.fulfill({ json: settingsState });
    }
    return route.fulfill({ json: settingsState });
  });
});

test('modal appears when versioning_enabled is unset', async ({ page }) => {
  await page.goto('/');

  const modal = page.getByRole('dialog').filter({ hasText: /Turn on config versioning/i });
  await expect(modal).toBeVisible();
  await expect(modal.getByRole('button', { name: /Leave off/i })).toBeVisible();
  await expect(modal.getByRole('button', { name: /Turn on versioning/i })).toBeVisible();
});

test('choosing "Turn on" patches versioning_enabled=on and closes', async ({ page }) => {
  const patches: Array<Record<string, unknown>> = [];
  await page.route('**/ui/api/settings', async (route) => {
    if (route.request().method() === 'PATCH') {
      const body = JSON.parse(route.request().postData() ?? '{}') as Record<string, unknown>;
      patches.push(body);
      return route.fulfill({
        json: {
          versioning_enabled: 'on',
          auto_commit_on_save: true,
          git_author_name: 'HA User',
          git_author_email: 'ha@distributed-esphome.local',
          server_token: 'test-token-abc',
          job_history_retention_days: 365,
          firmware_cache_max_gb: 2.0,
          job_log_retention_days: 30,
          job_timeout: 600,
          ota_timeout: 120,
          worker_offline_threshold: 30,
          device_poll_interval: 60,
          require_ha_auth: true,
          time_format: 'auto',
        },
      });
    }
    // GET — return unset until PATCH has happened; once it has,
    // return on. Simple heuristic: look at patches.
    return route.fulfill({
      json: {
        versioning_enabled: patches.length ? 'on' : 'unset',
        auto_commit_on_save: true,
        git_author_name: 'HA User',
        git_author_email: 'ha@distributed-esphome.local',
        server_token: 'test-token-abc',
        job_history_retention_days: 365,
        firmware_cache_max_gb: 2.0,
        job_log_retention_days: 30,
        job_timeout: 600,
        ota_timeout: 120,
        worker_offline_threshold: 30,
        device_poll_interval: 60,
        require_ha_auth: true,
        time_format: 'auto',
      },
    });
  });

  await page.goto('/');
  const modal = page.getByRole('dialog').filter({ hasText: /Turn on config versioning/i });
  await expect(modal).toBeVisible();

  await modal.getByRole('button', { name: /Turn on versioning/i }).click();

  await expect(modal).toBeHidden();
  await expect.poll(() => patches[0]).toEqual({ versioning_enabled: 'on' });
});

test('choosing "Leave off" patches versioning_enabled=off and closes', async ({ page }) => {
  const patches: Array<Record<string, unknown>> = [];
  await page.route('**/ui/api/settings', async (route) => {
    if (route.request().method() === 'PATCH') {
      const body = JSON.parse(route.request().postData() ?? '{}') as Record<string, unknown>;
      patches.push(body);
      return route.fulfill({
        json: {
          versioning_enabled: 'off',
          auto_commit_on_save: true,
          git_author_name: 'HA User',
          git_author_email: 'ha@distributed-esphome.local',
          server_token: 'test-token-abc',
          job_history_retention_days: 365,
          firmware_cache_max_gb: 2.0,
          job_log_retention_days: 30,
          job_timeout: 600,
          ota_timeout: 120,
          worker_offline_threshold: 30,
          device_poll_interval: 60,
          require_ha_auth: true,
          time_format: 'auto',
        },
      });
    }
    return route.fulfill({
      json: {
        versioning_enabled: patches.length ? 'off' : 'unset',
        auto_commit_on_save: true,
        git_author_name: 'HA User',
        git_author_email: 'ha@distributed-esphome.local',
        server_token: 'test-token-abc',
        job_history_retention_days: 365,
        firmware_cache_max_gb: 2.0,
        job_log_retention_days: 30,
        job_timeout: 600,
        ota_timeout: 120,
        worker_offline_threshold: 30,
        device_poll_interval: 60,
        require_ha_auth: true,
        time_format: 'auto',
      },
    });
  });

  await page.goto('/');
  const modal = page.getByRole('dialog').filter({ hasText: /Turn on config versioning/i });
  await expect(modal).toBeVisible();

  await modal.getByRole('button', { name: /Leave off/i }).click();

  await expect(modal).toBeHidden();
  await expect.poll(() => patches[0]).toEqual({ versioning_enabled: 'off' });
});

test('modal does NOT appear when versioning_enabled is already on', async ({ page }) => {
  // Default fixture ships ``'on'`` — spec doesn't override.
  await mockApi(page);
  await page.goto('/');
  // Give SWR a moment to fetch settings.
  await expect(page.getByText(/Living Room Sensor/i)).toBeVisible({ timeout: 5000 });

  const modal = page.getByRole('dialog').filter({ hasText: /Turn on config versioning/i });
  await expect(modal).not.toBeVisible();
});
