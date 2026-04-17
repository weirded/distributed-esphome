import { expect, test, type APIRequestContext } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));

/**
 * PT.11 — Pinned ESPHome version is honored when bulk-compiling on the real
 * server.
 *
 * Submits a single-target compile via the bulk /ui/api/compile endpoint with
 * an explicit `esphome_version` and asserts the resulting queued job carries
 * that version in its `esphome_version` field — the pin survived the server
 * round-trip and isn't stripped or replaced by the global default. The job
 * is cancelled afterwards so the suite stays fast and doesn't burn an
 * actual compile cycle.
 */

const TARGET_FILENAME = process.env.HASS4_TARGET || 'cyd-office-info.yaml';

const EXPECTED_VERSION =
  process.env.EXPECTED_VERSION ||
  readFileSync(join(__dirname, '../../VERSION'), 'utf-8').trim();

interface QueueJob {
  id: string;
  target: string;
  state: string;
  esphome_version?: string;
  created_at: string;
}

interface EsphomeVersions {
  selected: string | null;
  detected: string | null;
  available: string[];
}

async function getQueue(request: APIRequestContext): Promise<QueueJob[]> {
  const resp = await request.get('/ui/api/queue');
  if (!resp.ok()) throw new Error(`/ui/api/queue returned ${resp.status()}`);
  return resp.json();
}

test.describe.serial('pinned bulk compile hass-4 smoke', () => {
  test.beforeAll(async ({ request }) => {
    const resp = await request.get('/ui/api/server-info');
    expect(resp.ok()).toBe(true);
    const info = await resp.json();
    expect(info.addon_version).toBe(EXPECTED_VERSION);
  });

  test('bulk compile with explicit esphome_version stamps the job', async ({ request }) => {
    test.setTimeout(45_000);

    // Pick a non-default ESPHome version so the test asserts on something
    // the global default would NOT supply on its own. Take the second entry
    // in `available` if it differs from `selected`; fall back to selected.
    const versionsResp = await request.get('/ui/api/esphome-versions');
    expect(versionsResp.ok()).toBe(true);
    const versions = (await versionsResp.json()) as EsphomeVersions;
    const candidate = versions.available.find(v => v !== versions.selected) || versions.selected;
    expect(candidate, 'need at least one ESPHome version to pin to').toBeTruthy();

    const before = new Set((await getQueue(request)).map(j => j.id));

    const compileResp = await request.post('/ui/api/compile', {
      data: {
        targets: [TARGET_FILENAME],
        esphome_version: candidate,
      },
    });
    expect(compileResp.ok(), `compile should accept (got ${compileResp.status()})`).toBe(true);
    const enqueued = (await compileResp.json()) as { enqueued: number };
    expect(enqueued.enqueued).toBeGreaterThan(0);

    // Find the new job for our target.
    let newJob: QueueJob | null = null;
    await expect.poll(
      async () => {
        const queue = await getQueue(request);
        const candidates = queue
          .filter(j => j.target === TARGET_FILENAME && !before.has(j.id))
          .sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
        if (candidates[0]) {
          newJob = candidates[0];
          return candidates[0].id;
        }
        return null;
      },
      { timeout: 15_000, message: 'pinned bulk compile job should appear' },
    ).not.toBeNull();

    expect(newJob, 'new job must be set').not.toBeNull();
    expect(
      newJob!.esphome_version,
      `job.esphome_version should be ${candidate}, got ${newJob!.esphome_version}`,
    ).toBe(candidate);

    // Clean up — we proved the pin survived the round-trip; no need to
    // actually run the compile.
    await request.post('/ui/api/cancel', { data: { job_ids: [newJob!.id] } });
  });
});
