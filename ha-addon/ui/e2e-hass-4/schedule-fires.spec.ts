import { expect, test, type APIRequestContext } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { retryTransient } from './retry';

const __dirname = dirname(fileURLToPath(import.meta.url));

/**
 * PT.9 — Verify a one-time schedule on the real server fires automatically
 * and is cleared from the target after the job lands.
 *
 * Sets a `schedule_once` 8 seconds in the future, polls the queue for a
 * matching scheduled job, then asserts the target's `schedule_once` field
 * has been cleared. Cancels the resulting job to keep the queue clean for
 * the next run — we don't wait for a real compile here, just for the
 * scheduler to enqueue.
 */

const TARGET_FILENAME = process.env.FLEET_TARGET || process.env.HASS4_TARGET || 'cyd-office-info.yaml';

const EXPECTED_VERSION =
  process.env.EXPECTED_VERSION ||
  readFileSync(join(__dirname, '../../VERSION'), 'utf-8').trim();

interface QueueJob {
  id: string;
  target: string;
  state: string;
  scheduled?: boolean;
  schedule_kind?: 'recurring' | 'once' | null;
  created_at: string;
}

interface Target {
  target: string;
  schedule_once?: string | null;
  schedule?: string | null;
}

async function getQueue(request: APIRequestContext): Promise<QueueJob[]> {
  return retryTransient(async () => {
    const resp = await request.get('/ui/api/queue');
    if (!resp.ok()) throw new Error(`/ui/api/queue returned ${resp.status()}`);
    return resp.json();
  });
}

async function getTarget(request: APIRequestContext, name: string): Promise<Target | null> {
  return retryTransient(async () => {
    const resp = await request.get('/ui/api/targets');
    if (!resp.ok()) throw new Error(`/ui/api/targets returned ${resp.status()}`);
    const targets = (await resp.json()) as Target[];
    return targets.find(t => t.target === name) ?? null;
  });
}

test.describe.serial('schedule fires hass-4 smoke', () => {
  test.beforeAll(async ({ request }) => {
    const resp = await request.get('/ui/api/server-info');
    expect(resp.ok(), `server-info should return 2xx (got ${resp.status()})`).toBe(true);
    const info = await resp.json();
    expect(info.addon_version).toBe(EXPECTED_VERSION);
  });

  test.beforeEach(async ({ request }) => {
    // Idempotent cleanup — clear any leftover schedule_once from a previous
    // failed run so we don't trip on stale state.
    await request.delete(`/ui/api/targets/${encodeURIComponent(TARGET_FILENAME)}/schedule`);
  });

  test('one-time schedule fires within window and clears schedule_once', async ({ request }) => {
    test.setTimeout(60_000);

    // Snapshot the latest existing job so we can detect the new scheduled one.
    const initialQueue = await getQueue(request);
    const initialIds = new Set(initialQueue.map(j => j.id));

    // Schedule 8 seconds in the future. Server scheduler ticks once a
    // second, so 8s gives a comfortable window without wasting wall time.
    const fireAt = new Date(Date.now() + 8_000);
    const setResp = await request.post(
      `/ui/api/targets/${encodeURIComponent(TARGET_FILENAME)}/schedule/once`,
      { data: { datetime: fireAt.toISOString() } },
    );
    expect(setResp.ok(), `schedule/once POST should return 2xx (got ${setResp.status()})`).toBe(true);

    // Confirm the schedule was set on the target.
    const beforeTarget = await getTarget(request, TARGET_FILENAME);
    expect(beforeTarget?.schedule_once, 'target.schedule_once should be set').toBeTruthy();

    // Wait up to 25s for a NEW scheduled job for our target to appear.
    let firedJob: QueueJob | null = null;
    await expect.poll(
      async () => {
        const q = await getQueue(request);
        const candidate = q.find(j =>
          j.target === TARGET_FILENAME &&
          !initialIds.has(j.id) &&
          j.scheduled === true,
        );
        if (candidate) {
          firedJob = candidate;
          return candidate.id;
        }
        return null;
      },
      { timeout: 25_000, intervals: [1_000, 1_000, 2_000], message: 'expected a scheduled job to be enqueued' },
    ).not.toBeNull();

    expect(firedJob, 'fired job must be set').not.toBeNull();
    expect(firedJob!.schedule_kind, 'job should be tagged as one-time').toBe('once');

    // Target's schedule_once must be cleared after the fire.
    await expect.poll(
      async () => {
        const t = await getTarget(request, TARGET_FILENAME);
        return t?.schedule_once ?? null;
      },
      { timeout: 10_000, message: 'target.schedule_once should clear after fire' },
    ).toBeNull();

    // Cancel the job we just enqueued so we don't burn build time on a
    // throwaway compile when the schedule check was the actual subject.
    const cancelResp = await request.post('/ui/api/cancel', {
      data: { job_ids: [firedJob!.id] },
    });
    expect(cancelResp.ok(), 'cancel should accept the enqueued job').toBe(true);
  });
});
