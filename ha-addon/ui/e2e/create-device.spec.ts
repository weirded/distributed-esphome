import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// CD.7 — mocked Playwright coverage for the "new" and "duplicate" flows.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test('new device button opens the NewDeviceModal', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  // Click the "+ New Device" button in the Devices tab toolbar
  await page.getByRole('button', { name: /new device/i }).click();

  // Dialog appears with the expected title
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('heading', { name: /new device/i })).toBeVisible();

  // The text input is focused and the .yaml suffix is shown
  await expect(dialog.getByText('.yaml', { exact: false })).toBeVisible();
});

test('new device flow creates and opens editor', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  // Open the modal
  await page.getByRole('button', { name: /new device/i }).click();
  const createDialog = page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: /new device/i }) });
  await expect(createDialog).toBeVisible();

  // Type a valid slug
  const input = createDialog.getByPlaceholder(/kitchen-sensor/i);
  await input.fill('office-plug');

  // Click Create
  await createDialog.getByRole('button', { name: /^create$/i }).click();

  // Modal closes (no dialog with the "New Device" heading any more)
  await expect(createDialog).toHaveCount(0, { timeout: 5000 });

  // The editor modal opens on the new target. Monaco takes a beat to mount.
  await expect(page.locator('[class*="monaco"], [data-keybinding-context]')).toBeVisible({ timeout: 5000 });
});

test('new device modal validates the slug format', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  await page.getByRole('button', { name: /new device/i }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();

  const input = dialog.getByPlaceholder(/kitchen-sensor/i);

  // Uppercase letters rejected (inline error)
  await input.fill('Kitchen');
  await expect(dialog.getByText(/lowercase letters.*hyphens/i)).toBeVisible();

  // Underscores rejected
  await input.fill('my_device');
  await expect(dialog.getByText(/lowercase letters.*hyphens/i)).toBeVisible();

  // Valid slug clears the error and enables the Create button
  await input.fill('valid-slug');
  await expect(dialog.getByText(/lowercase letters.*hyphens/i)).not.toBeVisible();
  await expect(dialog.getByRole('button', { name: /^create$/i })).toBeEnabled();
});

test('new device modal rejects collision with existing target', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  await page.getByRole('button', { name: /new device/i }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();

  // "living-room" already exists in the fixtures
  const input = dialog.getByPlaceholder(/kitchen-sensor/i);
  await input.fill('living-room');
  await expect(dialog.getByText(/already exists/i)).toBeVisible();
  await expect(dialog.getByRole('button', { name: /^create$/i })).toBeDisabled();
});

test('duplicate hamburger item opens modal with pre-filled name', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  // Click the ⋮ hamburger on the first device row
  await page.locator('#tab-devices tbody tr').first().locator('.action-menu-trigger').click();

  // Click "Duplicate…"
  await page.getByRole('button', { name: /duplicate/i }).click();

  // Modal opens with pre-filled "-copy" suffix
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('heading', { name: /duplicate/i })).toBeVisible();

  const input = dialog.getByPlaceholder(/kitchen-sensor/i);
  await expect(input).toHaveValue(/-copy$/);
});

test('duplicate flow creates and opens editor', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  // Hamburger → Duplicate…
  await page.locator('#tab-devices tbody tr').first().locator('.action-menu-trigger').click();
  await page.getByRole('button', { name: /duplicate/i }).click();

  const dupDialog = page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: /^duplicate/i }) });
  await expect(dupDialog).toBeVisible();

  // The default is "<source>-copy" — change it to something unique
  const input = dupDialog.getByPlaceholder(/kitchen-sensor/i);
  await input.fill('living-room-2');

  await dupDialog.getByRole('button', { name: /^duplicate$/i }).click();

  // Duplicate dialog closes
  await expect(dupDialog).toHaveCount(0, { timeout: 5000 });

  // Editor opens on the new target
  await expect(page.locator('[class*="monaco"], [data-keybinding-context]')).toBeVisible({ timeout: 5000 });
});
