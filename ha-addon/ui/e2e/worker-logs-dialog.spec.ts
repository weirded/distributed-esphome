import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

/**
 * WL.3 — Workers-tab "View logs" dialog.
 *
 * The dialog wraps the same LogModal component QueueTab uses for
 * compile-job logs, parametrized over a tagged source union. Opening
 * it fetches the server's per-worker snapshot (initial hydration);
 * live lines stream in via the /ui/api/workers/{id}/logs/ws WebSocket.
 *
 * Test doubles:
 *   - /ui/api/workers/{id}/logs returns a canned snapshot string.
 *   - The WebSocket path is NOT mocked: Playwright's default behaviour
 *     (browser opens WS, no server → connection fails quickly) is fine
 *     for these assertions since we only care about the initial
 *     hydration path and the dropdown plumbing.
 */

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

test('View logs opens a dialog titled with the worker hostname', async ({ page }) => {
  await openActions(page, 'build-server-1');
  const viewLogsItem = page.getByRole('menuitem', { name: 'View logs' });
  await expect(viewLogsItem).toBeVisible();
  await viewLogsItem.click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  // Hostname is the modal title for worker-log mode.
  await expect(dialog.getByText('build-server-1', { exact: true })).toBeVisible();
});

test('View logs opens a WS to the worker-logs endpoint', async ({ page }) => {
  // Hydration and live tail both flow through the same WS — no
  // separate GET snapshot. This test asserts the WS is opened to
  // the right URL; backend coverage (test_worker_log_broker.py's
  // TestSubscribeAndSnapshot) proves the first frame is the buffer.
  const wsUrls: string[] = [];
  page.on('websocket', ws => wsUrls.push(ws.url()));

  await openActions(page, 'build-server-1');
  const viewLogsItem = page.getByRole('menuitem', { name: 'View logs' });
  await expect(viewLogsItem).toBeVisible();
  await viewLogsItem.click();

  await expect.poll(
    () => wsUrls.find(u => u.includes('/ui/api/workers/worker-1/logs/ws')) ?? '',
  ).toContain('/ui/api/workers/worker-1/logs/ws');
});

test('Download log exports a worker-specific filename', async ({ page }) => {
  await openActions(page, 'build-server-1');
  const viewLogsItem = page.getByRole('menuitem', { name: 'View logs' });
  await expect(viewLogsItem).toBeVisible();
  await viewLogsItem.click();
  await expect(page.getByRole('dialog')).toBeVisible();

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: /Download log/i }).click();
  const download = await downloadPromise;

  const suggested = download.suggestedFilename();
  expect(suggested).toMatch(/^worker-build-server-1-.+\.log$/);
});

test('Actions menu survives a poll cycle without closing', async ({ page }) => {
  // Bug #2 / #71 class guard: the dropdown's open state is lifted out
  // of the TanStack row cell. A SWR re-render triggered by the 1 Hz
  // /ui/api/workers poll must NOT tear the menu down mid-interaction.
  // Count workers-poll requests via the Page.request event (no route
  // interception — the mockApi fixture already handles /ui/api/workers
  // and Playwright's route precedence would swallow our handler).
  let workersPollCount = 0;
  page.on('request', req => {
    if (req.method() === 'GET' && req.url().endsWith('/ui/api/workers')) {
      workersPollCount++;
    }
  });

  await openActions(page, 'build-server-1');
  await expect(page.getByRole('menuitem', { name: 'View logs' })).toBeVisible();
  const pollsAtOpen = workersPollCount;
  // Wait until the SWR loop has fired at least two more polls after
  // the menu opened — enough to trigger TanStack row re-renders.
  await expect.poll(
    () => workersPollCount,
    { timeout: 10_000 },
  ).toBeGreaterThan(pollsAtOpen + 1);
  // The menu item must still be visible — if the dropdown unmounted
  // on the re-render, this assertion fails.
  await expect(page.getByRole('menuitem', { name: 'View logs' })).toBeVisible();
});
