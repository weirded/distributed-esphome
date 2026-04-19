import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// PT.1 — Pin / unpin via the device-row hamburger menu.
//
// Fixtures (PT.12): bedroom-light has pinned_version='2026.2.0'; living-room
// is unpinned. The pin/unpin endpoints in fixtures.ts return 200 with no
// body so we can verify the API was called.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
});

function rowFor(page: import('@playwright/test').Page, name: string) {
  return page.locator('#tab-devices tbody tr').filter({ hasText: name });
}

test('pinned device shows pin icon in the version cell', async ({ page }) => {
  // bedroom-light is pinned to 2026.2.0 in fixtures — version cell wraps
  // the pin icon in a <span title="Pinned to 2026.2.0">.
  const row = rowFor(page, 'Bedroom Light');
  await expect(row.locator('[title="Pinned ESPHome version: 2026.2.0"]')).toBeVisible();
});

test('unpinned device shows no pin icon', async ({ page }) => {
  // living-room has no pinned_version in fixtures — no pinned-version badge.
  const row = rowFor(page, 'Living Room Sensor');
  await expect(row.locator('[title^="Pinned ESPHome version"]')).toHaveCount(0);
});

test('hamburger on pinned device shows Unpin item with version', async ({ page }) => {
  const row = rowFor(page, 'Bedroom Light');
  await row.getByRole('button', { name: /more actions/i }).click();
  // Menu item text includes the pinned version in parentheses.
  await expect(page.getByRole('menuitem', { name: /Unpin ESPHome version \(2026\.2\.0\)/ })).toBeVisible();
});

test('hamburger on unpinned device shows Pin item', async ({ page }) => {
  const row = rowFor(page, 'Living Room Sensor');
  await row.getByRole('button', { name: /more actions/i }).click();
  await expect(page.getByRole('menuitem', { name: /Pin ESPHome version to current/i })).toBeVisible();
});

test('clicking Unpin fires DELETE on the pin endpoint', async ({ page }) => {
  // Intercept the unpin request specifically and verify it fires.
  let deletedFor: string | null = null;
  await page.route('**/ui/api/targets/*/pin', route => {
    if (route.request().method() === 'DELETE') {
      deletedFor = decodeURIComponent(route.request().url().split('/targets/')[1].split('/')[0]);
    }
    route.fulfill({ status: 200, json: {} });
  });

  const row = rowFor(page, 'Bedroom Light');
  await row.getByRole('button', { name: /more actions/i }).click();
  await page.getByRole('menuitem', { name: /Unpin ESPHome version/ }).click();

  await expect.poll(() => deletedFor).toBe('bedroom-light.yaml');
});

test('clicking Pin fires POST on the pin endpoint', async ({ page }) => {
  let pinnedFor: string | null = null;
  await page.route('**/ui/api/targets/*/pin', route => {
    if (route.request().method() === 'POST') {
      pinnedFor = decodeURIComponent(route.request().url().split('/targets/')[1].split('/')[0]);
    }
    route.fulfill({ status: 200, json: {} });
  });

  const row = rowFor(page, 'Living Room Sensor');
  await row.getByRole('button', { name: /more actions/i }).click();
  await page.getByRole('menuitem', { name: /Pin ESPHome version to current/i }).click();

  await expect.poll(() => pinnedFor).toBe('living-room.yaml');
});
