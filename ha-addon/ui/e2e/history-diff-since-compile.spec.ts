import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

// AV.7: "Diff since compile" button in the Queue log modal opens the
// HistoryPanel deep-linked to (from=job.config_hash, to=working tree).

test('Diff since compile opens HistoryPanel with preset from-hash', async ({ page }) => {
  await page.goto('/');

  // Navigate to the Queue tab and open the log for job-001, which has
  // a config_hash set in fixtures.
  await page.getByRole('button', { name: /Queue/ }).click();
  const successRow = page.getByRole('row').filter({ hasText: 'bedroom-light' });
  await expect(successRow).toBeVisible({ timeout: 5000 });

  // The log modal is opened via the log target cell, or via a Log
  // button. Check the exact control in our app by hovering the row:
  // the Queue tab typically has a clickable target link.
  await successRow.getByRole('button', { name: /^Log$/ }).click();

  // Log modal opened — the Diff-since-compile button should be visible
  // because job-001 has a config_hash.
  const logDialog = page.getByRole('dialog', { name: /bedroom-light/i });
  await expect(logDialog).toBeVisible();
  const diffBtn = logDialog.getByRole('button', { name: /diff since compile/i });
  await expect(diffBtn).toBeVisible();

  // Click it and confirm the HistoryPanel drawer opens for the right file.
  await diffBtn.click();
  const drawer = page.locator('[data-slot="sheet-content"]');
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('heading', { name: /bedroom-light\.yaml/ })).toBeVisible();
});

test('Diff since compile button is hidden when the job has no config_hash', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Queue/ }).click();
  // job-002 (garage-door.yaml, failed) does NOT have config_hash in the
  // fixtures — so the shortcut should be absent.
  const failedRow = page.getByRole('row').filter({ hasText: 'garage-door' });
  await failedRow.getByRole('button', { name: /^Log$/ }).first().click();
  const logDialog = page.getByRole('dialog', { name: /garage-door/i });
  await expect(logDialog).toBeVisible();
  await expect(logDialog.getByRole('button', { name: /diff since compile/i })).toHaveCount(0);
});
