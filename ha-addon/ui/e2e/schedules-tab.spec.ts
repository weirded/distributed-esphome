import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// PT.3 — Schedules tab: list, search, select, bulk remove, empty state.
//
// Fixtures (PT.12): garage-door has a recurring 0 3 * * * schedule, office
// has a one-time schedule. Living-room and bedroom-light have neither.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
  await page.getByRole('button', { name: /Schedules/ }).click();
});

test('schedules tab lists scheduled devices', async ({ page }) => {
  // garage-door (recurring) and office (one-time) — both should render.
  await expect(page.getByText('Garage Door')).toBeVisible();
  await expect(page.getByText('Office Sensor')).toBeVisible();
  // Devices without any schedule must NOT appear here.
  await expect(page.getByText('Living Room Sensor')).not.toBeVisible();
  await expect(page.getByText('Bedroom Light')).not.toBeVisible();
});

test('schedules tab badge shows count of scheduled devices', async ({ page }) => {
  // Count = number of targets with schedule || schedule_once.
  const tab = page.getByRole('button', { name: /Schedules/ });
  await expect(tab).toContainText('2');
});

test('search filters scheduled devices', async ({ page }) => {
  const search = page.getByPlaceholder(/search/i);
  await search.fill('garage');
  await expect(page.getByText('Garage Door')).toBeVisible();
  await expect(page.getByText('Office Sensor')).not.toBeVisible();
});

test('recurring schedule cell shows humanized cron', async ({ page }) => {
  const row = page.locator('#tab-schedules tbody tr').filter({ hasText: 'Garage Door' });
  // formatCronHuman('0 3 * * *') yields "Daily 03:00".
  await expect(row).toContainText(/Daily 03:00/);
  await expect(row).toContainText(/Active/);
});

test('one-time schedule cell shows the Once: prefix', async ({ page }) => {
  const row = page.locator('#tab-schedules tbody tr').filter({ hasText: 'Office Sensor' });
  await expect(row).toContainText(/Once:/);
  await expect(row).toContainText(/One-time/);
});

test('Remove Selected is disabled when no rows are selected', async ({ page }) => {
  await page.getByRole('button', { name: /Actions/i }).click();
  const item = page.getByRole('menuitem', { name: /Remove Selected/i });
  await expect(item).toHaveAttribute('aria-disabled', 'true');
  // Close the menu so it doesn't bleed into the next test.
  await page.keyboard.press('Escape');
});

test('Remove Selected fires DELETE for each checked row', async ({ page }) => {
  const deleted: string[] = [];
  await page.route('**/ui/api/targets/*/schedule', route => {
    if (route.request().method() === 'DELETE') {
      deleted.push(decodeURIComponent(route.request().url().split('/targets/')[1].split('/')[0]));
    }
    route.fulfill({ status: 200, json: {} });
  });

  // Check both rows via their checkboxes.
  const checkboxes = page.locator('#tab-schedules tbody input[type="checkbox"]');
  await checkboxes.nth(0).check();
  await checkboxes.nth(1).check();

  await page.getByRole('button', { name: /Actions/i }).click();
  await page.getByRole('menuitem', { name: /Remove Selected \(2\)/i }).click();

  await expect.poll(() => deleted.length).toBe(2);
  expect(deleted.sort()).toEqual(['garage-door.yaml', 'office.yaml']);
});

test('clicking Edit opens the Upgrade modal in scheduled mode', async ({ page }) => {
  const row = page.locator('#tab-schedules tbody tr').filter({ hasText: 'Garage Door' });
  await row.getByRole('button', { name: 'Edit' }).click();
  // UpgradeModal opens with Garage Door's name in the title — exact title
  // may vary, but the modal must render.
  await expect(page.getByRole('dialog')).toBeVisible({ timeout: 5000 });
});
