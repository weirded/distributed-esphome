import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// PT.8 — Closing the editor on a freshly created (unsaved) device must
// fire DELETE so the .pending.<name>.yaml stub doesn't linger. Regression
// guard for bug #42.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test('cancelling a brand-new device fires DELETE on the pending file', async ({ page }) => {
  // Capture DELETE calls on /ui/api/targets/* — must include the pending stub.
  const deleted: string[] = [];
  await page.route('**/ui/api/targets/*', route => {
    if (route.request().method() === 'DELETE') {
      const url = route.request().url();
      const after = url.split('/targets/')[1] ?? '';
      deleted.push(decodeURIComponent(after.split('?')[0]));
      return route.fulfill({ status: 200, json: {} });
    }
    return route.fallback();
  });

  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  await page.getByRole('button', { name: /new device/i }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByPlaceholder(/kitchen-sensor/i).fill('temp-stub');
  await dialog.getByRole('button', { name: /^create$/i }).click();

  // Editor opens on the new pending target.
  await expect(page.locator('[class*="monaco"], [data-keybinding-context]')).toBeVisible({ timeout: 5000 });

  // Close without saving — Escape works because the editor is clean (no edits made).
  await page.keyboard.press('Escape');

  // App.tsx schedules a deleteTarget(.pending.temp-stub.yaml, archive=false).
  await expect.poll(() => deleted).toContain('.pending.temp-stub.yaml');
});

test('closing an existing (already-saved) target does NOT fire DELETE', async ({ page }) => {
  // Sanity check: opening the editor on an existing fixture target and
  // closing it should NOT delete the file. The pending-cleanup path only
  // fires for targets that the App.tsx unsavedNewTargets set holds.
  const deleted: string[] = [];
  await page.route('**/ui/api/targets/*', route => {
    if (route.request().method() === 'DELETE') {
      const url = route.request().url();
      const after = url.split('/targets/')[1] ?? '';
      deleted.push(decodeURIComponent(after.split('?')[0]));
      return route.fulfill({ status: 200, json: {} });
    }
    return route.fallback();
  });

  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
  await page
    .locator('#tab-devices tbody tr')
    .first()
    .getByRole('button', { name: 'Edit' })
    .click();
  await expect(page.locator('[class*="monaco"], [data-keybinding-context]')).toBeVisible({ timeout: 5000 });

  // Close the clean editor. No edits → Escape closes immediately.
  await page.keyboard.press('Escape');
  // CR.6: wait for an observable signal (modal gone) instead of a fixed
  // timeout. Also guarantees we don't race `deleted` on slow CI.
  await expect(page.getByRole('dialog')).toHaveCount(0);

  expect(deleted).toEqual([]);
});
