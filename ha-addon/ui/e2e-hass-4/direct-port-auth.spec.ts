import { expect, request as pwRequest, test } from '@playwright/test';

/**
 * #82 — direct-port auth covers the static UI shell, not just /ui/api/*.
 *
 * Before the fix, `require_ha_auth=true` gated JSON API calls with 401
 * but served the React SPA HTML and Vite JS bundle to anyone on the
 * LAN — an attacker could version-fingerprint the add-on and enumerate
 * the API surface without authenticating.
 *
 * #83 — the default for `require_ha_auth` flipped back to `false` in
 * 1.6.2 (see WORKITEMS-1.6.2.md bug #83), so this test now enables the
 * flag explicitly before the 401 assertions and restores the prior
 * value afterwards. We also assert the content-negotiated 401: browser
 * clients get a styled HTML remediation page, API clients keep JSON.
 *
 * This test asserts: every protected UI path on the direct port
 * returns 401 without a Bearer token (JSON or HTML depending on
 * Accept), and returns 200 when we send the add-on's shared system
 * token.
 *
 * Uses its own `APIRequestContext` created **without** the auth header
 * so `playwright.config.ts`'s `extraHTTPHeaders` Bearer (attached for
 * every other smoke test) doesn't sneak in and turn our 401 assertions
 * into false 200s.
 */

const FLEET_URL = (process.env.FLEET_URL || process.env.HASS4_URL || 'http://hass-4.local:8765').replace(/\/$/, '');
const ADDON_TOKEN = process.env.FLEET_TOKEN || process.env.HASS4_ADDON_TOKEN || '';

const PROTECTED_PATHS = ['/', '/index.html', '/ui/api/server-info'] as const;

// @requires-ha — toggles `require_ha_auth` and asserts unauth requests
// 401. Standalone mode always runs with require_ha_auth=false, so the
// entire premise doesn't apply; the standalone target filters this
// spec out via --grep-invert=@requires-ha.
test.describe('#82 direct-port auth covers the SPA shell', { tag: ['@requires-ha'] }, () => {
  // Dedicated no-auth APIRequestContext for the 401 assertions. The
  // default `request` fixture inherits playwright.config.ts's
  // `extraHTTPHeaders` which carries a Bearer — that would mask the
  // very bug this test file exists to catch.
  let unauth: Awaited<ReturnType<typeof pwRequest.newContext>>;
  // An auth'd context dedicated to toggling require_ha_auth for the
  // duration of this spec so we don't depend on the persisted value.
  let admin: Awaited<ReturnType<typeof pwRequest.newContext>>;
  let prevRequireHaAuth: boolean | null = null;

  test.beforeAll(async () => {
    unauth = await pwRequest.newContext({
      baseURL: FLEET_URL,
      extraHTTPHeaders: {},
    });
    if (ADDON_TOKEN) {
      admin = await pwRequest.newContext({
        baseURL: FLEET_URL,
        extraHTTPHeaders: { Authorization: `Bearer ${ADDON_TOKEN}` },
      });
      const cur = await admin.get('/ui/api/settings');
      expect(cur.ok(), `settings probe should 2xx (got ${cur.status()})`).toBe(true);
      const body = (await cur.json()) as { require_ha_auth?: boolean };
      prevRequireHaAuth = body.require_ha_auth ?? false;
      if (!prevRequireHaAuth) {
        const patch = await admin.patch('/ui/api/settings', {
          data: { require_ha_auth: true },
        });
        expect(patch.ok(), `enable require_ha_auth should 2xx (got ${patch.status()})`).toBe(true);
      }
    }
  });

  test.afterAll(async () => {
    if (admin && prevRequireHaAuth === false) {
      await admin.patch('/ui/api/settings', { data: { require_ha_auth: false } });
    }
    if (admin) await admin.dispose();
    await unauth.dispose();
  });

  for (const path of PROTECTED_PATHS) {
    test(`${path} without auth returns 401`, async () => {
      const resp = await unauth.get(path);
      expect(
        resp.status(),
        `GET ${path} without Bearer should 401 under require_ha_auth=true`,
      ).toBe(401);
      expect(
        resp.headers()['www-authenticate'] || '',
        'WWW-Authenticate header should advertise Bearer realm',
      ).toMatch(/^Bearer/);
    });
  }

  test('/ without auth does NOT leak SPA content', async () => {
    // Default Accept (*/*) → JSON 401 body. Must not contain the
    // SPA shell's root div nor any `<!doctype` from the SPA HTML.
    // #83's HTML 401 page is only served when Accept prefers text/html.
    const resp = await unauth.get('/');
    const body = await resp.text();
    expect(body.toLowerCase()).not.toContain('<!doctype');
    expect(body).not.toContain('id="root"');
  });

  test('/ with Accept: text/html renders the HTML 401 page', async () => {
    // #83: a browser landing on :8765 directly sees a styled
    // remediation page instead of a bare-JSON blob. Must not
    // leak the real SPA shell (`id="root"`), must explain both
    // recovery paths.
    const resp = await unauth.get('/', {
      headers: { Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8' },
    });
    expect(resp.status()).toBe(401);
    expect(resp.headers()['content-type'] || '').toMatch(/^text\/html/);
    const body = await resp.text();
    expect(body.toLowerCase()).toContain('<!doctype html>');
    expect(body).toContain('Authentication required');
    expect(body).toContain('Authorization: Bearer');
    expect(body).not.toContain('id="root"');
  });

  test.describe('with a valid system Bearer', () => {
    test.skip(
      !ADDON_TOKEN,
      'FLEET_TOKEN / HASS4_ADDON_TOKEN not set — push-to-hass-4.sh / push-to-haos.sh / scripts/test-matrix.py export it; run the suite via one of those wrappers to exercise the 200-path.',
    );

    for (const path of PROTECTED_PATHS) {
      test(`${path} with Bearer returns 200`, async () => {
        const resp = await unauth.get(path, {
          headers: { Authorization: `Bearer ${ADDON_TOKEN}` },
        });
        expect(
          resp.status(),
          `GET ${path} with valid Bearer should succeed (got ${resp.status()})`,
        ).toBe(200);
      });
    }

    test('/ with Bearer serves the React SPA shell', async () => {
      const resp = await unauth.get('/', {
        headers: { Authorization: `Bearer ${ADDON_TOKEN}` },
      });
      expect(resp.status()).toBe(200);
      const body = await resp.text();
      expect(body.toLowerCase()).toContain('<!doctype');
      expect(body).toContain('id="root"');
    });
  });
});
