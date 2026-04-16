import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// FD.3 + FD.8 — Compile-and-download flow end-to-end in the UI.
//
// Covers:
//   - UpgradeModal "Now" mode shows a "Compile + OTA" vs
//     "Compile + Download" sub-toggle.
//   - Selecting "Compile + Download" changes the confirm button label
//     to "Compile & Download".
//   - Submitting with that mode selected POSTs
//     {targets:[x], download_only: true} to /ui/api/compile.
//   - Scheduled mode does NOT show the sub-toggle (download-only is
//     Now-only in 1.4.1).
//   - Queue tab renders a Download button ONLY on rows that are
//     (success && download_only && has_firmware) — not on OTA rows.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
});

test('UpgradeModal shows Compile + OTA/Download toggle in Now mode', async ({ page }) => {
  const row = page.locator('#tab-devices tbody tr').filter({ hasText: 'Living Room Sensor' });
  await row.getByRole('button', { name: 'Upgrade' }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  // The sub-toggle sits below the main Now/Scheduled radio.
  await expect(dialog.getByLabel('Compile + OTA', { exact: true })).toBeVisible();
  await expect(dialog.getByLabel('Compile + Download (no OTA)', { exact: true })).toBeVisible();
  // Default is OTA, so the confirm button reads "Upgrade".
  await expect(dialog.getByRole('button', { name: /^Upgrade$/ })).toBeVisible();
});

test('selecting Compile + Download swaps the confirm button label', async ({ page }) => {
  const row = page.locator('#tab-devices tbody tr').filter({ hasText: 'Living Room Sensor' });
  await row.getByRole('button', { name: 'Upgrade' }).click();

  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Compile + Download (no OTA)', { exact: true }).check();
  await expect(dialog.getByRole('button', { name: /^Compile & Download$/ })).toBeVisible();

  // Flipping back to OTA restores the original label.
  await dialog.getByLabel('Compile + OTA', { exact: true }).check();
  await expect(dialog.getByRole('button', { name: /^Upgrade$/ })).toBeVisible();
});

test('submitting Compile + Download POSTs download_only: true', async ({ page }) => {
  let body: { targets?: string[] | string; download_only?: boolean } | null = null;
  await page.route('**/ui/api/compile', async route => {
    try {
      body = JSON.parse(route.request().postData() ?? '{}');
    } catch { /* ignore */ }
    route.fulfill({ json: { enqueued: 1 } });
  });

  const row = page.locator('#tab-devices tbody tr').filter({ hasText: 'Living Room Sensor' });
  await row.getByRole('button', { name: 'Upgrade' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Compile + Download (no OTA)', { exact: true }).check();
  await dialog.getByRole('button', { name: /^Compile & Download$/ }).click();

  await expect.poll(() => body?.download_only).toBe(true);
  expect(Array.isArray(body!.targets) && body!.targets[0]).toBe('living-room.yaml');
});

test('scheduled mode hides the OTA/Download sub-toggle', async ({ page }) => {
  // Open from Schedules tab → Edit so the modal opens in Scheduled mode.
  await page.getByRole('button', { name: /Schedules/ }).click();
  const row = page.locator('#tab-schedules tbody tr').filter({ hasText: 'Garage Door' });
  await row.getByRole('button', { name: 'Edit' }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  // The radios from the FD.3 sub-toggle should NOT exist here.
  await expect(dialog.getByLabel('Compile + OTA', { exact: true })).toHaveCount(0);
  await expect(dialog.getByLabel('Compile + Download (no OTA)', { exact: true })).toHaveCount(0);
});

test('Queue tab renders Download button only on eligible rows', async ({ page }) => {
  await page.getByRole('button', { name: /Queue/ }).click();
  await expect(page.getByText('bedroom-light')).toBeVisible({ timeout: 5000 });

  // job-008 (office.yaml) is the only download-only+has_firmware fixture.
  const downloadRow = page.locator('#tab-queue tbody tr').filter({ hasText: 'office' });
  // #68: relabeled "Download" → "Download .bin" to disambiguate from log-download buttons.
  const dlAnchor = downloadRow.getByRole('link', { name: 'Download .bin' });
  await expect(dlAnchor).toBeVisible();
  await expect(dlAnchor).toHaveAttribute('href', /\/ui\/api\/jobs\/job-008\/firmware$/);
  await expect(dlAnchor).toHaveAttribute('download', '');

  // Any other success row (e.g. bedroom-light job-001 OTA success) must NOT have the .bin download.
  const otaRow = page.locator('#tab-queue tbody tr').filter({ hasText: 'bedroom-light' });
  await expect(otaRow.getByRole('link', { name: 'Download .bin' })).toHaveCount(0);
});

test('download-only success row shows Ready badge, not OTA Pending (#23)', async ({ page }) => {
  await page.getByRole('button', { name: /Queue/ }).click();
  await expect(page.getByText('bedroom-light')).toBeVisible({ timeout: 5000 });
  const downloadRow = page.locator('#tab-queue tbody tr').filter({ hasText: 'office' });
  // Pre-fix this row showed "OTA Pending" because ota_result is null for
  // download-only jobs. Post-#23 it reads "Ready".
  await expect(downloadRow.getByText('Ready', { exact: true })).toBeVisible();
  await expect(downloadRow.getByText('OTA Pending', { exact: true })).toHaveCount(0);
});

test('download-only terminal row exposes Clear + Rerun (was blocked pre-#23)', async ({ page }) => {
  await page.getByRole('button', { name: /Queue/ }).click();
  // Scope by data-job attribute so we don't accidentally match the
  // Office Sensor Devices-tab row or any other "office" string.
  const downloadRow = page.locator('#tab-queue tbody tr[data-job="job-008"]');
  await expect(downloadRow).toHaveCount(1);
  // Pre-#23 isJobFinished returned false for download-only-success because
  // ota_result !== 'success' → neither Clear nor Rerun rendered. Post-fix
  // both are present.
  await expect(downloadRow.getByRole('button', { name: 'Clear' })).toBeVisible();
  await expect(downloadRow.getByRole('button', { name: 'Rerun' })).toBeVisible();
});
