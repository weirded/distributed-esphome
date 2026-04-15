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

  const toggle = page.locator('header button[title*="Switch to"]');
  await toggle.click();
  await expect(html).toHaveAttribute('data-theme', 'light');

  await toggle.click();
  await expect(html).not.toHaveAttribute('data-theme', 'light');
});

test('theme preference persists across reloads', async ({ page }) => {
  await page.goto('/');
  // Switch to light
  await page.locator('header button[title*="Switch to"]').click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');

  // Reload and confirm light mode is restored from localStorage
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');

  // Switch back so we don't leave the test browser in a non-default state
  await page.locator('header button[title*="Switch to"]').click();
});

test('streamer mode toggle adds .streamer class to html', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  const html = page.locator('html');
  // The streamer toggle is the only header button whose title mentions "streamer mode"
  const streamerToggle = page.locator('header button[title*="streamer mode" i]');
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

test('narrow viewport: header is horizontally scrollable so every control is reachable (#1)', async ({ page }) => {
  // iPhone SE width — narrow enough to overflow the header's natural width.
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto('/');
  await expect(page.getByText('Distributed Build')).toBeVisible({ timeout: 5000 });

  const header = page.locator('header');
  // overflow-x: auto turns the header into its own scroll container.
  const overflowX = await header.evaluate(el => getComputedStyle(el).overflowX);
  expect(overflowX).toBe('auto');

  // Sanity: header content is wider than viewport (i.e. there's something
  // to scroll). If this stops being true we should remove the test, not
  // tighten the assertion.
  const { scrollWidth, clientWidth } = await header.evaluate(el => ({
    scrollWidth: el.scrollWidth,
    clientWidth: el.clientWidth,
  }));
  expect(scrollWidth).toBeGreaterThan(clientWidth);

  // Streamer-mode toggle is the last interactive control before the spacer
  // and most likely to be off-screen on iOS Safari. Scroll the header to
  // bring it into view and assert it becomes reachable.
  const streamerBtn = page.locator('header button[aria-label*="streamer mode"]');
  await streamerBtn.scrollIntoViewIfNeeded();
  await expect(streamerBtn).toBeInViewport();
});

test('header version dropdown renders ABOVE the sticky header (#14)', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Living Room Sensor')).toBeVisible({ timeout: 5000 });

  const trigger = page.locator('header button[title*="ESPHome version"]').first();
  await trigger.click();
  // Wait for the portalled menu to mount.
  const menu = page.locator('[data-slot="dropdown-menu-content"]');
  await expect(menu).toBeVisible({ timeout: 2000 });

  // The dropdown popup must be on top of the header in the stacking order.
  // Read both elements' computed z-index and confirm popup > header. With
  // header at z-100 (the old value), the dropdown's top edge rendered
  // BEHIND the sticky header at the version chip's anchor position.
  const stack = await page.evaluate(() => {
    const header = document.querySelector('header')!;
    const popup = document.querySelector('[data-slot="dropdown-menu-content"]')!;
    return {
      headerZ: parseInt(getComputedStyle(header).zIndex, 10),
      popupZ: parseInt(getComputedStyle(popup).zIndex, 10),
    };
  });
  expect(stack.popupZ).toBeGreaterThan(stack.headerZ);

  // Belt-and-braces: even when popup and header overlap vertically (Base
  // UI's `sideOffset: 4` puts the popup right below the trigger which sits
  // mid-header), the popup's content at that y-band must be on top. Use
  // elementsFromPoint() at the popup's top-center pixel and assert the
  // popup beats the header in the hit list.
  const hit = await page.evaluate(() => {
    const popup = document.querySelector('[data-slot="dropdown-menu-content"]')!;
    const r = popup.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const y = r.top + 5;
    const stack = document.elementsFromPoint(x, y);
    return {
      topMost: stack[0]?.tagName.toLowerCase() ?? '',
      popupIndex: stack.findIndex(el => el === popup || popup.contains(el)),
      headerIndex: stack.findIndex(el => el.tagName.toLowerCase() === 'header'),
    };
  });
  // popup wins if it's earlier in the hit list (front of stack)
  expect(hit.popupIndex).toBeGreaterThanOrEqual(0);
  if (hit.headerIndex !== -1) {
    expect(hit.popupIndex).toBeLessThan(hit.headerIndex);
  }
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
