import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

// SP.4 / SP.6 — Settings drawer mocked e2e coverage.

test('gear icon opens the Settings drawer with all sections', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('button', { name: 'Settings' })).toBeVisible();
  await page.getByRole('button', { name: 'Settings' }).click();

  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
  // #96: Basic tab opens by default — versioning + auth + display sections.
  await expect(page.getByText('Config versioning')).toBeVisible();
  await expect(page.getByText('Authentication')).toBeVisible();
  await expect(page.getByText(/^Display$/)).toBeVisible();

  // Switch to Advanced — retention/disk/timeouts/polling + About.
  const drawer = page.locator('[data-slot="sheet-content"]');
  await drawer.getByRole('button', { name: /^Advanced$/ }).click();
  await expect(page.getByText('Job history')).toBeVisible();
  await expect(page.getByText('Disk management')).toBeVisible();
  await expect(page.getByText('Timeouts')).toBeVisible();
  await expect(page.getByText('Polling')).toBeVisible();
  await expect(page.getByText('About')).toBeVisible();
});

test('server token field masks by default and can be revealed', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Settings' }).click();

  const drawer = page.locator('[data-slot="sheet-content"]');
  const tokenInput = drawer.locator('input[type="password"]').first();
  await expect(tokenInput).toHaveValue('test-token-abc');

  // Click the eye button to reveal
  await drawer.getByRole('button', { name: 'Show token' }).click();
  const revealed = drawer.locator('input[type="text"][value="test-token-abc"]').first();
  await expect(revealed).toBeVisible();
});

test('auto-commit toggle flips and persists after reopen', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Settings' }).click();

  const toggle = page.getByRole('switch', { name: 'Auto-commit on save' });
  await expect(toggle).toBeVisible();
  // default: on
  await expect(toggle).toBeChecked();

  // Capture the PATCH body to confirm the UI sent the right partial.
  const patchRequest = page.waitForRequest(req =>
    req.url().includes('/ui/api/settings') && req.method() === 'PATCH',
  );
  await toggle.click();
  const req = await patchRequest;
  expect(JSON.parse(req.postData() ?? '{}')).toEqual({ auto_commit_on_save: false });

  // Toast confirms persistence.
  await expect(page.getByText('Setting saved')).toBeVisible();

  // Close + reopen: drawer shows the persisted value.
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Settings' }).click();
  await expect(page.getByRole('switch', { name: 'Auto-commit on save' })).not.toBeChecked();
});

test('numeric retention field rejects out-of-range input', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Settings' }).click();

  // #96: numeric settings live under the Advanced tab now.
  const drawer = page.locator('[data-slot="sheet-content"]');
  await drawer.getByRole('button', { name: /^Advanced$/ }).click();

  // Retention (days) under Job history — default 365.
  const retention = page.locator('input[type="number"]').first();
  await expect(retention).toHaveValue('365');

  await retention.fill('-1');
  await retention.blur();

  // Client-side validation catches it before any PATCH is sent.
  await expect(page.getByText(/must be an integer between/i)).toBeVisible();
  // Value reverts to the previous committed value.
  await expect(retention).toHaveValue('365');
});

test('git author name and email persist after edit + reopen', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Settings' }).click();

  // Scope to the drawer so the Devices tab's "Search devices…" input
  // doesn't match. `[data-slot="sheet-content"]` is the drawer root.
  const drawer = page.locator('[data-slot="sheet-content"]');
  const nameInput = drawer.locator('input[type="text"]').first();
  const emailInput = drawer.locator('input[type="text"]').nth(1);
  await expect(nameInput).toHaveValue('HA User');
  await expect(emailInput).toHaveValue('ha@distributed-esphome.local');

  // Change both and capture the PATCH for the name field.
  const patchRequest = page.waitForRequest(req =>
    req.url().includes('/ui/api/settings') && req.method() === 'PATCH',
  );
  await nameInput.fill('Stefan Zier');
  await nameInput.blur();
  const req = await patchRequest;
  expect(JSON.parse(req.postData() ?? '{}')).toEqual({ git_author_name: 'Stefan Zier' });
  await expect(page.getByText('Setting saved').first()).toBeVisible();

  await emailInput.fill('stefan@zier.com');
  await emailInput.blur();

  // Reopen drawer and confirm persistence.
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Settings' }).click();
  const reopenedDrawer = page.locator('[data-slot="sheet-content"]');
  await expect(reopenedDrawer.locator('input[type="text"]').first()).toHaveValue('Stefan Zier');
  await expect(reopenedDrawer.locator('input[type="text"]').nth(1)).toHaveValue('stefan@zier.com');
});

test('empty git author name is rejected client-side', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Settings' }).click();

  const drawer = page.locator('[data-slot="sheet-content"]');
  const nameInput = drawer.locator('input[type="text"]').first();
  await nameInput.fill('   ');  // whitespace only
  await nameInput.blur();

  await expect(page.getByText(/must not be empty/i)).toBeVisible();
  await expect(nameInput).toHaveValue('HA User');  // reverted
});
