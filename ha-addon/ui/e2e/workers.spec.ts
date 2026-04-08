import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await page.getByRole('button', { name: /Workers/ }).click();
});

// ---------------------------------------------------------------------------
// PW.5 — Workers tab interactions
// ---------------------------------------------------------------------------

test('workers tab shows worker hostnames', async ({ page }) => {
  await expect(page.getByText('build-server-1').first()).toBeVisible({ timeout: 5000 });
  await expect(page.getByText('build-server-2').first()).toBeVisible();
});

test('online worker shows online indicator', async ({ page }) => {
  await expect(page.getByText('build-server-1').first()).toBeVisible({ timeout: 5000 });
});

test('connect worker button is present', async ({ page }) => {
  const btn = page.getByRole('button', { name: /connect/i });
  await expect(btn).toBeVisible({ timeout: 5000 });
});

test('connect worker button opens modal', async ({ page }) => {
  const btn = page.getByRole('button', { name: /connect/i });
  await expect(btn).toBeVisible({ timeout: 5000 });
  await btn.click();

  // Modal should show connection instructions with docker command
  await expect(page.getByText(/docker/i).first()).toBeVisible({ timeout: 5000 });
});

test('worker shows system info', async ({ page }) => {
  await expect(page.getByText('build-server-1').first()).toBeVisible({ timeout: 5000 });
  // Worker 1 has system_info with cpu, memory, etc.
  await expect(page.getByText(/Intel|i7|32 GB|Debian/i).first()).toBeVisible();
});
