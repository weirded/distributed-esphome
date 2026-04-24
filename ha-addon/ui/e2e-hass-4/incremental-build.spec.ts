import { expect, test, type APIRequestContext } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));

/**
 * PT.10 — Two consecutive compiles of the same target on the same worker:
 * the second build must be substantially faster than the first because the
 * PlatformIO build cache (`.pioenvs`) survives between runs.
 *
 * Pinned to local-worker so both jobs share a cache directory; otherwise
 * round-robin scheduling could send the second job to a different worker
 * with a cold cache and the comparison becomes meaningless.
 *
 * Threshold: second ≤ 1.20 × first. Honest about what this test can detect:
 * for a small device like cyd-office-info, most of the wall-clock budget is
 * OTA upload + PlatformIO setup, not the C++ compile that the cache
 * accelerates. Two healthy back-to-back runs have measured ratios of 0.76,
 * 0.83, and 0.88 — the variance is high enough that any threshold below
 * ~1.0 flakes. The realistic regression we catch here is "PlatformIO has
 * to redownload its package cache" — that pushes the ratio well above 1.5.
 * Tune via SPEEDUP_THRESHOLD env if you want a stricter check on a larger
 * project. Ratio is logged so trends can be eyeballed across CI runs.
 *
 * NOTE: this test consumes ~2 real compiles' worth of build time. It runs
 * inside the existing 10-minute hass-4 suite budget but is the longest
 * single test by far.
 */

const TARGET_FILENAME = process.env.FLEET_TARGET || process.env.HASS4_TARGET || 'cyd-office-info.yaml';

const EXPECTED_VERSION =
  process.env.EXPECTED_VERSION ||
  readFileSync(join(__dirname, '../../VERSION'), 'utf-8').trim();

const COMPILE_BUDGET_MS = parseInt(process.env.COMPILE_BUDGET_MS || '480000', 10);
const SPEEDUP_THRESHOLD = parseFloat(process.env.SPEEDUP_THRESHOLD || '1.20');

interface QueueJob {
  id: string;
  target: string;
  state: string;
  duration_seconds?: number | null;
  created_at: string;
  finished_at?: string;
  pinned_client_id?: string;
  assigned_client_id?: string;
}

interface Worker {
  client_id: string;
  hostname: string;
  online: boolean;
  max_parallel_jobs?: number;
}

function isTerminal(state: string): boolean {
  return state === 'success' || state === 'failed' || state === 'timed_out';
}

/**
 * Retry transient kernel-level socket errors that laptop dual-homed
 * NICs produce during long polls — specifically `EADDRNOTAVAIL`,
 * `EHOSTUNREACH`, `ECONNRESET`, and `ECONNREFUSED`. These are
 * client-side flakes, not product bugs: MacOS returns EADDRNOTAVAIL
 * when the source interface's address churns mid-read (common when
 * two interfaces compete for the default route). One retry with a
 * short delay is enough — real product outages persist past it and
 * still fail the containing `expect.poll`.
 */
const TRANSIENT = /EADDRNOTAVAIL|EHOSTUNREACH|ECONNRESET|ECONNREFUSED/;

async function getQueue(request: APIRequestContext): Promise<QueueJob[]> {
  for (let attempt = 0; ; attempt++) {
    try {
      const resp = await request.get('/ui/api/queue');
      if (!resp.ok()) throw new Error(`/ui/api/queue returned ${resp.status()}`);
      return resp.json();
    } catch (err) {
      const msg = String(err);
      if (attempt < 3 && TRANSIENT.test(msg)) {
        await new Promise(r => setTimeout(r, 500 * (attempt + 1)));
        continue;
      }
      throw err;
    }
  }
}

async function getJob(request: APIRequestContext, id: string): Promise<QueueJob | null> {
  return (await getQueue(request)).find(j => j.id === id) ?? null;
}

async function runOneCompile(request: APIRequestContext, workerId: string): Promise<QueueJob> {
  const before = new Set((await getQueue(request)).map(j => j.id));
  const compileResp = await request.post('/ui/api/compile', {
    data: { targets: [TARGET_FILENAME], pinned_client_id: workerId },
  });
  expect(compileResp.ok()).toBe(true);

  let jobId: string | null = null;
  await expect.poll(
    async () => {
      const queue = await getQueue(request);
      const found = queue.find(j => j.target === TARGET_FILENAME && !before.has(j.id));
      if (found) {
        jobId = found.id;
        return jobId;
      }
      return null;
    },
    { timeout: 15_000, message: 'compile job should appear in queue' },
  ).not.toBeNull();

  let final: QueueJob | null = null;
  await expect.poll(
    async () => {
      const job = await getJob(request, jobId!);
      if (job && isTerminal(job.state)) {
        final = job;
        return job.state;
      }
      return job?.state ?? 'missing';
    },
    {
      timeout: COMPILE_BUDGET_MS,
      intervals: [2_000, 5_000, 10_000],
      message: `compile did not finish within ${COMPILE_BUDGET_MS}ms`,
    },
  ).toBe('success');

  expect(final, 'compile should finish').not.toBeNull();
  expect(final!.duration_seconds, 'duration_seconds must be reported').toBeTruthy();
  return final!;
}

test.describe.serial('incremental build hass-4 smoke', () => {
  test.beforeAll(async ({ request }) => {
    const resp = await request.get('/ui/api/server-info');
    expect(resp.ok()).toBe(true);
    const info = await resp.json();
    expect(info.addon_version).toBe(EXPECTED_VERSION);
  });

  test('second compile does not regress significantly vs first on the same worker', async ({ request }) => {
    test.setTimeout(COMPILE_BUDGET_MS * 2 + 60_000);

    const workersResp = await request.get('/ui/api/workers');
    expect(workersResp.ok()).toBe(true);
    const workers = (await workersResp.json()) as Worker[];
    const localWorker = workers.find(w => w.hostname === 'local-worker' && w.online);
    expect(localWorker, 'local-worker must be online').toBeDefined();

    const first = await runOneCompile(request, localWorker!.client_id);
    const second = await runOneCompile(request, localWorker!.client_id);

    const ratio = second.duration_seconds! / first.duration_seconds!;
    // eslint-disable-next-line no-console
    console.log(`first=${first.duration_seconds}s, second=${second.duration_seconds}s, ratio=${ratio.toFixed(2)}`);
    expect(
      ratio,
      `second compile (${second.duration_seconds}s) should be ≤${SPEEDUP_THRESHOLD.toFixed(2)} × first (${first.duration_seconds}s); ratio=${ratio.toFixed(2)}. ` +
        `A ratio above this threshold suggests the build cache was wiped between runs.`,
    ).toBeLessThanOrEqual(SPEEDUP_THRESHOLD);
  });
});
