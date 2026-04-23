import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// QS.25 follow-up — Workers tab actions: clean cache, parallel-jobs slot
// control, remove offline worker. WL.3 consolidated Clean Cache / Remove
// and "View logs" into a single per-row "Actions" dropdown menu.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
  await page.getByRole('button', { name: /Workers/ }).click();
  await expect(page.getByText('build-server-1').first()).toBeVisible({ timeout: 5000 });
});

function workerRow(page: import('@playwright/test').Page, hostname: string) {
  return page.locator('table tbody tr').filter({ hasText: hostname });
}

async function openActions(page: import('@playwright/test').Page, hostname: string) {
  await workerRow(page, hostname).getByRole('button', { name: new RegExp(`Actions for ${hostname}`) }).click();
}

test('actions dropdown reveals Clean cache for online workers', async ({ page }) => {
  await openActions(page, 'build-server-1');
  await expect(page.getByRole('menuitem', { name: 'Clean cache' })).toBeVisible();
  await expect(page.getByRole('menuitem', { name: 'Remove' })).toHaveCount(0);
});

test('actions dropdown reveals Remove for offline workers', async ({ page }) => {
  await openActions(page, 'build-server-2');
  await expect(page.getByRole('menuitem', { name: 'Remove' })).toBeVisible();
  await expect(page.getByRole('menuitem', { name: 'Clean cache' })).toHaveCount(0);
});

test('Clean cache fires POST /workers/{id}/clean', async ({ page }) => {
  let cleanedFor: string | null = null;
  // Clear the mockApi fixture's handler for this pattern so ours is
  // the only one that runs (Playwright's route stack doesn't always
  // prefer the newest registration when the patterns match identically).
  await page.unroute('**/ui/api/workers/*/clean');
  await page.route('**/ui/api/workers/*/clean', route => {
    if (route.request().method() === 'POST') {
      const url = route.request().url();
      cleanedFor = url.split('/workers/')[1].split('/')[0];
    }
    route.fulfill({ status: 200, json: {} });
  });

  await openActions(page, 'build-server-1');
  const cleanItem = page.getByRole('menuitem', { name: 'Clean cache' });
  await expect(cleanItem).toBeVisible();
  await cleanItem.click();

  await expect.poll(() => cleanedFor).toBe('worker-1');
});

test('Remove offline worker fires DELETE /workers/{id}', async ({ page }) => {
  let removedFor: string | null = null;
  await page.unroute('**/ui/api/workers/*');
  await page.route('**/ui/api/workers/*', route => {
    if (route.request().method() === 'DELETE') {
      const url = route.request().url();
      removedFor = url.split('/workers/')[1];
    }
    route.fulfill({ status: 200, json: {} });
  });

  await openActions(page, 'build-server-2');
  const removeItem = page.getByRole('menuitem', { name: 'Remove' });
  await expect(removeItem).toBeVisible();
  await removeItem.click();

  await expect.poll(() => removedFor).toBe('worker-2');
});

test('parallel-jobs +/- buttons debounce-fire POST /parallel-jobs', async ({ page }) => {
  let lastPayload: { max_parallel_jobs?: number; id?: string } | null = null;
  await page.route('**/ui/api/workers/*/parallel-jobs', route => {
    if (route.request().method() === 'POST') {
      const url = route.request().url();
      const id = url.split('/workers/')[1].split('/')[0];
      try {
        const body = JSON.parse(route.request().postData() ?? '{}');
        lastPayload = { ...body, id };
      } catch { /* ignore */ }
    }
    route.fulfill({ status: 200, json: {} });
  });

  // worker-1 has max_parallel_jobs=2 in fixtures. Click + once → debounced
  // POST 600ms later with count=3.
  const row = workerRow(page, 'build-server-1');
  // The slot control's "+" button is the second small Button in the slot
  // cell; locate by text content ("+").
  await row.getByRole('button', { name: '+', exact: true }).click();

  await expect.poll(() => lastPayload?.id, { timeout: 3_000 }).toBe('worker-1');
  expect(lastPayload!.max_parallel_jobs).toBe(3);
});

test('Connect Worker button opens the modal', async ({ page }) => {
  await page.getByRole('button', { name: /connect worker/i }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('heading', { name: /Connect a Build Worker/i })).toBeVisible();
});
