import { expect, test } from '@playwright/test';
import { mockApi, queue } from './fixtures';

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  // Navigate to queue tab
  await page.goto('/');
  await page.getByRole('button', { name: /Queue/ }).click();
});

// ---------------------------------------------------------------------------
// PW.4 — Queue tab interactions
// ---------------------------------------------------------------------------

test('queue shows job states with badges', async ({ page }) => {
  // Wait for queue to render
  await expect(page.getByText('bedroom-light')).toBeVisible({ timeout: 5000 });

  // Check for state indicators — success, failed, working
  await expect(page.getByText(/success/i).first()).toBeVisible();
  await expect(page.getByText(/failed/i).first()).toBeVisible();
  await expect(page.getByText(/working|compiling/i).first()).toBeVisible();
});

test('queue search filters jobs', async ({ page }) => {
  await expect(page.getByText('bedroom-light')).toBeVisible({ timeout: 5000 });

  const search = page.getByPlaceholder(/search/i);
  await search.fill('garage');

  await expect(page.getByText('garage-door').first()).toBeVisible();
  await expect(page.getByText('bedroom-light')).not.toBeVisible();
});

test('clicking a job row opens log modal', async ({ page }) => {
  await expect(page.getByText('bedroom-light')).toBeVisible({ timeout: 5000 });

  // Click on a job row to open its log
  await page.getByText('bedroom-light').first().click();

  // Log modal should appear with terminal-like content
  await expect(page.getByText(/compiling|done|log/i).first()).toBeVisible({ timeout: 5000 });
});

test('worker hostname shown for assigned jobs', async ({ page }) => {
  await expect(page.getByText('build-server-1').first()).toBeVisible({ timeout: 5000 });
});
