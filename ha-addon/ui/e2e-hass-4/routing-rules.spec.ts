import { expect, test, type APIRequestContext } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { retryTransient } from './retry';

const __dirname = dirname(fileURLToPath(import.meta.url));

/**
 * TG.10 — real-HA round-trip of the TG.2/TG.3/TG.4 routing-rule pipeline.
 *
 * What the test does, end-to-end:
 *   1. Tag the test device with ``routing-test`` via ``/ui/api/targets/{
 *      filename}/meta`` (so the YAML metadata comment block carries the
 *      tag and the rule fires for this device).
 *   2. POST a routing rule that fires on ``routing-test`` and requires
 *      the worker to carry a tag no live worker has (``arm9000``). With
 *      no eligible worker, every fresh job enqueued for the device must
 *      land in BLOCKED.
 *   3. Trigger a compile via ``/ui/api/compile`` and assert the new job
 *      reaches ``state: blocked`` with ``blocked_reason.rule_id``
 *      pointing at our rule.
 *   4. DELETE the rule. The server's ``re_evaluate_routing`` sweep flips
 *      the BLOCKED job back to PENDING and an online worker claims it.
 *      Wait for the job to reach a terminal state (success | failed |
 *      timed_out) and assert it's success — the same compile that was
 *      blocked a moment ago now runs to completion.
 *   5. Cleanup: drop the ``routing-test`` tag from the device.
 *
 * The cleanup hook also drops the rule + tag if the test bailed mid-way
 * so a re-run starts from a clean slate.
 *
 * Skipped on standalone targets via the ``@requires-ha`` tag — the rule
 * itself doesn't need HA, but the test mutates the live fleet state in
 * a way that makes it unsafe to run alongside other smoke specs that
 * are also enqueuing compiles for the same target.
 */

const TARGET_FILENAME = process.env.FLEET_TARGET || process.env.HASS4_TARGET || 'cyd-office-info.yaml';

const EXPECTED_VERSION =
  process.env.EXPECTED_VERSION ||
  readFileSync(join(__dirname, '../../VERSION'), 'utf-8').trim();

const COMPILE_BUDGET_MS = parseInt(process.env.COMPILE_BUDGET_MS || '480000', 10);

const RULE_ID = 'e2e-routing-test';
const TEST_TAG = 'routing-test';
const UNREACHABLE_TAG = 'arm9000';

interface QueueJob {
  id: string;
  target: string;
  state: string;
  created_at: string;
  finished_at?: string;
  ota_result?: string;
  blocked_reason?: { rule_id: string; rule_name: string; summary: string } | null;
}

function isTerminal(state: string): boolean {
  return state === 'success' || state === 'failed' || state === 'timed_out';
}

async function getQueue(request: APIRequestContext): Promise<QueueJob[]> {
  return retryTransient(async () => {
    const resp = await request.get('/ui/api/queue');
    if (!resp.ok()) throw new Error(`/ui/api/queue returned ${resp.status()}`);
    return resp.json();
  });
}

async function getJob(request: APIRequestContext, id: string): Promise<QueueJob | null> {
  return (await getQueue(request)).find(j => j.id === id) ?? null;
}

async function readMeta(request: APIRequestContext, filename: string): Promise<Record<string, unknown>> {
  return retryTransient(async () => {
    const resp = await request.get(`/ui/api/targets/${encodeURIComponent(filename)}/meta`);
    if (!resp.ok()) throw new Error(`meta GET returned ${resp.status()}`);
    return resp.json();
  });
}

async function writeMeta(
  request: APIRequestContext,
  filename: string,
  body: Record<string, unknown>,
): Promise<void> {
  await retryTransient(async () => {
    const resp = await request.post(`/ui/api/targets/${encodeURIComponent(filename)}/meta`, {
      data: body,
    });
    if (!resp.ok()) throw new Error(`meta POST returned ${resp.status()}: ${await resp.text()}`);
  });
}

async function deleteRule(request: APIRequestContext, id: string): Promise<void> {
  // 404 is fine — the rule was already gone (test is partially run).
  await request.delete(`/ui/api/routing-rules/${encodeURIComponent(id)}`);
}

test.describe('TG.10 routing-rule end-to-end', { tag: ['@requires-ha'] }, () => {
  test.beforeAll(async ({ request }) => {
    const resp = await request.get('/ui/api/server-info');
    expect(resp.ok(), `server-info should return 2xx (got ${resp.status()})`).toBe(true);
    const info = await resp.json();
    expect(
      info.addon_version,
      `expected add-on version ${EXPECTED_VERSION}, got ${info.addon_version}`,
    ).toBe(EXPECTED_VERSION);
  });

  test.afterEach(async ({ request }) => {
    // Best-effort cleanup so a flaky run doesn't leave the rule wedged
    // in /data/routing-rules.json across subsequent specs.
    await deleteRule(request, RULE_ID);
    try {
      const meta = await readMeta(request, TARGET_FILENAME);
      const tagsRaw = typeof meta.tags === 'string' ? meta.tags : '';
      const tags = tagsRaw.split(',').map((s: string) => s.trim()).filter(Boolean);
      if (tags.includes(TEST_TAG)) {
        const next = tags.filter(t => t !== TEST_TAG);
        await writeMeta(request, TARGET_FILENAME, { tags: next.length ? next.join(',') : null });
      }
    } catch {
      // Tag-cleanup is best-effort — surface a warning via console so a
      // human can clean up if it kept failing.
      console.warn(`afterEach: failed to clean ${TEST_TAG} tag from ${TARGET_FILENAME}`);
    }
  });

  test('rule blocks compile, deleting the rule unblocks it', async ({ request }) => {
    test.setTimeout(COMPILE_BUDGET_MS + 90_000);

    // 1. Tag the device.
    const initialMeta = await readMeta(request, TARGET_FILENAME);
    const initialTagsRaw = typeof initialMeta.tags === 'string' ? initialMeta.tags : '';
    const initialTags = initialTagsRaw.split(',').map((s: string) => s.trim()).filter(Boolean);
    if (!initialTags.includes(TEST_TAG)) {
      const next = [...initialTags, TEST_TAG].join(',');
      await writeMeta(request, TARGET_FILENAME, { tags: next });
    }

    // 2. Create the rule. Use an explicit id so cleanup is deterministic.
    await deleteRule(request, RULE_ID); // belt-and-suspenders
    const ruleResp = await request.post('/ui/api/routing-rules', {
      data: {
        id: RULE_ID,
        name: 'TG.10 e2e — block until deleted',
        severity: 'required',
        device_match: [{ op: 'all_of', tags: [TEST_TAG] }],
        worker_match: [{ op: 'all_of', tags: [UNREACHABLE_TAG] }],
      },
    });
    expect(
      ruleResp.ok(),
      `create rule returned ${ruleResp.status()}: ${await ruleResp.text()}`,
    ).toBe(true);

    // 3. Snapshot the latest job for the target so we can detect the
    //    new one. Trigger a compile.
    const before = await latestJobIdFor(request, TARGET_FILENAME);
    const compileResp = await request.post('/ui/api/compile', {
      data: { targets: [TARGET_FILENAME] },
    });
    expect(compileResp.ok(), `compile returned ${compileResp.status()}`).toBe(true);

    // 4. New job appears.
    const newId = await expect.poll(
      async () => latestJobIdFor(request, TARGET_FILENAME),
      { timeout: 15_000, message: 'expected a new job for the tagged target' },
    ).not.toBe(before);
    void newId; // unused — we just needed the side-effect

    const jobId = await latestJobIdFor(request, TARGET_FILENAME);
    expect(jobId).toBeTruthy();

    // 5. Job lands in BLOCKED with blocked_reason pointing at the rule.
    //    Server triggers re_evaluate on every enqueue, so the transition
    //    to BLOCKED is synchronous from the queue's POV; allow a small
    //    window for the eligibility sweep to land.
    await expect.poll(
      async () => {
        const job = await getJob(request, jobId!);
        return job?.state ?? 'missing';
      },
      { timeout: 10_000, intervals: [500, 1_000, 2_000], message: 'expected job to land in BLOCKED' },
    ).toBe('blocked');

    const blockedJob = await getJob(request, jobId!);
    expect(blockedJob?.blocked_reason?.rule_id).toBe(RULE_ID);

    // 6. Delete the rule. Re-eval flips the BLOCKED job back to PENDING
    //    and an online worker claims it.
    await deleteRule(request, RULE_ID);

    // PENDING/WORKING is fine — we just want to see it leave BLOCKED.
    await expect.poll(
      async () => {
        const job = await getJob(request, jobId!);
        return job?.state ?? 'missing';
      },
      { timeout: 15_000, intervals: [500, 1_000, 2_000], message: 'expected job to leave BLOCKED after rule delete' },
    ).not.toBe('blocked');

    // 7. Wait for terminal — the unblocked compile should finish
    //    successfully end-to-end (real OTA against the live device).
    let finalJob: QueueJob | null = null;
    await expect.poll(
      async () => {
        const job = await getJob(request, jobId!);
        if (job && isTerminal(job.state)) {
          finalJob = job;
          return job.state;
        }
        return job?.state ?? 'missing';
      },
      {
        timeout: COMPILE_BUDGET_MS,
        intervals: [2_000, 5_000, 10_000],
        message: `unblocked compile did not finish within ${COMPILE_BUDGET_MS}ms`,
      },
    ).toMatch(/^(success|failed|timed_out)$/);

    expect(finalJob, 'final job should be set').not.toBeNull();
    expect(finalJob!.state, `final state: ${finalJob!.state}`).toBe('success');
  });
});

async function latestJobIdFor(
  request: APIRequestContext,
  target: string,
): Promise<string | null> {
  const jobs = await getQueue(request);
  const matching = jobs
    .filter(j => j.target === target)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  return matching[0]?.id ?? null;
}
