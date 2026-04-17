import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// QS.25 follow-up — rename and delete flows from the device hamburger menu.
// Ensures the right API endpoints fire with the right payloads.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
});

function rowFor(page: import('@playwright/test').Page, name: string) {
  return page.locator('#tab-devices tbody tr').filter({ hasText: name });
}

test('hamburger Rename opens the RenameModal', async ({ page }) => {
  const row = rowFor(page, 'Living Room Sensor');
  await row.getByRole('button', { name: /more actions/i }).click();
  await page.getByRole('menuitem', { name: /^Rename$/ }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('heading', { name: /rename/i })).toBeVisible();
});

test('Rename submission fires POST /rename with new_name', async ({ page }) => {
  let renamePayload: { target?: string; new_name?: string } = {};
  await page.route('**/ui/api/targets/*/rename', route => {
    if (route.request().method() === 'POST') {
      const url = route.request().url();
      const target = decodeURIComponent(url.split('/targets/')[1].split('/')[0]);
      try {
        const body = JSON.parse(route.request().postData() ?? '{}');
        renamePayload = { ...body, target };
      } catch { /* ignore */ }
    }
    route.fulfill({ json: { new_filename: 'living-room-renamed.yaml' } });
  });

  const row = rowFor(page, 'Living Room Sensor');
  await row.getByRole('button', { name: /more actions/i }).click();
  await page.getByRole('menuitem', { name: /^Rename$/ }).click();

  const dialog = page.getByRole('dialog');
  await dialog.locator('input#rename-device-name').fill('living-room-renamed');
  await dialog.getByRole('button', { name: /Rename & Upgrade/ }).click();

  await expect.poll(() => renamePayload.target).toBe('living-room.yaml');
  expect(renamePayload.new_name).toBe('living-room-renamed');
});

test('hamburger Delete opens the DeleteModal with archive option', async ({ page }) => {
  const row = rowFor(page, 'Living Room Sensor');
  await row.getByRole('button', { name: /more actions/i }).click();
  await page.getByRole('menuitem', { name: /^Delete$/ }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('heading', { name: /delete/i })).toBeVisible();
});

test('Delete confirm fires DELETE on the target endpoint', async ({ page }) => {
  let deletedFor: string | null = null;
  let archiveFlag: string | null = null;
  await page.route('**/ui/api/targets/*', route => {
    if (route.request().method() === 'DELETE') {
      const url = route.request().url();
      const after = url.split('/targets/')[1] ?? '';
      const [name, query] = after.split('?');
      deletedFor = decodeURIComponent(name);
      archiveFlag = new URLSearchParams(query ?? '').get('archive');
      return route.fulfill({ status: 200, json: {} });
    }
    return route.fallback();
  });

  const row = rowFor(page, 'Living Room Sensor');
  await row.getByRole('button', { name: /more actions/i }).click();
  await page.getByRole('menuitem', { name: /^Delete$/ }).click();

  const dialog = page.getByRole('dialog');
  // DeleteModal default action is "Archive" (warn) — fires DELETE with
  // ?archive=true. "Delete Permanently" requires a second confirmation.
  await dialog.getByRole('button', { name: /^Archive$/ }).click();

  await expect.poll(() => deletedFor).toBe('living-room.yaml');
  expect(archiveFlag).toBe('true');
});

test('Delete Permanently requires a second confirmation', async ({ page }) => {
  let deletedFor: string | null = null;
  let archiveFlag: string | null = null;
  await page.route('**/ui/api/targets/*', route => {
    if (route.request().method() === 'DELETE') {
      const url = route.request().url();
      const after = url.split('/targets/')[1] ?? '';
      const [name, query] = after.split('?');
      deletedFor = decodeURIComponent(name);
      archiveFlag = new URLSearchParams(query ?? '').get('archive');
      return route.fulfill({ status: 200, json: {} });
    }
    return route.fallback();
  });

  const row = rowFor(page, 'Living Room Sensor');
  await row.getByRole('button', { name: /more actions/i }).click();
  await page.getByRole('menuitem', { name: /^Delete$/ }).click();

  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: /Delete Permanently/ }).click();
  // After the first click, the modal swaps in "Yes, Delete Forever" — wait
  // for that confirmation button, then click it.
  const confirm = dialog.getByRole('button', { name: /Yes, Delete Forever/ });
  await expect(confirm).toBeVisible();
  await confirm.click();

  await expect.poll(() => deletedFor).toBe('living-room.yaml');
  expect(archiveFlag).toBe('false');
});
