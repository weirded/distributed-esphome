import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// PT.2 — UpgradeModal in its scheduling guise.
//
// The modal is the unified version-pinning + scheduling dialog. It opens in
// "Now" mode by default for the per-row Upgrade button, and in "Scheduled"
// mode when triggered from the Schedules-tab Edit button (defaultMode prop).

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
});

test('per-row Upgrade button opens modal in Now mode', async ({ page }) => {
  const row = page.locator('#tab-devices tbody tr').filter({ hasText: 'Living Room Sensor' });
  await row.getByRole('button', { name: 'Upgrade' }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  // Title in Now mode is "Upgrade — <name>"; Scheduled mode is
  // "Schedule Upgrade — <name>". Asserting on the leading word disambiguates.
  await expect(dialog.getByRole('heading', { name: /^Upgrade —/ })).toBeVisible();
  // Now-mode confirm button is labelled "Upgrade".
  await expect(dialog.getByRole('button', { name: /^Upgrade$/ })).toBeVisible();
});

test('Schedules-tab Edit opens modal in Scheduled mode (#79)', async ({ page }) => {
  await page.getByRole('button', { name: /Schedules/ }).click();
  await page.locator('#tab-schedules tbody tr').filter({ hasText: 'Garage Door' })
    .getByRole('button', { name: 'Edit' }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  // #79: Garage Door fixture has a recurring cron → modal opens with
  // "Schedule Recurring" selected and the heading reflects that.
  await expect(dialog.getByRole('heading', { name: /^Schedule Recurring Upgrade —/ })).toBeVisible();
  await expect(dialog.getByRole('button', { name: /Save Schedule/ })).toBeVisible();
});

test('switching action changes title and confirm-button label (#79)', async ({ page }) => {
  const row = page.locator('#tab-devices tbody tr').filter({ hasText: 'Living Room Sensor' });
  await row.getByRole('button', { name: 'Upgrade' }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: /^Upgrade —/ })).toBeVisible();

  // Flip to Schedule Recurring.
  await dialog.getByRole('radio', { name: /Schedule Recurring/ }).check();
  await expect(dialog.getByRole('heading', { name: /^Schedule Recurring Upgrade —/ })).toBeVisible();
  await expect(dialog.getByRole('button', { name: /Save Schedule/ })).toBeVisible();

  // Flip to Schedule Once — the heading is "Schedule Upgrade — …"
  // (deliberately dropping "Recurring"), the button stays "Save Schedule".
  await dialog.getByRole('radio', { name: /Schedule Once/ }).check();
  await expect(dialog.getByRole('heading', { name: /^Schedule Upgrade —/ })).toBeVisible();
  await expect(dialog.getByRole('button', { name: /Save Schedule/ })).toBeVisible();

  // Back to Upgrade Now — default label restored.
  await dialog.getByRole('radio', { name: /Upgrade Now/ }).check();
  await expect(dialog.getByRole('heading', { name: /^Upgrade —/ })).toBeVisible();
  await expect(dialog.getByRole('button', { name: /^Upgrade$/ })).toBeVisible();
});

test('saving a recurring schedule fires POST /schedule with cron + tz', async ({ page }) => {
  let payload: { cron?: string; tz?: string; target?: string } = {};
  await page.route('**/ui/api/targets/*/schedule', route => {
    if (route.request().method() === 'POST') {
      const url = route.request().url();
      const target = decodeURIComponent(url.split('/targets/')[1].split('/')[0]);
      try {
        const body = JSON.parse(route.request().postData() ?? '{}');
        payload = { ...body, target };
      } catch { /* ignore */ }
    }
    route.fulfill({ json: { schedule_enabled: true } });
  });

  const row = page.locator('#tab-devices tbody tr').filter({ hasText: 'Living Room Sensor' });
  await row.getByRole('button', { name: 'Upgrade' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('radio', { name: /Schedule Recurring/ }).check();
  // Default cadence in friendly mode is "Every 1 day(s) at 02:00" → cron 0 2 * * *
  await dialog.getByRole('button', { name: /Save Schedule/ }).click();

  await expect.poll(() => payload.target).toBe('living-room.yaml');
  expect(payload.cron).toMatch(/^\d+ \d+ \* \* \*$/);
  expect(payload.tz).toBeTruthy();
});

test('saving a one-time schedule fires POST /schedule/once (#79)', async ({ page }) => {
  let payload: { datetime?: string; target?: string } = {};
  await page.route('**/ui/api/targets/*/schedule/once', route => {
    if (route.request().method() === 'POST') {
      const url = route.request().url();
      const target = decodeURIComponent(url.split('/targets/')[1].split('/')[0]);
      try {
        const body = JSON.parse(route.request().postData() ?? '{}');
        payload = { ...body, target };
      } catch { /* ignore */ }
    }
    route.fulfill({ status: 200, json: {} });
  });

  const row = page.locator('#tab-devices tbody tr').filter({ hasText: 'Living Room Sensor' });
  await row.getByRole('button', { name: 'Upgrade' }).click();
  const dialog = page.getByRole('dialog');
  // #79: "Schedule Once" is now a top-level Action radio — no more
  // nested Recurring/Once sub-toggle inside the schedule form.
  await dialog.getByRole('radio', { name: /Schedule Once/ }).check();
  // Default onceDate seeds to "now" → already valid; just confirm.
  await dialog.getByRole('button', { name: /Save Schedule/ }).click();

  await expect.poll(() => payload.target).toBe('living-room.yaml');
  expect(payload.datetime).toBeTruthy();
});

test('Remove existing schedule fires DELETE /schedule', async ({ page }) => {
  let deletedFor: string | null = null;
  await page.route('**/ui/api/targets/*/schedule', route => {
    if (route.request().method() === 'DELETE') {
      const url = route.request().url();
      deletedFor = decodeURIComponent(url.split('/targets/')[1].split('/')[0]);
    }
    route.fulfill({ status: 200, json: {} });
  });

  // Open the modal on garage-door (which already has a recurring schedule
  // in fixtures), via the Schedules tab Edit button.
  await page.getByRole('button', { name: /Schedules/ }).click();
  await page.locator('#tab-schedules tbody tr').filter({ hasText: 'Garage Door' })
    .getByRole('button', { name: 'Edit' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: /Remove existing schedule/ }).click();

  await expect.poll(() => deletedFor).toBe('garage-door.yaml');
});
