import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// QS.25 follow-up — localStorage round-trip persistence: column visibility
// (Devices tab gear menu) and theme (header sun/moon toggle).

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test('hiding a column persists across reload', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  // Sanity: Area column is hidden by default. Toggle it on, then off again,
  // to walk both sides of the persistence path. Simpler: toggle the
  // default-on "HA" column off and verify the header disappears + survives
  // reload.
  await expect(page.getByRole('columnheader', { name: /^HA$/ })).toBeVisible();

  // Open the column picker (gear icon)
  await page.getByRole('button', { name: 'Toggle columns' }).click();
  // Click the HA checkbox menu item
  await page.getByRole('menuitemcheckbox', { name: /^HA$/ }).click();
  // Close the menu
  await page.keyboard.press('Escape');

  await expect(page.getByRole('columnheader', { name: /^HA$/ })).toHaveCount(0);

  // Reload — the persisted preference should restore the hidden state
  await page.reload();
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
  await expect(page.getByRole('columnheader', { name: /^HA$/ })).toHaveCount(0);
});

test('column visibility writes to localStorage under device-columns', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  await page.getByRole('button', { name: 'Toggle columns' }).click();
  await page.getByRole('menuitemcheckbox', { name: /^HA$/ }).click();
  await page.keyboard.press('Escape');

  // Re-read localStorage from the page and assert the key exists with HA
  // missing from the visible-columns list.
  const stored = await page.evaluate(() => localStorage.getItem('device-columns'));
  expect(stored, 'device-columns localStorage entry should exist').toBeTruthy();
  const visible = JSON.parse(stored!) as string[];
  expect(visible).not.toContain('ha');
});

test('theme toggle persists across reload', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  // Default is dark — no data-theme attribute on <html>.
  const html = page.locator('html');
  await expect(html).not.toHaveAttribute('data-theme', 'light');

  // Toggle to light
  await page.locator('header button[title*="Switch to"]').click();
  await expect(html).toHaveAttribute('data-theme', 'light');

  // localStorage 'theme' must read 'light'
  const persisted = await page.evaluate(() => localStorage.getItem('theme'));
  expect(persisted).toBe('light');

  // Reload — light mode should restore
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
});

test('theme defaults to dark when no localStorage value exists', async ({ page }) => {
  // Wipe storage before the page boots so the initial-theme branch hits the
  // "no stored value → dark" fallback.
  await page.addInitScript(() => localStorage.removeItem('theme'));
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  await expect(page.locator('html')).not.toHaveAttribute('data-theme', 'light');
});

test('showUnmanaged toggle persists across reload', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  // Default is true. Toggle off via the gear menu.
  await page.getByRole('button', { name: 'Toggle columns' }).click();
  await page.getByRole('menuitemcheckbox', { name: /Show unmanaged devices/i }).click();
  await page.keyboard.press('Escape');

  const persisted = await page.evaluate(() => localStorage.getItem('showUnmanaged'));
  expect(persisted).toBe('false');

  await page.reload();
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
  // After reload, the menu still shows it as unchecked.
  await page.getByRole('button', { name: 'Toggle columns' }).click();
  const checkbox = page.getByRole('menuitemcheckbox', { name: /Show unmanaged devices/i });
  await expect(checkbox).toHaveAttribute('aria-checked', 'false');
});
