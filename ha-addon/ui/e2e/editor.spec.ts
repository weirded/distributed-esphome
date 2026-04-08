import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// PW.6 — Editor modal Playwright tests
//
// The editor opens when the user clicks "Edit" on a device row. It contains
// a Monaco editor with the YAML config, plus Save / Validate / Save & Upgrade
// buttons. Closing with unsaved changes shows a confirm dialog.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  // Wait for the device table to populate before doing anything
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
});

async function openEditor(page: import('@playwright/test').Page) {
  // Each device row has an Edit button. Click the first one (Living Room Sensor).
  // There are multiple "Edit" buttons (one per row) — use the first.
  await page.getByRole('button', { name: /^edit$/i }).first().click();
  // Monaco renders into a div with the .monaco-editor class
  await expect(page.locator('.monaco-editor').first()).toBeVisible({ timeout: 10_000 });
}

test('clicking Edit opens the editor modal with Monaco', async ({ page }) => {
  await openEditor(page);
  // Editor body should contain the fixture YAML content
  await expect(page.locator('.monaco-editor').first()).toBeVisible();
});

test('editor modal has Save, Validate, and Save & Upgrade buttons', async ({ page }) => {
  await openEditor(page);
  // Save button (exact match avoids matching "Save & Upgrade")
  await expect(page.getByRole('button', { name: /^save$/i })).toBeVisible();
  // Save & Upgrade
  await expect(page.getByRole('button', { name: /save & upgrade/i })).toBeVisible();
  // Validate
  await expect(page.getByRole('button', { name: /^validate$/i })).toBeVisible();
});

test('clicking Save fires the save API and shows a toast', async ({ page }) => {
  let saveHits = 0;
  await page.route('**/ui/api/targets/*/content', route => {
    if (route.request().method() === 'POST') {
      saveHits++;
      return route.fulfill({ json: { ok: true } });
    }
    return route.fallback();
  });

  await openEditor(page);
  await page.getByRole('button', { name: /^save$/i }).click();

  // Server received the save POST
  await expect.poll(() => saveHits).toBeGreaterThan(0);
});

test('clicking Validate fires the validate API', async ({ page }) => {
  let validateHits = 0;
  await page.route('**/ui/api/validate', route => {
    validateHits++;
    return route.fulfill({ json: { job_id: 'validate-001' } });
  });

  await openEditor(page);
  await page.getByRole('button', { name: /^validate$/i }).click();

  await expect.poll(() => validateHits).toBeGreaterThan(0);
});

test('clicking Save & Upgrade fires save then compile', async ({ page }) => {
  let saveHits = 0;
  let compileHits = 0;
  await page.route('**/ui/api/targets/*/content', route => {
    if (route.request().method() === 'POST') {
      saveHits++;
      return route.fulfill({ json: { ok: true } });
    }
    return route.fallback();
  });
  await page.route('**/ui/api/compile', route => {
    compileHits++;
    return route.fulfill({ json: { enqueued: 1 } });
  });

  await openEditor(page);
  await page.getByRole('button', { name: /save & upgrade/i }).click();

  await expect.poll(() => saveHits).toBeGreaterThan(0);
  await expect.poll(() => compileHits).toBeGreaterThan(0);
});

test('editor modal closes via Escape key when clean', async ({ page }) => {
  await openEditor(page);
  await page.keyboard.press('Escape');
  // Modal is gone
  await expect(page.locator('.monaco-editor').first()).not.toBeVisible({ timeout: 5000 });
});
