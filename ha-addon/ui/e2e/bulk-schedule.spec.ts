import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// PT.4 — Bulk-schedule actions on the Devices tab "Actions" dropdown.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
});

function actionsTrigger(page: import('@playwright/test').Page) {
  // The Actions dropdown sits inside the Devices toolbar.
  return page.locator('#tab-devices .actions').getByRole('button', { name: /^Actions/ });
}

test('Schedule Selected and Remove Schedule items are disabled with no selection', async ({ page }) => {
  await actionsTrigger(page).click();
  await expect(page.getByRole('menuitem', { name: /Schedule Selected/ })).toHaveAttribute('aria-disabled', 'true');
  await expect(page.getByRole('menuitem', { name: /Remove Schedule from Selected/ })).toHaveAttribute('aria-disabled', 'true');
  await page.keyboard.press('Escape');
});

test('selecting devices enables Schedule Selected', async ({ page }) => {
  // Check two device rows.
  const checkboxes = page.locator('#tab-devices tbody input.target-cb');
  await checkboxes.nth(0).check();
  await checkboxes.nth(1).check();

  await actionsTrigger(page).click();
  await expect(page.getByRole('menuitem', { name: /Schedule Selected/ })).not.toHaveAttribute('aria-disabled', 'true');
  await page.keyboard.press('Escape');
});

test('Schedule Selected opens the modal in scheduleOnly mode with multi-target title', async ({ page }) => {
  const checkboxes = page.locator('#tab-devices tbody input.target-cb');
  await checkboxes.nth(0).check();
  await checkboxes.nth(1).check();

  await actionsTrigger(page).click();
  await page.getByRole('menuitem', { name: /Schedule Selected/ }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  // Title is "Schedule Upgrade — N devices" (scheduleOnly hides the worker
  // + version selectors and forces the heading into Scheduled phrasing).
  await expect(dialog.getByRole('heading', { name: /Schedule Upgrade — 2 devices/ })).toBeVisible();
  // UX.8: the 3-option Action radio (Upgrade Now / Download Now /
  // Schedule Upgrade) is hidden in scheduleOnly mode.
  await expect(dialog.getByRole('radio', { name: /Upgrade Now/ })).toHaveCount(0);
  await expect(dialog.getByRole('radio', { name: /Download Now/ })).toHaveCount(0);
});

test('saving a bulk schedule fires POST /schedule for every selected target', async ({ page }) => {
  const posted: string[] = [];
  await page.route('**/ui/api/targets/*/schedule', route => {
    if (route.request().method() === 'POST') {
      const url = route.request().url();
      posted.push(decodeURIComponent(url.split('/targets/')[1].split('/')[0]));
    }
    route.fulfill({ json: { schedule_enabled: true } });
  });

  // Select living-room (first row by alphabetical order: bedroom-light < garage-door
  // < living-room < office, but the table sort default is by target ASC).
  // Just check the first two rows whatever they are; the test asserts on count.
  const checkboxes = page.locator('#tab-devices tbody input.target-cb');
  await checkboxes.nth(0).check();
  await checkboxes.nth(1).check();

  await actionsTrigger(page).click();
  await page.getByRole('menuitem', { name: /Schedule Selected/ }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  // Default cadence (friendly mode, every 1 day at 02:00) is fine — just submit.
  await dialog.getByRole('button', { name: /Save Schedule/ }).click();

  await expect.poll(() => posted.length).toBe(2);
});

test('Remove Schedule from Selected fires DELETE on each scheduled target', async ({ page }) => {
  const deleted: string[] = [];
  await page.route('**/ui/api/targets/*/schedule', route => {
    if (route.request().method() === 'DELETE') {
      const url = route.request().url();
      deleted.push(decodeURIComponent(url.split('/targets/')[1].split('/')[0]));
    }
    route.fulfill({ status: 200, json: {} });
  });

  // Select all four rows. Only garage-door (recurring) and office (once)
  // have schedules in fixtures, so only those two should DELETE-fire.
  const checkboxes = page.locator('#tab-devices tbody input.target-cb');
  const count = await checkboxes.count();
  for (let i = 0; i < count; i++) {
    await checkboxes.nth(i).check();
  }

  await actionsTrigger(page).click();
  await page.getByRole('menuitem', { name: /Remove Schedule from Selected/ }).click();

  await expect.poll(() => deleted.length).toBe(2);
  expect(deleted.sort()).toEqual(['garage-door.yaml', 'office.yaml']);
});
