import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// PT.7 — Toolbar button heights must be uniform across every tab.
//
// The Devices toolbar already has an existing identical-height test in
// devices.spec.ts. This spec extends the same check to Queue / Workers /
// Schedules, so layout drift in any of the tab toolbars trips CI.

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });
});

async function measureToolbarHeights(page: import('@playwright/test').Page, tabSelector: string) {
  return page.evaluate((sel) => {
    const toolbar = document.querySelector(`${sel} .actions`);
    if (!toolbar) return [];
    return Array.from(toolbar.children).map(el => ({
      text: el.textContent?.trim().slice(0, 25) ?? '',
      height: Math.round(el.getBoundingClientRect().height * 10) / 10,
    }));
  }, tabSelector);
}

for (const { name, tabName, tabSelector } of [
  { name: 'Queue', tabName: /Queue/, tabSelector: '#tab-queue' },
  { name: 'Schedules', tabName: /Schedules/, tabSelector: '#tab-schedules' },
]) {
  test(`${name} toolbar buttons have identical height`, async ({ page }) => {
    await page.getByRole('button', { name: tabName }).click();
    const heights = await measureToolbarHeights(page, tabSelector);
    expect(heights.length, `${name} toolbar should have at least one element`).toBeGreaterThan(0);
    const firstHeight = heights[0].height;
    for (const btn of heights) {
      expect(btn.height, `"${btn.text}" height ${btn.height} != ${firstHeight}`).toBe(firstHeight);
    }
  });
}

test('Workers toolbar uses the connect-worker button', async ({ page }) => {
  // Workers tab doesn't render an .actions toolbar — its primary action is
  // the "Connect Worker" button. Verify it exists at the standard 28px row
  // height the other toolbar buttons use, for consistency.
  await page.getByRole('button', { name: /Workers/ }).click();
  const button = page.getByRole('button', { name: /connect worker/i }).first();
  await expect(button).toBeVisible();
  const h = await button.evaluate((el) => Math.round(el.getBoundingClientRect().height * 10) / 10);
  expect(h, `Connect Worker height ${h} != 28`).toBe(28);
});
