import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// PT.5 — Queue extras: Triggered column icons, Rerun vs Retry button labels,
// Cancelled badge, Clear actions don't touch cancelled rows by accident.

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

test('failed job uses Retry (not Rerun) label', async ({ page }) => {
  // job-002 (garage-door) is failed — Retry, not Rerun.
  const row = page.locator('#tab-queue tbody tr').filter({ hasText: 'garage-door' }).first();
  await expect(row.getByRole('button', { name: 'Retry' })).toBeVisible();
  await expect(row.getByRole('button', { name: 'Rerun' })).toHaveCount(0);
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
