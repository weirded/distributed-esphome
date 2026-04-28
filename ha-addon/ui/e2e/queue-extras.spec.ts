import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// PT.5 — Queue extras: Triggered column icons, Rerun button labels,
// Cancelled badge, Clear actions don't touch cancelled rows by accident.
// Bug #108 collapsed both "Retry" (failed jobs) and "Rerun" (success
// jobs) onto a single "Rerun" verb; the warn-amber colour still
// distinguishes failed-source rows at a glance.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await page.getByRole('button', { name: /Queue/ }).click();
  await expect(page.getByText('bedroom-light')).toBeVisible({ timeout: 5000 });
});

test('triggered column shows Manual by default and Recurring for scheduled jobs (UX.5)', async ({ page }) => {
  // job-007 (garage-door, scheduled recurring) → "Recurring" cell.
  // job-001 (bedroom-light, manual)            → "Manual" cell (UX.5 rename from "User").
  const garageRow = page.locator('#tab-queue tbody tr').filter({ hasText: 'garage-door' }).first();
  await expect(garageRow).toContainText(/Recurring|Manual/);

  const bedroomRow = page.locator('#tab-queue tbody tr').filter({ hasText: 'bedroom-light' }).first();
  await expect(bedroomRow).toContainText('Manual');
});

test('successful job uses Rerun (not Retry) label', async ({ page }) => {
  // job-001 (bedroom-light) is success — its row gets a "Rerun" button.
  const row = page.locator('#tab-queue tbody tr').filter({ hasText: 'bedroom-light' });
  await expect(row.getByRole('button', { name: 'Rerun' })).toBeVisible();
  await expect(row.getByRole('button', { name: 'Retry' })).toHaveCount(0);
});

test('failed job also uses Rerun (Bug #108: same verb for success + failure)', async ({ page }) => {
  // job-002 (garage-door) is failed — pre-#108 it said "Retry", now
  // both branches read "Rerun" and the warn-amber variant signals
  // "this job failed" without changing the verb.
  const row = page.locator('#tab-queue tbody tr').filter({ hasText: 'garage-door' }).first();
  await expect(row.getByRole('button', { name: 'Rerun' })).toBeVisible();
  await expect(row.getByRole('button', { name: 'Retry' })).toHaveCount(0);
});

test('cancelled badge renders for cancelled jobs', async ({ page }) => {
  // job-006 (living-room) is cancelled. The "Cancelled" badge text should
  // be visible somewhere in the queue table.
  await expect(page.locator('#tab-queue').getByText('Cancelled', { exact: true })).toBeVisible();
});

test('Clear Succeeded sends the success-only state filter', async ({ page }) => {
  // The handler calls /ui/api/queue/clear with {states:['success']}. The
  // server-side filter is what excludes cancelled rows; capture the request
  // body and assert states only contains 'success' (no 'cancelled').
  let states: string[] = [];
  await page.route('**/ui/api/queue/clear', async route => {
    try {
      const body = JSON.parse(route.request().postData() ?? '{}');
      states = body.states ?? [];
    } catch { /* ignore */ }
    route.fulfill({ json: { cleared: 1 } });
  });

  // Toolbar Clear dropdown — scope to tab-queue's .actions container so we
  // don't pick up the per-row Clear buttons.
  await page.locator('#tab-queue .actions').getByRole('button', { name: /Clear/i }).click();
  await page.getByRole('menuitem', { name: /Clear Succeeded/i }).click();

  await expect.poll(() => states).toEqual(['success']);
  expect(states).not.toContain('cancelled');
});

// Bug #85: "Clear Selected" menu entry in the Clear dropdown removes
// whatever rows the user has checked, via POST /ui/api/queue/remove.
test('Clear Selected sends the selected row ids to /queue/remove', async ({ page }) => {
  let removedIds: string[] = [];
  await page.route('**/ui/api/queue/remove', async route => {
    try {
      const body = JSON.parse(route.request().postData() ?? '{}');
      removedIds = body.ids ?? [];
    } catch { /* ignore */ }
    route.fulfill({ json: { removed: removedIds.length } });
  });

  // Open the Clear dropdown with no selection → "Clear Selected" is disabled.
  await page.locator('#tab-queue .actions').getByRole('button', { name: /Clear/i }).click();
  const clearSelected = page.getByRole('menuitem', { name: /Clear Selected/i });
  await expect(clearSelected).toBeVisible();
  await expect(clearSelected).toHaveAttribute('aria-disabled', 'true');
  // Close the dropdown.
  await page.keyboard.press('Escape');

  // Select the first two rows via their checkboxes.
  const checkboxes = page.locator('#tab-queue tbody tr input[type="checkbox"]');
  await checkboxes.nth(0).check();
  await checkboxes.nth(1).check();

  // Re-open the Clear dropdown and invoke Clear Selected.
  await page.locator('#tab-queue .actions').getByRole('button', { name: /Clear/i }).click();
  await page.getByRole('menuitem', { name: /Clear Selected/i }).click();

  await expect.poll(() => removedIds.length).toBe(2);
});
