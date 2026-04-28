import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// RC.1 — read-only "View rendered config" modal opens from the Devices
// hamburger and shows the YAML *as ESPHome will compile it* (i.e. with
// substitutions / packages / !secret resolved). Server-side endpoint is
// covered by tests/test_rendered_config.py; these tests pin the UI's
// open / render / error / copy / download flows against a mocked HTTP
// route.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
});

async function openRenderedConfigFor(page: import('@playwright/test').Page, deviceText: string) {
  const row = page.locator('#tab-devices tbody tr').filter({ hasText: deviceText }).first();
  await row.getByRole('button', { name: /More actions/ }).click();
  await page.getByRole('menuitem', { name: /View rendered config/ }).click();
}

test('hamburger menu surfaces the View rendered config item for every device', async ({ page }) => {
  const row = page.locator('#tab-devices tbody tr').filter({ hasText: 'Living Room Sensor' }).first();
  await row.getByRole('button', { name: /More actions/ }).click();
  await expect(page.getByRole('menuitem', { name: /View rendered config/ })).toBeVisible();
  await page.keyboard.press('Escape');
});

test('successful render: modal shows the rendered YAML in a Monaco editor', async ({ page }) => {
  const rendered = `esphome:\n  name: living-room\n  friendly_name: Living Room Sensor\nesp32:\n  board: esp32dev\nwifi:\n  ssid: my-network\n  password: hunter2-resolved-from-secret\n`;
  await page.route('**/ui/api/targets/*/rendered-config', route => {
    route.fulfill({ json: { success: true, output: rendered, cached: false } });
  });

  await openRenderedConfigFor(page, 'Living Room Sensor');

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('heading', { name: /Rendered config — Living Room Sensor/ })).toBeVisible();
  // Header carries the !secret warning so the user reads it before
  // copying.
  await expect(dialog.getByText(/contains the values of any/)).toBeVisible();
  await expect(dialog.getByText(/copy with care/)).toBeVisible();
  // Monaco renders the YAML inside a `.monaco-editor` container —
  // wait for it to mount, then assert a stretch of the rendered
  // text appears inside.
  const editor = dialog.locator('.monaco-editor').first();
  await expect(editor).toBeVisible({ timeout: 10_000 });
  await expect(editor).toContainText('living-room');
  await expect(editor).toContainText('hunter2-resolved-from-secret');
});

test('failure: stderr surfaces in a red panel, no editor', async ({ page }) => {
  const errBody = "INVALID: '!secret oven_password' could not be resolved\n";
  await page.route('**/ui/api/targets/*/rendered-config', route => {
    route.fulfill({ json: { success: false, output: errBody, cached: false } });
  });

  await openRenderedConfigFor(page, 'Living Room Sensor');

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(/esphome config reported an error/)).toBeVisible();
  await expect(dialog.getByText(/could not be resolved/)).toBeVisible();
  // No Monaco editor renders on the failure path.
  await expect(dialog.locator('.monaco-editor')).toHaveCount(0);
  // Copy + Download stay disabled on the error path.
  await expect(dialog.getByRole('button', { name: /^Copy$/ })).toBeDisabled();
  await expect(dialog.getByRole('button', { name: /Download/ })).toBeDisabled();
});

test('Copy writes the rendered YAML to the clipboard', async ({ page, browserName }) => {
  test.skip(browserName !== 'chromium', 'Clipboard permission is Chromium-only in CI.');
  const rendered = `esphome:\n  name: living-room\n`;
  await page.route('**/ui/api/targets/*/rendered-config', route => {
    route.fulfill({ json: { success: true, output: rendered, cached: false } });
  });
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);

  await openRenderedConfigFor(page, 'Living Room Sensor');
  const dialog = page.getByRole('dialog');
  await expect(dialog.locator('.monaco-editor')).toBeVisible({ timeout: 10_000 });
  await dialog.getByRole('button', { name: /^Copy$/ }).click();

  // Read clipboard via the page so we get the same browser-context
  // permission Playwright just granted.
  const text = await page.evaluate(() => navigator.clipboard.readText());
  expect(text).toBe(rendered);
});
