import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// PT.6 — Modal sizing: editor + log modals should fit within the viewport
// at small (1024×768) and large (1920×1080) sizes. Regression guard for the
// "modal overflows the viewport" class of bugs that has hit us a few times.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

async function openEditor(page: import('@playwright/test').Page) {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
  await page
    .locator('#tab-devices tbody tr')
    .first()
    .getByRole('button', { name: 'Edit' })
    .click();
  // Monaco mounts asynchronously; wait for its container.
  await expect(page.locator('[class*="monaco"], [data-keybinding-context]')).toBeVisible({ timeout: 5000 });
}

async function openLogModal(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button', { name: /Queue/ }).click();
  await expect(page.getByText('bedroom-light')).toBeVisible({ timeout: 5000 });
  // Click the per-row "Log" button on a finished job.
  const row = page.locator('#tab-queue tbody tr').filter({ hasText: 'bedroom-light' });
  await row.getByRole('button', { name: 'Log' }).click();
  // xterm container appears once the log fetch resolves.
  await expect(page.locator('.xterm-container')).toBeVisible({ timeout: 5000 });
}

async function fitsInViewport(page: import('@playwright/test').Page, selector: string) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {
      fits: r.right <= window.innerWidth && r.bottom <= window.innerHeight,
      r: { width: r.width, height: r.height, right: r.right, bottom: r.bottom },
      viewport: { w: window.innerWidth, h: window.innerHeight },
    };
  }, selector);
}

async function openUpgradeModal(page: import('@playwright/test').Page) {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
  await page
    .locator('#tab-devices tbody tr')
    .filter({ hasText: 'Living Room Sensor' })
    .getByRole('button', { name: 'Upgrade' })
    .click();
  await expect(page.getByRole('dialog')).toBeVisible({ timeout: 5000 });
}

// Bug #14: UpgradeModal's version list landed below the fold on short
// viewports because the default DialogContent had no max-height. Assert
// the dialog caps at the viewport AND the version-list is reachable
// (within the dialog's internal scroll container) at a phone-tall height.
test('UpgradeModal fits within a short viewport and version list is reachable (#14)', async ({ page }) => {
  await page.setViewportSize({ width: 480, height: 600 });
  await openUpgradeModal(page);

  const dialog = await fitsInViewport(page, '[role="dialog"]');
  expect(dialog).not.toBeNull();
  expect(dialog!.fits, `dialog ${JSON.stringify(dialog!.r)} > viewport ${JSON.stringify(dialog!.viewport)}`).toBe(true);

  // Version "Current" button is the first item in the inline scroll list;
  // scrollIntoViewIfNeeded inside the dialog's overflow-y container should
  // bring it on-screen.
  const currentBtn = page.getByRole('dialog').getByRole('button', { name: /^Current/ });
  await currentBtn.scrollIntoViewIfNeeded();
  await expect(currentBtn).toBeInViewport();
});

for (const viewport of [
  { name: '1024x768', width: 1024, height: 768 },
  { name: '1920x1080', width: 1920, height: 1080 },
]) {
  test(`editor modal fits within ${viewport.name} viewport`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await openEditor(page);
    const dialog = await fitsInViewport(page, '[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog!.fits, `dialog ${JSON.stringify(dialog!.r)} > viewport ${JSON.stringify(dialog!.viewport)}`).toBe(true);
  });

  test(`log modal fits within ${viewport.name} viewport`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await openLogModal(page);
    const dialog = await fitsInViewport(page, '[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog!.fits, `log dialog ${JSON.stringify(dialog!.r)} > viewport ${JSON.stringify(dialog!.viewport)}`).toBe(true);
  });
}
