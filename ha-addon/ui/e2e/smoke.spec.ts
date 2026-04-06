import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

// ---------------------------------------------------------------------------
// PW.2 — Smoke tests: page loads, all three tabs render, header elements
// ---------------------------------------------------------------------------

test('page loads and shows header', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('header')).toBeVisible();
  await expect(page.getByText('Distributed Build')).toBeVisible();
  await expect(page.getByText(/^v1\.3/)).toBeVisible();
});

test('all three tabs are present', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: /Devices/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /Queue/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /Workers/ })).toBeVisible();
});

test('devices tab is active by default and shows devices', async ({ page }) => {
  await page.goto('/');
  // Wait for the device table to populate
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
  await expect(page.getByText('Bedroom Light')).toBeVisible();
  await expect(page.getByText('Garage Door')).toBeVisible();
});

test('device tab shows IP addresses', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('192.168.1.10')).toBeVisible({ timeout: 5000 });
  await expect(page.getByText('192.168.1.11')).toBeVisible();
});

test('esphome version is shown in header', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: /ESPHome 2026\.3\.2/ })).toBeVisible({ timeout: 5000 });
});

test('secrets button is present', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Secrets')).toBeVisible();
});

test('theme toggle is present', async ({ page }) => {
  await page.goto('/');
  // Sun or moon icon for theme toggle
  const toggle = page.locator('header span[title*="Switch to"]');
  await expect(toggle).toBeVisible();
});

// ---------------------------------------------------------------------------
// Tab switching
// ---------------------------------------------------------------------------

test('switching to queue tab shows jobs', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Queue/ }).click();

  // Should see job targets from fixture data
  await expect(page.getByText('bedroom-light')).toBeVisible({ timeout: 5000 });
  await expect(page.getByText('garage-door')).toBeVisible();
  await expect(page.getByText('living-room')).toBeVisible();
});

test('switching to workers tab shows workers', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Workers/ }).click();

  await expect(page.getByText('build-server-1').first()).toBeVisible({ timeout: 5000 });
  await expect(page.getByText('build-server-2').first()).toBeVisible();
});

test('tab counts show correct numbers', async ({ page }) => {
  await page.goto('/');
  // Wait for data to load
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  // Queue should show "1 active" (one working job)
  const queueTab = page.getByRole('button', { name: /Queue/ });
  await expect(queueTab).toContainText('1 active');

  // Workers should show "1/2" (1 online out of 2)
  const workersTab = page.getByRole('button', { name: /Workers/ });
  await expect(workersTab).toContainText('1/2');
});
