import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// Bug #17 — TagsEditDialog layout sanity. The dialog has a header (title
// only), a padded body (description + chip-input + suggestions), and a
// DialogFooter that anchors the Cancel + Save buttons at the bottom.
// This spec opens the modal from the Workers tab and asserts:
//   - title and footer are rendered with the right structural slots
//   - Cancel + Save are *both* below the chip-input box (not floating
//     mid-body or wrapping unexpectedly)
//   - the close × overlay is suppressed (we have an explicit Cancel)
//   - the dialog fits within a small viewport so the footer is reachable

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

async function openTagsModal(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button', { name: /Workers/ }).click();
  await expect(page.locator('#tab-workers')).toBeVisible({ timeout: 5000 });
  // Click any worker's Tags cell to open the editor.
  const tagsCell = page.locator('#tab-workers tbody tr').first().getByRole('button', { name: /Tags for/ });
  await tagsCell.click();
  await expect(page.locator('[data-slot="dialog-content"]')).toBeVisible({ timeout: 3000 });
}

test('TagsEditDialog has header / body / footer with Cancel + Save in the footer (#17)', async ({ page }) => {
  await openTagsModal(page);

  const dialog = page.locator('[data-slot="dialog-content"]');

  // Header carries the title.
  await expect(dialog.locator('[data-slot="dialog-title"]')).toContainText('Edit tags');

  // Footer anchors the buttons.
  const footer = dialog.locator('[data-slot="dialog-footer"]');
  await expect(footer).toBeVisible();
  await expect(footer.getByRole('button', { name: 'Cancel' })).toBeVisible();
  await expect(footer.getByRole('button', { name: 'Save' })).toBeVisible();

  // No floating × close button — explicit Cancel is the only dismiss path.
  await expect(dialog.locator('[data-slot="dialog-close"]')).toHaveCount(0);
});

test('TagsEditDialog footer sits below the chip-input box (#17)', async ({ page }) => {
  await openTagsModal(page);

  const dialog = page.locator('[data-slot="dialog-content"]');
  // The TagsEditDialog body contains exactly one bare <input> (the
  // chip-input). The chip-input's placeholder is suppressed when the
  // worker already has tags (TG.10 fixture), so locate the input by
  // position rather than placeholder text.
  const input = dialog.locator('input').first();
  const footer = dialog.locator('[data-slot="dialog-footer"]');

  const inputBox = await input.boundingBox();
  const footerBox = await footer.boundingBox();
  expect(inputBox).not.toBeNull();
  expect(footerBox).not.toBeNull();
  // Footer top must be below input bottom — buttons can't float into
  // the chip-input area or sit above it.
  expect(footerBox!.y, `footer at ${footerBox!.y} should be below input ending at ${inputBox!.y + inputBox!.height}`)
    .toBeGreaterThan(inputBox!.y + inputBox!.height);
});

test('TagsEditDialog fits within a 480x600 viewport with footer reachable (#17)', async ({ page }) => {
  await page.setViewportSize({ width: 480, height: 600 });
  await openTagsModal(page);

  const dialog = page.locator('[data-slot="dialog-content"]');
  const dialogBox = await dialog.boundingBox();
  expect(dialogBox).not.toBeNull();
  const bottom = dialogBox!.y + dialogBox!.height;
  expect(bottom, `dialog bottom ${bottom} > viewport 600`).toBeLessThanOrEqual(600);

  const saveBtn = dialog.locator('[data-slot="dialog-footer"]').getByRole('button', { name: 'Save' });
  await saveBtn.scrollIntoViewIfNeeded();
  await expect(saveBtn).toBeInViewport();
});
