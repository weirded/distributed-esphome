import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// Bug #109 + #110 — clicking Rerun on a queue row opens the
// UpgradeModal pre-populated with the original job's parameters; if
// the chosen worker / tag-expression conflicts with an active
// routing rule, a warning surfaces and confirming sends
// `bypass_routing_rules: true` so the server enqueues the job anyway.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await page.getByRole('button', { name: /^Queue/ }).click();
  await expect(page.getByText('bedroom-light')).toBeVisible({ timeout: 5000 });
});

test('Bug #109 — Rerun on a successful job opens the UpgradeModal', async ({ page }) => {
  // job-001 (bedroom-light) is success — Rerun is the green variant.
  // Clicking it should open the modal targeting bedroom-light.
  const row = page.locator('#tab-queue tbody tr').filter({ hasText: 'bedroom-light' }).first();
  await row.getByRole('button', { name: 'Rerun' }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  // The display name in the title comes from the target's
  // friendly_name ("Bedroom Light") via the App.tsx lookup.
  await expect(dialog.getByRole('heading', { name: /Upgrade — Bedroom Light/ })).toBeVisible();
});

test('Bug #110 — choosing a worker that conflicts with an active rule surfaces a warning', async ({ page }) => {
  // Inject one routing rule that requires worker tag "windows" for
  // any device. Both fixture workers carry "linux" / nothing — neither
  // satisfies "windows", so picking Specific worker should warn.
  await page.route('**/ui/api/routing-rules', route => {
    if (route.request().method() === 'GET') {
      route.fulfill({
        json: {
          rules: [{
            id: 'windows-only',
            name: 'Garage doors must build on Windows',
            severity: 'required',
            device_match: [{ op: 'any_of', tags: ['kitchen'] }],
            worker_match: [{ op: 'all_of', tags: ['windows'] }],
          }],
        },
      });
      return;
    }
    route.continue();
  });

  // bedroom-light is tagged with "kitchen" in the fixture (TG.5
  // setup), so the rule's device_match matches it. Pick any specific
  // worker — none satisfy "windows" — and the warning panel appears.
  const row = page.locator('#tab-queue tbody tr').filter({ hasText: 'bedroom-light' }).first();
  await row.getByRole('button', { name: 'Rerun' }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();

  // Switch worker mode to Specific and pick the first eligible worker.
  await dialog.getByRole('radio', { name: /Specific worker/ }).click();
  await dialog.locator('select#upgrade-worker-select').selectOption({ index: 1 });

  // The warning surfaces with the rule name — proves the conflict
  // detector ran client-side against the routing-rules fetch.
  await expect(dialog.getByText(/Routing-rule conflict/)).toBeVisible();
  await expect(dialog.getByText(/Garage doors must build on Windows/)).toBeVisible();
  // Confirm-button label includes "& override rules" so the click is
  // unambiguous.
  await expect(dialog.getByRole('button', { name: /Upgrade & override rules/ })).toBeVisible();
});

test('Bug #110 — confirming the warning sends bypass_routing_rules: true', async ({ page }) => {
  await page.route('**/ui/api/routing-rules', route => {
    if (route.request().method() === 'GET') {
      route.fulfill({
        json: {
          rules: [{
            id: 'windows-only',
            name: 'Garage doors must build on Windows',
            severity: 'required',
            device_match: [{ op: 'any_of', tags: ['kitchen'] }],
            worker_match: [{ op: 'all_of', tags: ['windows'] }],
          }],
        },
      });
      return;
    }
    route.continue();
  });

  let postedBody: Record<string, unknown> | null = null;
  await page.route('**/ui/api/compile', route => {
    postedBody = route.request().postDataJSON();
    route.fulfill({ json: { enqueued: 1 } });
  });

  const row = page.locator('#tab-queue tbody tr').filter({ hasText: 'bedroom-light' }).first();
  await row.getByRole('button', { name: 'Rerun' }).click();

  const dialog = page.getByRole('dialog');
  await dialog.getByRole('radio', { name: /Specific worker/ }).click();
  await dialog.locator('select#upgrade-worker-select').selectOption({ index: 1 });
  await expect(dialog.getByText(/Routing-rule conflict/)).toBeVisible();
  await dialog.getByRole('button', { name: /Upgrade & override rules/ }).click();

  await expect.poll(() => postedBody).not.toBeNull();
  // The bypass flag rides through to the server.
  expect(postedBody!.bypass_routing_rules).toBe(true);
  // The user's worker pin still rides too — the override skips
  // routing rules but honours the user's explicit constraint.
  expect(postedBody!.pinned_client_id).toBeTruthy();
});

test('Bug #110 — no warning when the chosen worker satisfies every active rule', async ({ page }) => {
  // Same rule, but this time pick a tag expression that requires
  // "linux" (which build-server-1 carries), so the user's filter is
  // compatible with the rule. No warning, no "& override rules".
  await page.route('**/ui/api/routing-rules', route => {
    if (route.request().method() === 'GET') {
      route.fulfill({
        json: {
          rules: [{
            id: 'linux-only',
            name: 'Kitchen devices need a linux worker',
            severity: 'required',
            device_match: [{ op: 'any_of', tags: ['kitchen'] }],
            worker_match: [{ op: 'all_of', tags: ['linux'] }],
          }],
        },
      });
      return;
    }
    route.continue();
  });

  const row = page.locator('#tab-queue tbody tr').filter({ hasText: 'bedroom-light' }).first();
  await row.getByRole('button', { name: 'Rerun' }).click();

  const dialog = page.getByRole('dialog');
  await dialog.getByRole('radio', { name: /Tag expression/ }).click();
  // Drop "linux" into the chip-input — that's the worker filter.
  const chipInput = dialog.locator('input[placeholder*="worker tag"]');
  await chipInput.fill('linux');
  await chipInput.press('Enter');

  await expect(dialog.getByText(/Routing-rule conflict/)).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: /^Upgrade$/ })).toBeVisible();
});
