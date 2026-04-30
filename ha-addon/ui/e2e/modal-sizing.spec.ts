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
  // Monaco mounts asynchronously; wait for the editor instance inside the modal.
  // CF.1: we now bundle Monaco locally, which means the loader registers
  // ``.monaco-colors`` / body classes at page boot — the old broad selector
  // matched 14 elements and tripped strict mode. Anchor on the actual
  // editor element (``[role="code"].monaco-editor``) inside the dialog.
  await expect(
    page.locator('[data-slot="dialog-content"] [role="code"].monaco-editor').first(),
  ).toBeVisible({ timeout: 5000 });
}

async function openLogModal(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button', { name: /Queue/ }).click();
  await expect(page.getByText('bedroom-light')).toBeVisible({ timeout: 5000 });
  // #209: per-row Log button moved into the row hamburger ("View log").
  const row = page.locator('#tab-queue tbody tr').filter({ hasText: 'bedroom-light' });
  await row.getByRole('button', { name: 'More actions' }).click();
  await page.getByRole('menuitem', { name: 'View log' }).click();
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

  // #215: "Current" version is now a radio label (was an inline button
  // in the old scrolling list). The dialog's overflow-y container
  // should still bring it on-screen via scrollIntoViewIfNeeded.
  const currentRadio = page.getByRole('dialog').getByRole('radio', { name: /^Current/ });
  await currentRadio.scrollIntoViewIfNeeded();
  await expect(currentRadio).toBeInViewport();
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
