import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// FD.3 + FD.8 + UX.8 — Compile-and-download flow end-to-end in the UI.
//
// Covers:
//   - UpgradeModal exposes a three-option Action radio: Upgrade Now |
//     Download Now | Schedule Upgrade (UX.8, replaces the earlier
//     nested Now/Scheduled + Compile-OTA/Compile-Download toggles).
//   - Selecting "Download Now" changes the confirm button to
//     "Compile & Download".
//   - Submitting with Download Now selected POSTs
//     {targets:[x], download_only: true} to /ui/api/compile.
//   - scheduleOnly mode (opened from Schedules-tab Edit) hides the
//     action radios entirely — download-only is not a scheduled action.
//   - Queue tab renders a Download button ONLY on rows that are
//     (success && download_only && has_firmware) — not on OTA rows.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
});

test('UpgradeModal exposes the three Action radios (UX.8)', async ({ page }) => {
  const row = page.locator('#tab-devices tbody tr').filter({ hasText: 'Living Room Sensor' });
  await row.getByRole('button', { name: 'Upgrade' }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('radio', { name: /Upgrade Now/ })).toBeVisible();
  await expect(dialog.getByRole('radio', { name: /Download Now/ })).toBeVisible();
  await expect(dialog.getByRole('radio', { name: /Schedule Upgrade/ })).toBeVisible();
  // Default action is Upgrade Now, so the confirm button reads "Upgrade".
  await expect(dialog.getByRole('button', { name: /^Upgrade$/ })).toBeVisible();
});

test('selecting Download Now swaps the confirm button label', async ({ page }) => {
  const row = page.locator('#tab-devices tbody tr').filter({ hasText: 'Living Room Sensor' });
  await row.getByRole('button', { name: 'Upgrade' }).click();

  const dialog = page.getByRole('dialog');
  await dialog.getByRole('radio', { name: /Download Now/ }).check();
  await expect(dialog.getByRole('button', { name: /^Compile & Download$/ })).toBeVisible();

  // Flipping back to Upgrade Now restores the original label.
  await dialog.getByRole('radio', { name: /Upgrade Now/ }).check();
  await expect(dialog.getByRole('button', { name: /^Upgrade$/ })).toBeVisible();
});

test('submitting Download Now POSTs download_only: true', async ({ page }) => {
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
  await dialog.getByRole('radio', { name: /Download Now/ }).check();
  await dialog.getByRole('button', { name: /^Compile & Download$/ }).click();

  await expect.poll(() => body?.download_only).toBe(true);
  expect(Array.isArray(body!.targets) && body!.targets[0]).toBe('living-room.yaml');
});

test('Schedules-tab Edit pre-selects Schedule Upgrade (UX.8)', async ({ page }) => {
  // Open from Schedules tab → Edit. All three Action radios are available
  // (per UX.8 design — user can flip to Upgrade Now if they want to run it
  // once instead of editing the schedule), but "Schedule Upgrade" is the
  // pre-selected default and the schedule sub-form is visible.
  await page.getByRole('button', { name: /Schedules/ }).click();
  const row = page.locator('#tab-schedules tbody tr').filter({ hasText: 'Garage Door' });
  await row.getByRole('button', { name: 'Edit' }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('heading', { name: /^Schedule Upgrade —/ })).toBeVisible();
  // Schedule Upgrade radio is pre-checked; the other two are present but not checked.
  await expect(dialog.getByRole('radio', { name: /Schedule Upgrade/ })).toBeChecked();
  await expect(dialog.getByRole('radio', { name: /Upgrade Now/ })).not.toBeChecked();
  await expect(dialog.getByRole('radio', { name: /Download Now/ })).not.toBeChecked();
});

test('Queue tab renders Download dropdown only on eligible rows', async ({ page }) => {
  await page.getByRole('button', { name: /Queue/ }).click();
  await expect(page.getByText('bedroom-light')).toBeVisible({ timeout: 5000 });

  // job-008 (office.yaml) is the only download-only+has_firmware fixture.
  const downloadRow = page.locator('#tab-queue tbody tr').filter({ hasText: 'office' });
  // #69: replaced the single `<a>Download</a>` with a shadcn DropdownMenu
  // trigger button (aria-label "Download firmware") that opens a menu of
  // variant × compression options.
  const dlTrigger = downloadRow.getByRole('button', { name: 'Download firmware' });
  await expect(dlTrigger).toBeVisible();
  await dlTrigger.click();

  // Each menu item is an <a download> with a variant-scoped href.
  // Legacy fixture (job-008) was pre-#69 so it surfaces as the single
  // "firmware" variant, yielding two menu items: raw + gzipped.
  const rawItem = page.getByRole('menuitem', { name: /Firmware.*\.bin\)$/ });
  const gzItem = page.getByRole('menuitem', { name: /Firmware.*\.bin\.gz\)$/ });
  await expect(rawItem).toBeVisible();
  await expect(gzItem).toBeVisible();
  await expect(rawItem).toHaveAttribute(
    'href', /\/ui\/api\/jobs\/job-008\/firmware\?variant=firmware$/,
  );
  await expect(gzItem).toHaveAttribute(
    'href', /\/ui\/api\/jobs\/job-008\/firmware\?variant=firmware&gz=1$/,
  );

  // Close the menu before asserting on the OTA row (Escape drops the
  // portal; leaving it open can occlude sibling rows).
  await page.keyboard.press('Escape');

  // Any other success row (e.g. bedroom-light job-001 OTA success) must NOT have a download button.
  const otaRow = page.locator('#tab-queue tbody tr').filter({ hasText: 'bedroom-light' });
  await expect(otaRow.getByRole('button', { name: 'Download firmware' })).toHaveCount(0);
});

test('Queue Download dropdown survives a SWR poll tick (#71)', async ({ page }) => {
  // Regression guard for #71 / #2-class bug: SWR polls the queue at 1 Hz,
  // which re-instantiates TanStack Table cells. Any DropdownMenu state
  // kept inside the cell would tear down mid-click and the menu would
  // vanish. The fix lifts `open` state to the QueueTab parent (see
  // CLAUDE.md Design Judgment → "Lift DropdownMenu open state out of
  // any row cell").
  await page.getByRole('button', { name: /Queue/ }).click();
  await expect(page.locator('#tab-queue tbody tr').first()).toBeVisible({ timeout: 5000 });

  const row = page.locator('#tab-queue tbody tr').filter({ hasText: 'office' });
  await row.getByRole('button', { name: 'Download firmware' }).click();

  const menuItem = page.getByRole('menuitem').first();
  await expect(menuItem).toBeVisible();

  // Wait long enough to cross at least two 1 Hz SWR poll ticks. The
  // menu must still be visible afterward.
  await page.waitForTimeout(2500);
  await expect(menuItem).toBeVisible();
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
