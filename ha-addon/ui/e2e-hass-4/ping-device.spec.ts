import { expect, test } from '@playwright/test';

/**
 * #206 — Ping device live regression. The DM.2 ICMP-ping endpoint
 * silently failed on every HAOS install because the kernel default
 * ``net.ipv4.ping_group_range = 1 0`` disables unprivileged datagram
 * ICMP, and the addon container didn't request ``CAP_NET_RAW`` so the
 * privileged-socket fallback wasn't available either. Fix: ``config.yaml``
 * grants ``NET_RAW`` and the helper tries unprivileged → privileged.
 *
 * This spec hits the real ``/ui/api/targets/<filename>/ping`` endpoint
 * on the deployed addon. Uses ``cyd-office-info.yaml`` (the home-lab
 * test device — see project memory) so we don't have to assume which
 * yaml lives on the running instance. Override via FLEET_TARGET if the
 * topology drifts.
 */

const TARGET_FILENAME = process.env.FLEET_TARGET || process.env.HASS4_TARGET || 'cyd-office-info.yaml';

test.describe('ping device — live ICMP', () => {
  test('POST /ui/api/targets/<f>/ping returns a populated host record', async ({ request }) => {
    test.setTimeout(30_000);
    const resp = await request.post(`./ui/api/targets/${TARGET_FILENAME}/ping`);
    expect(
      resp.ok(),
      `expected /ping to return 2xx (got ${resp.status()}) — body: ${await resp.text()}`,
    ).toBe(true);
    const body = await resp.json() as {
      target: string;
      address: string;
      is_alive: boolean;
      packets_sent: number;
      packets_received: number;
      packet_loss: number;
      min_rtt: number;
      avg_rtt: number;
      max_rtt: number;
      jitter: number;
    };

    // Don't assert is_alive — the test device may legitimately be off
    // when the smoke runs. The bug we're guarding is "endpoint always
    // 500s with SocketPermissionError because the addon has neither
    // unprivileged-ping nor NET_RAW", so a clean 2xx response with the
    // expected shape is what proves the fix landed.
    expect(body.target).toBe(TARGET_FILENAME);
    expect(body.address).toBeTruthy();
    expect(body.packets_sent).toBe(10);
    expect(body.packets_received).toBeGreaterThanOrEqual(0);
    expect(body.packets_received).toBeLessThanOrEqual(10);
    expect(typeof body.is_alive).toBe('boolean');
    expect(typeof body.packet_loss).toBe('number');
    expect(typeof body.min_rtt).toBe('number');
    expect(typeof body.avg_rtt).toBe('number');
    expect(typeof body.max_rtt).toBe('number');
    expect(typeof body.jitter).toBe('number');
  });

  test('Ping modal opens from device hamburger and renders a result', async ({ page }) => {
    test.setTimeout(30_000);
    await page.goto('/');
    const stem = TARGET_FILENAME.replace(/\.ya?ml$/, '');
    const targetRow = page.locator('table tbody tr')
      .filter({ has: page.locator('.device-filename', { hasText: stem }) })
      .first();
    await expect(targetRow).toBeVisible({ timeout: 30_000 });

    const menuTrigger = targetRow.locator('.action-menu-trigger');
    await expect(menuTrigger).toBeVisible();
    await menuTrigger.click();
    await page.getByRole('menuitem', { name: /Ping device/i }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    // Spinner shows briefly while the ping runs (~4s worst-case for
    // an unreachable host). The bug was "modal flips straight to Ping
    // failed with SocketPermissionError"; either Reachable or No
    // response is fine — both prove the endpoint succeeded.
    await expect(
      dialog.getByText(/Reachable|No response/i),
    ).toBeVisible({ timeout: 10_000 });
    await expect(dialog.getByText('Ping failed')).toHaveCount(0);
  });
});
