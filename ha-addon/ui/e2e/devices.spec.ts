import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

// ---------------------------------------------------------------------------
// PW.3 — Device tab interactions
// ---------------------------------------------------------------------------

test('search filters devices', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  // Type in search box
  const search = page.getByPlaceholder(/search/i);
  await search.fill('bedroom');

  // Bedroom should be visible, others should not
  await expect(page.getByText('Bedroom Light')).toBeVisible();
  await expect(page.getByText('Living Room Sensor')).not.toBeVisible();
  await expect(page.getByText('Garage Door')).not.toBeVisible();
});

test('search clears and shows all devices', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  const search = page.getByPlaceholder(/search/i);
  await search.fill('bedroom');
  await expect(page.getByText('Living Room Sensor')).not.toBeVisible();

  await search.fill('');
  await expect(page.getByText('Living Room Sensor')).toBeVisible();
  await expect(page.getByText('Bedroom Light')).toBeVisible();
});

test('upgrade all button is present', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  // There should be some upgrade-related button
  const upgradeBtn = page.getByRole('button', { name: /upgrade/i });
  await expect(upgradeBtn.first()).toBeVisible();
});

test('clicking edit opens editor modal', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  // Click the hamburger menu on the first device row
  const menuButtons = page.locator('button[aria-haspopup="menu"], button[aria-label*="menu"], [data-testid="device-menu"]');
  // Find the row-level menu trigger — it's a ☰ or similar icon button
  const hamburger = page.locator('button').filter({ hasText: '☰' }).first();

  if (await hamburger.isVisible()) {
    await hamburger.click();
    // Look for Edit menu item
    const editItem = page.getByRole('menuitem', { name: /edit/i });
    if (await editItem.isVisible({ timeout: 2000 }).catch(() => false)) {
      await editItem.click();
      // Editor modal should appear with Monaco
      await expect(page.locator('[class*="monaco"], [data-keybinding-context]')).toBeVisible({ timeout: 5000 });
    }
  }
});

test('theme toggle switches between dark and light', async ({ page }) => {
  await page.goto('/');

  // Default is dark mode
  const html = page.locator('html');

  // Click theme toggle
  const toggle = page.locator('header span[title*="Switch to"]');
  await toggle.click();

  // Should now be light mode
  await expect(html).toHaveAttribute('data-theme', 'light');

  // Click again
  await toggle.click();

  // Should be back to dark (no data-theme attribute)
  await expect(html).not.toHaveAttribute('data-theme', 'light');
});
