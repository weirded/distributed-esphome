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
  // #85: wordmark is now "ESPHome Fleet" alongside the house glyph.
  await expect(page.getByText('ESPHome Fleet', { exact: true })).toBeVisible();
  await expect(page.getByText(/^v\d+\.\d+/)).toBeVisible();
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
  const toggle = page.locator('header button[title*="Switch to"]');
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
  // PT.12 fixtures add a recurring-scheduled garage-door + cancelled
  // living-room job; multiple rows for those targets is expected.
  await expect(page.getByText('garage-door').first()).toBeVisible();
  await expect(page.getByText('living-room').first()).toBeVisible();
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

  // Queue should show "2 active" — fixtures contain one WORKING job
  // (job-003) and one PENDING job (job-004). Bumped from "1 active" in C.6
  // when the missing job states (pending, timed_out) were added to the
  // fixtures so the queue tab is exercised on the full state machine.
  const queueTab = page.getByRole('button', { name: /Queue/ });
  await expect(queueTab).toContainText('2 active');

  // Workers should show "1/2" (1 online out of 2)
  const workersTab = page.getByRole('button', { name: /Workers/ });
  await expect(workersTab).toContainText('1/2');
});
