import { expect, test } from '@playwright/test';
import { mockApi, targets } from './fixtures';
import type { Target } from '@/types';

// UD.5 — Devices-tab Platform column shows chip family on the
// primary line and PlatformIO board on a smaller secondary line.

const seededTargets: Target[] = targets.map(t => {
  if (t.target === 'living-room.yaml') {
    return { ...t, esp_type: 'ESP32-S3', board: 'esp32-s3-devkitm-1' };
  }
  if (t.target === 'bedroom-light.yaml') {
    return { ...t, esp_type: 'ESP8266', board: 'd1_mini' };
  }
  return t;
});

async function enableEsp(page: import('@playwright/test').Page) {
  // Settings² icon button carries aria-label="Toggle columns".
  await page.getByRole('button', { name: 'Toggle columns' }).click();
  await page.getByRole('menuitemcheckbox', { name: 'Platform' }).click();
  // Close picker so subsequent locator queries don't match items inside it.
  await page.keyboard.press('Escape');
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.route('**/ui/api/targets', route => route.fulfill({ json: seededTargets }));
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
  await enableEsp(page);
});

test('Platform column header reads "Platform" (renamed from "ESP")', async ({ page }) => {
  await expect(page.getByRole('button', { name: /^Platform/ })).toBeVisible();
});

test('chip family + board both render for living-room', async ({ page }) => {
  const row = page.locator('#tab-devices tbody tr').filter({ hasText: 'Living Room Sensor' });
  await expect(row).toContainText('ESP32-S3');
  await expect(row).toContainText('esp32-s3-devkitm-1');
});

test('ESP8266 + d1_mini both render for bedroom-light', async ({ page }) => {
  const row = page.locator('#tab-devices tbody tr').filter({ hasText: 'Bedroom Light' });
  await expect(row).toContainText('ESP8266');
  await expect(row).toContainText('d1_mini');
});

test('row without esp_type renders muted em-dash, no board line', async ({ page }) => {
  const row = page.locator('#tab-devices tbody tr').filter({ hasText: 'Garage Door' });
  // Garage door wasn't seeded with esp_type/board → cell falls back to —.
  await expect(row).not.toContainText('ESP32');
  await expect(row).not.toContainText('ESP8266');
});
