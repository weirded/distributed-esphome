import { expect, test, type Page } from '@playwright/test';
import { mockApi } from './fixtures';

/**
 * TG.10 — mocked Playwright coverage of the TG.4–TG.9 fleet-tags + routing
 * surfaces. Covers four user paths:
 *
 *   1. Rule-builder happy path — open the modal from the Workers
 *      toolbar, fill in a new rule, save, and confirm it appears in the
 *      list.
 *   2. Inline tag edit on Devices and Workers tabs — click a tag cell,
 *      add a tag in the dialog, save, and confirm the per-target /
 *      per-worker POST fires with the merged tag list.
 *   3. Filter pills — click a tag pill in the Devices tab, the table
 *      narrows to matching rows; click again, the filter clears.
 *   4. BLOCKED badge — fixture seeds a job in BLOCKED with
 *      ``blocked_reason`` set; the badge tooltip surfaces the rule, and
 *      clicking the badge opens the rules modal pre-selected to the
 *      rule that fired (TG.9 deep-link).
 */

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

async function openRoutingRulesModal(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: /^Workers/ }).click();
  await page.getByRole('button', { name: /^Routing rules/ }).click();
  await expect(page.getByRole('dialog')).toBeVisible({ timeout: 3_000 });
}

test('rule-builder happy path — create and persist a new routing rule (TG.10)', async ({ page }) => {
  // Capture the POST so we can assert the body shape independently of
  // the SWR-driven re-render below.
  let posted: { name?: string; device_match?: unknown; worker_match?: unknown } | null = null;
  await page.route('**/ui/api/routing-rules', async (route) => {
    if (route.request().method() === 'POST') {
      posted = JSON.parse(route.request().postData() ?? '{}');
    }
    await route.fallback();
  });

  await openRoutingRulesModal(page);

  // Seeded rule renders in the list view.
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Kitchen devices need an arm64 worker')).toBeVisible();

  // Open the builder.
  await dialog.getByRole('button', { name: /Add rule/ }).click();
  await expect(dialog.getByText('Add routing rule')).toBeVisible();

  // Fill the name — id auto-slugs.
  await dialog.getByPlaceholder('e.g. Kitchen devices need kitchen workers').fill('Bedroom needs sleeping worker');
  // Auto-slugged id appears in the read-only preview field.
  await expect(dialog.locator('input[value="bedroom-needs-sleeping-worker"]')).toBeVisible();

  // Builder DOM order (1 device clause + 1 worker clause initially):
  //   [0] Name input
  //   [1] ID input (auto-slug)
  //   [2] Device clause #1 chip-input
  //   [3] Worker clause #1 chip-input
  // Scoping via placeholder breaks after the first commit because the
  // placeholder is only rendered while the chip list is empty.
  const inputs = dialog.locator('input');
  await inputs.nth(2).fill('kitchen');
  await inputs.nth(2).press('Enter');
  await inputs.nth(3).fill('linux');
  await inputs.nth(3).press('Enter');

  // Live-preview footer renders some "N of M devices … K of L … workers" copy.
  await expect(dialog.getByText(/\d+ of \d+ devices/)).toBeVisible();
  await expect(dialog.getByText(/\d+ of \d+ online workers/)).toBeVisible();

  // Save.
  await dialog.getByRole('button', { name: /Create rule/ }).click();

  // POST landed with the typed name.
  await expect.poll(() => posted?.name, { timeout: 3_000 }).toBe('Bedroom needs sleeping worker');

  // Modal returns to list mode and the new rule shows up.
  await expect(dialog.getByText('Bedroom needs sleeping worker')).toBeVisible({ timeout: 3_000 });
});

test('inline tag edit on Devices tab persists via /meta POST (TG.10)', async ({ page }) => {
  const postedMeta: Record<string, unknown> = {};
  await page.route('**/ui/api/targets/*/meta', async (route, request) => {
    const m = new URL(request.url()).pathname.match(/\/ui\/api\/targets\/([^/]+)\/meta$/);
    if (m && request.method() === 'POST') {
      postedMeta[decodeURIComponent(m[1])] = JSON.parse(request.postData() || '{}');
    }
    await route.fulfill({ status: 200, json: { ok: true } });
  });

  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5_000 });

  // Click the per-row tag cell — opens the shared TagsEditDialog.
  await page.locator('#tab-devices').getByRole('button', { name: 'Tags for living-room' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible({ timeout: 3_000 });

  // The chip-input's placeholder only shows when the tag list is empty
  // (TagChipInput, line 87) and ``living-room.yaml`` already has two
  // tags from the fixture — so locate the bare input by tag name and
  // focus by clicking the chip-input wrapper.
  const input = dialog.locator('input').first();
  await input.click();
  await input.fill('production');
  await input.press('Enter');
  await dialog.getByRole('button', { name: /^Save$/ }).click();

  await expect.poll(() => postedMeta['living-room.yaml'], { timeout: 3_000 }).toEqual({
    tags: 'kitchen,cosy,production',
  });
});

test('inline tag edit on Workers tab POSTs new tags to /workers/{id}/tags (TG.10)', async ({ page }) => {
  const postedTags: Record<string, unknown> = {};
  await page.route('**/ui/api/workers/*/tags', async (route, request) => {
    const m = new URL(request.url()).pathname.match(/\/ui\/api\/workers\/([^/]+)\/tags$/);
    if (m && request.method() === 'POST') {
      postedTags[decodeURIComponent(m[1])] = JSON.parse(request.postData() || '{}');
    }
    await route.fulfill({ status: 200, json: { ok: true } });
  });

  await page.goto('/');
  await page.getByRole('button', { name: /^Workers/ }).click();
  // Scope to the workers tab — the hostname appears in every slot cell.
  const tabWorkers = page.locator('#tab-workers');
  await expect(tabWorkers.getByRole('button', { name: 'Tags for build-server-1' })).toBeVisible({ timeout: 5_000 });

  await tabWorkers.getByRole('button', { name: 'Tags for build-server-1' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible({ timeout: 3_000 });

  // build-server-1 already has tags ['linux','fast'] so the chip-input
  // placeholder is hidden — locate the bare input.
  const input = dialog.locator('input').first();
  await input.click();
  await input.fill('arm64');
  await input.press('Enter');
  await dialog.getByRole('button', { name: /^Save$/ }).click();

  // Workers tab uses an array-of-strings shape (not the Devices CSV).
  await expect.poll(() => postedTags['worker-1'], { timeout: 3_000 }).toEqual({
    tags: ['linux', 'fast', 'arm64'],
  });
});

test('filter pill toggles narrow / restore the Devices table (TG.10)', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5_000 });

  // Devices tab seed: living-room (kitchen,cosy), bedroom-light (kitchen,sleeping),
  // garage-door (no tags), office (no tags). The "kitchen" pill should
  // narrow to the two kitchen-tagged rows; clicking again clears.
  const tabDevices = page.locator('#tab-devices');
  // The pill chip carries the count suffix " (2)" so we can match a
  // distinctive label rather than the bare tag string (which also
  // appears inline on each row's tag cell).
  const kitchenPill = tabDevices.getByRole('button', { name: /^kitchen \(2\)$/ });
  await expect(kitchenPill).toBeVisible();

  // Initial — all four managed devices visible.
  await expect(tabDevices.getByText('Living Room Sensor')).toBeVisible();
  await expect(tabDevices.getByText('Garage Door')).toBeVisible();

  // Click pill → only kitchen-tagged rows survive.
  await kitchenPill.click();
  await expect(tabDevices.getByText('Living Room Sensor')).toBeVisible();
  await expect(tabDevices.getByText('Bedroom Light')).toBeVisible();
  await expect(tabDevices.getByText('Garage Door')).not.toBeVisible();

  // Click again → filter clears.
  await kitchenPill.click();
  await expect(tabDevices.getByText('Garage Door')).toBeVisible();
});

test('BLOCKED badge surfaces rule reason and deep-links into the rule editor (TG.10)', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /^Queue/ }).click();

  // The seeded job-009 is BLOCKED with blocked_reason pointing at the
  // kitchen-only rule. The badge renders as a button with an aria-label
  // citing the rule name.
  const badge = page.getByRole('button', {
    name: /Blocked by rule 'Kitchen devices need an arm64 worker'/,
  });
  await expect(badge).toBeVisible({ timeout: 5_000 });

  // Click → rules modal opens in edit mode for the kitchen-only rule.
  await badge.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible({ timeout: 3_000 });
  // Title carries the rule name when in edit mode.
  await expect(dialog.getByText(/Edit rule — Kitchen devices need an arm64 worker/)).toBeVisible();
});
