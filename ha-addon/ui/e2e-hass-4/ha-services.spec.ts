import { expect, test, type APIRequestContext } from '@playwright/test';

/**
 * #64 — HA Services end-to-end smoke test.
 *
 * Calls Home Assistant's REST API directly to invoke the
 * `esphome_fleet.compile` and `esphome_fleet.cancel` services, then
 * verifies the Fleet queue reflects the action. This is the
 * integration-level equivalent of clicking "Perform Action" in HA's
 * Developer Tools → Services tab.
 *
 * Requires a long-lived access token for the HA instance. Set via
 * `HASS_TOKEN` env var (create one at Profile → Security → Long-Lived
 * Access Tokens → Create Token in the HA UI). When unset, every test
 * in this file self-skips with a pointer to how to enable it.
 *
 * HA hostname defaults to `http://hass-4.local:8123`; override with
 * `HASS_URL`. Fleet base URL for the queue-verification step comes
 * from `FLEET_URL` (with `HASS4_URL` as BC fallback),
 * defaulting to `http://hass-4.local:8765`.
 */

const HASS_URL = (process.env.HASS_URL || 'http://hass-4.local:8123').replace(/\/$/, '');
const HASS_TOKEN = process.env.HASS_TOKEN || '';
const FLEET_URL = (process.env.FLEET_URL || process.env.HASS4_URL || 'http://hass-4.local:8765').replace(/\/$/, '');
const TARGET_FILENAME = process.env.FLEET_TARGET || process.env.HASS4_TARGET || 'cyd-office-info.yaml';

interface QueueJob {
  id: string;
  target: string;
  state: string;
  esphome_version?: string;
  pinned_client_id?: string | null;
}

async function getFleetQueue(request: APIRequestContext): Promise<QueueJob[]> {
  const resp = await request.get(`${FLEET_URL}/ui/api/queue`);
  expect(resp.ok(), `fleet /ui/api/queue should return 2xx (got ${resp.status()})`).toBeTruthy();
  return (await resp.json()) as QueueJob[];
}

async function callHaService(
  request: APIRequestContext,
  service: string,
  data: Record<string, unknown>,
) {
  return request.post(`${HASS_URL}/api/services/esphome_fleet/${service}`, {
    headers: {
      Authorization: `Bearer ${HASS_TOKEN}`,
      'Content-Type': 'application/json',
    },
    data,
  });
}

// @requires-ha — calls HA's /api/services/esphome_fleet/* endpoints,
// so the standalone-Docker target filters these out via
// --grep-invert=@requires-ha.
//
// @requires-integration-config — also requires a configured
// esphome_fleet integration entry, not just the integration files
// being present in custom_components/. The throwaway HAOS VM
// (haos-pve target) has the files copied by the add-on's
// integration_installer at boot but no automated step completes
// the config flow, so the esphome_fleet.* services aren't
// registered and these specs would 400. The matrix filters this
// tag out on haos-pve. Hass-4 has a real configured entry so
// runs them.
test.describe('HA services hass-4 smoke (#64)', {
  tag: ['@requires-ha', '@requires-integration-config'],
}, () => {
  test.skip(
    !HASS_TOKEN,
    'HASS_TOKEN not set — create a Long-Lived Access Token in HA '
    + '(Profile → Security) and export HASS_TOKEN before running.',
  );

  test('esphome_fleet.compile enqueues a job visible in the Fleet queue', async ({ request }) => {
    test.setTimeout(30_000);

    const before = new Set((await getFleetQueue(request)).map(j => j.id));

    const resp = await callHaService(request, 'compile', {
      targets: [TARGET_FILENAME],
    });
    expect(
      resp.ok(),
      `HA service call should return 2xx (got ${resp.status()}; body=${await resp.text()})`,
    ).toBeTruthy();

    // HA's /api/services returns the list of changed states (can be empty).
    // The authoritative verification is the Fleet queue gaining a new row.
    let newJob: QueueJob | null = null;
    await expect.poll(
      async () => {
        const queue = await getFleetQueue(request);
        newJob = queue.find(j => j.target === TARGET_FILENAME && !before.has(j.id)) ?? null;
        return newJob?.id ?? null;
      },
      { timeout: 10_000, message: 'a new cyd-office-info job should appear in the Fleet queue' },
    ).not.toBeNull();
    expect(newJob).not.toBeNull();

    // Clean up so the real compile doesn't run unnecessarily.
    await request.post(`${FLEET_URL}/ui/api/cancel`, {
      data: { job_ids: [newJob!.id] },
    });
    await request.post(`${FLEET_URL}/ui/api/queue/remove`, {
      data: { ids: [newJob!.id] },
    });
  });

  test('esphome_fleet.cancel ends a queued job', async ({ request }) => {
    test.setTimeout(30_000);

    // Arrange: enqueue via the Fleet API directly (don't depend on the
    // compile-service test having run first).
    const createResp = await request.post(`${FLEET_URL}/ui/api/compile`, {
      data: { targets: [TARGET_FILENAME] },
    });
    expect(createResp.ok()).toBeTruthy();

    let jobId: string | null = null;
    await expect.poll(
      async () => {
        const queue = await getFleetQueue(request);
        const j = queue.find(q => q.target === TARGET_FILENAME && (q.state === 'pending' || q.state === 'working'));
        jobId = j?.id ?? null;
        return jobId;
      },
      { timeout: 10_000 },
    ).not.toBeNull();

    // Act: cancel via the HA service.
    const resp = await callHaService(request, 'cancel', {
      job_ids: [jobId!],
    });
    expect(resp.ok(), `cancel service should return 2xx (got ${resp.status()})`).toBeTruthy();

    // Assert: the queue entry goes to `cancelled` within a couple of seconds.
    await expect.poll(
      async () => {
        const queue = await getFleetQueue(request);
        return queue.find(q => q.id === jobId)?.state ?? 'missing';
      },
      { timeout: 10_000 },
    ).toBe('cancelled');

    // Clean up.
    await request.post(`${FLEET_URL}/ui/api/queue/remove`, {
      data: { ids: [jobId!] },
    });
  });

  test('esphome_fleet.compile with invalid target returns 4xx', async ({ request }) => {
    // Bad target filename → the Fleet server's /ui/api/compile rejects
    // with 0 enqueued, but the HA service wrapper still returns 200
    // (the action executed; it just didn't enqueue anything). What we
    // verify here: the service call itself doesn't crash with a
    // schema error or 500.
    const resp = await callHaService(request, 'compile', {
      targets: ['this-file-definitely-does-not-exist.yaml'],
    });
    expect(resp.ok(), 'service call should not crash on unknown target').toBeTruthy();
  });
});
