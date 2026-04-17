import { expect, request as pwRequest, test } from '@playwright/test';

/**
 * #82 — direct-port auth covers the static UI shell, not just /ui/api/*.
 *
 * Before the fix, `require_ha_auth=true` (mandatory since AU.7 in 1.5.0)
 * gated JSON API calls with 401 but served the React SPA HTML and Vite
 * JS bundle to anyone on the LAN — an attacker could version-fingerprint
 * the add-on and enumerate the API surface without authenticating.
 *
 * This test asserts the fix: every protected UI path on the direct port
 * returns 401 without a Bearer token, and returns 200 when we send the
 * add-on's shared system token.
 *
 * Uses its own `APIRequestContext` created **without** the auth header
 * so `playwright.config.ts`'s `extraHTTPHeaders` Bearer (attached for
 * every other smoke test) doesn't sneak in and turn our 401 assertions
 * into false 200s.
 */

const FLEET_URL = (process.env.HASS4_URL || 'http://hass-4.local:8765').replace(/\/$/, '');
const ADDON_TOKEN = process.env.HASS4_ADDON_TOKEN || '';

const PROTECTED_PATHS = ['/', '/index.html', '/ui/api/server-info'] as const;

test.describe('#82 direct-port auth covers the SPA shell', () => {
  // Dedicated no-auth APIRequestContext for the 401 assertions. The
  // default `request` fixture inherits playwright.config.ts's
  // `extraHTTPHeaders` which carries a Bearer — that would mask the
  // very bug this test file exists to catch.
  let unauth: Awaited<ReturnType<typeof pwRequest.newContext>>;
  test.beforeAll(async () => {
    unauth = await pwRequest.newContext({
      baseURL: FLEET_URL,
      extraHTTPHeaders: {},
    });
  });
  test.afterAll(async () => { await unauth.dispose(); });

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

  test('/ without auth does NOT leak HTML content', async () => {
    const resp = await unauth.get('/');
    const body = await resp.text();
    expect(body.toLowerCase()).not.toContain('<!doctype');
    expect(body).not.toContain('id="root"');
  });

  test.describe('with a valid system Bearer', () => {
    test.skip(
      !ADDON_TOKEN,
      'HASS4_ADDON_TOKEN not set — push-to-hass-4.sh exports it; run the suite via that wrapper to exercise the 200-path.',
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
