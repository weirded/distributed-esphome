import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

// AV.6: History panel opens from the Devices row hamburger and from
// the Editor modal toolbar.

test('hamburger "Config history…" opens the History panel', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  // Open the hamburger on the first row.
  const firstRow = page.getByRole('row').filter({ hasText: 'Living Room Sensor' });
  await firstRow.getByRole('button', { name: /more actions/i }).click();

  await page.getByRole('menuitem', { name: /config history/i }).click();

  // Drawer opened — title shows the filename.
  const drawer = page.locator('[data-slot="sheet-content"]');
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('heading', { name: /living-room\.yaml/ })).toBeVisible();

  // Commit list populated from the mock. Short-hash labels on the
  // rows are unambiguous (only in the commit list, not in the
  // `<select>` options which aren't currently rendered visibly).
  await expect(drawer.getByText('fedcba9', { exact: true }).first()).toBeVisible();
  await expect(drawer.getByText('0123456', { exact: true }).first()).toBeVisible();
});

test('Restore button on a commit triggers a rollback', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  const firstRow = page.getByRole('row').filter({ hasText: 'Living Room Sensor' });
  await firstRow.getByRole('button', { name: /more actions/i }).click();
  await page.getByRole('menuitem', { name: /config history/i }).click();

  const drawer = page.locator('[data-slot="sheet-content"]');
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText('fedcba9', { exact: true }).first()).toBeVisible();

  // Bug 15: Restore opens a proper shadcn Dialog, not window.confirm.
  // Click the row-level Restore button, then confirm in the dialog.
  await drawer.getByRole('button', { name: /^Restore$/ }).first().click();
  const confirmDialog = page.getByRole('dialog').filter({ hasText: /Restore fedcba9/ });
  await expect(confirmDialog).toBeVisible();
  await confirmDialog.getByRole('button', { name: /^Restore this version$/ }).click();
  await expect(page.getByText(/Restored cafeba5/)).toBeVisible({ timeout: 5000 });
});

test('uncommitted banner shows the Commit prompt when the status endpoint says so', async ({ page }) => {
  // Override the default mock to report dirty state for this test.
  await page.route('**/ui/api/files/*/status', route => {
    route.fulfill({
      json: {
        has_uncommitted_changes: true,
        head_hash: 'fedcba9876543210fedcba9876543210fedcba98',
        head_short_hash: 'fedcba9',
      },
    });
  });

  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  const firstRow = page.getByRole('row').filter({ hasText: 'Living Room Sensor' });
  await firstRow.getByRole('button', { name: /more actions/i }).click();
  await page.getByRole('menuitem', { name: /config history/i }).click();

  const drawer = page.locator('[data-slot="sheet-content"]');
  await expect(drawer.getByText(/uncommitted changes/i)).toBeVisible();

  // Click Commit… to reveal the message field.
  await drawer.getByRole('button', { name: /^Commit…$/ }).click();

  const commitRequest = page.waitForRequest(req =>
    req.url().includes('/commit') && req.method() === 'POST',
  );
  await drawer.getByRole('button', { name: /^Commit$/ }).click();
  await commitRequest;
  await expect(page.getByText(/Committed/)).toBeVisible();
});
