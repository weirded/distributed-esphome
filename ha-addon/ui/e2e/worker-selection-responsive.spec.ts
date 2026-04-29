import { expect, test } from '@playwright/test';
import { mockApi, queue } from './fixtures';
import type { Job } from '@/types';

// UD.2 — Worker-selection cell short/long label switching at the
// Tailwind ``xl:`` breakpoint (1280 px).
//
// Pre-fix the cell rendered the long form ("Fastest worker available",
// "Pinned to worker", etc.) at every viewport, which overflowed on a
// standard 13" laptop. Fix uses ``hidden xl:inline`` + ``xl:hidden`` to
// swap the long form for a short form below 1280 px. Tooltip retains
// the long context regardless.

const seededQueue: Job[] = queue.map(j => {
  if (j.id === 'job-001') return { ...j, selection_reason: 'higher_perf_score' };
  if (j.id === 'job-002') return { ...j, selection_reason: 'pinned_to_worker' };
  return j;
});

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.route('**/ui/api/queue', route => route.fulfill({ json: seededQueue }));
  await page.goto('/');
  await page.getByRole('button', { name: /Queue/ }).click();
  await expect(page.getByText('bedroom-light')).toBeVisible({ timeout: 5000 });
});

test('long-form selection-reason label visible at ≥1280 px', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  // job-001 (bedroom-light) → higher_perf_score → "Fastest worker available"
  const row = page.locator('#tab-queue tbody tr').filter({ hasText: 'bedroom-light' });
  await expect(row.getByText('Fastest worker available')).toBeVisible();
  await expect(row.getByText('Fastest', { exact: true })).toBeHidden();
});

test('short-form selection-reason label visible below 1280 px', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 900 });
  const row = page.locator('#tab-queue tbody tr').filter({ hasText: 'bedroom-light' });
  await expect(row.getByText('Fastest', { exact: true })).toBeVisible();
  await expect(row.getByText('Fastest worker available')).toBeHidden();
});

test('Pinned variant short form is "Pinned" below 1280 px', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 900 });
  // job-002 (garage-door, failed) → pinned_to_worker → short "Pinned"
  const row = page.locator('#tab-queue tbody tr').filter({ hasText: 'garage-door' }).first();
  await expect(row.getByText('Pinned', { exact: true })).toBeVisible();
  await expect(row.getByText('Pinned to worker')).toBeHidden();
});

test('tooltip carries the long form regardless of viewport', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 900 });
  const row = page.locator('#tab-queue tbody tr').filter({ hasText: 'bedroom-light' });
  // The wrapper <span> has the title attribute; the long-form helper
  // text always lands on it whether the visible label is the long or
  // short variant.
  const wrapper = row.locator('span[title*="highest effective perf score"]');
  await expect(wrapper).toHaveCount(1);
});
