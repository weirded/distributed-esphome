import { expect, test } from '@playwright/test';
import { mockApi } from './fixtures';

// PW.7 — Theme + responsive Playwright tests

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

// ---------------------------------------------------------------------------
// Theme toggle + persistence
// ---------------------------------------------------------------------------

test('theme toggle switches data-theme attribute', async ({ page }) => {
  await page.goto('/');
  const html = page.locator('html');

  // Default is dark — no data-theme attribute set
  await expect(html).not.toHaveAttribute('data-theme', 'light');

  const toggle = page.locator('header span[title*="Switch to"]');
  await toggle.click();
  await expect(html).toHaveAttribute('data-theme', 'light');

  await toggle.click();
  await expect(html).not.toHaveAttribute('data-theme', 'light');
});

test('theme preference persists across reloads', async ({ page }) => {
  await page.goto('/');
  // Switch to light
  await page.locator('header span[title*="Switch to"]').click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');

  // Reload and confirm light mode is restored from localStorage
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');

  // Switch back so we don't leave the test browser in a non-default state
  await page.locator('header span[title*="Switch to"]').click();
});

test('streamer mode toggle adds .streamer class to html', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  const html = page.locator('html');
  // The streamer toggle button is the only header span whose title mentions "streamer mode"
  const streamerToggle = page.locator('header span[title*="streamer mode" i]');
  await streamerToggle.click();
  await expect(html).toHaveClass(/streamer/);

  // Toggle off
  await streamerToggle.click();
  await expect(html).not.toHaveClass(/streamer/);
});

// ---------------------------------------------------------------------------
// Viewport responsiveness
// ---------------------------------------------------------------------------

test('narrow viewport: tabs and header still rendered', async ({ page }) => {
  await page.setViewportSize({ width: 480, height: 800 });
  await page.goto('/');

  await expect(page.locator('header')).toBeVisible();
  await expect(page.getByRole('button', { name: /Devices/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /Queue/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /Workers/ })).toBeVisible();
});

test('narrow viewport: window-level horizontal scroll is locked', async ({ page }) => {
  await page.setViewportSize({ width: 480, height: 800 });
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  // The window itself shouldn't scroll horizontally — that's the
  // "page yanks sideways on a phone swipe" bug. We don't assert on
  // body.scrollLeft here because Tailwind preflight + flex layouts
  // can leave body slightly scrollable even with overflow-x: hidden;
  // window.scrollX is the property the user actually feels.
  const winX = await page.evaluate(() => {
    window.scrollTo(2000, 0);
    return window.scrollX;
  });
  expect(winX).toBe(0);
});

test('narrow viewport: table-wrap is the horizontal scroll container', async ({ page }) => {
  await page.setViewportSize({ width: 480, height: 800 });
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  // The .table-wrap div is where horizontal scroll lives for wide tables.
  // Verify its computed overflow-x is auto so it actually shows a scrollbar
  // when needed.
  const wrap = page.locator('.table-wrap').first();
  await expect(wrap).toBeVisible();
  const overflowX = await wrap.evaluate(el => getComputedStyle(el).overflowX);
  expect(overflowX).toBe('auto');
});

test('desktop viewport: page renders without horizontal scroll', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  const scrolled = await page.evaluate(() => {
    window.scrollTo(2000, 0);
    return window.scrollX;
  });
  expect(scrolled).toBe(0);
});
