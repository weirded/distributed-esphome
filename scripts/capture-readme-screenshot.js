/* Bug #17 — canonical README screenshot: Devices tab with the
   History drawer open on cyd-office-info.yaml, diff view selected.
   See dev-plans/RELEASE_CHECKLIST.md → "Canonical shape" for the
   rationale. Intended to be re-run each release to refresh
   docs/screenshot.png with a current render.

   Usage:
     PW_TOKEN=$(ssh root@hass-4.local \
       "python3 -c 'import json; print(json.load(open(\"/usr/share/hassio/addons/data/local_esphome_dist_server/settings.json\"))[\"server_token\"])'") \
       node scripts/capture-readme-screenshot.js
     cp /tmp/screenshot-history-diff.png docs/screenshot.png

   Fleet's direct-port auth: Bearer via extraHTTPHeaders + the
   UI's session-storage pickup. ``?token=`` is the HA LLAT path.
*/
const { chromium } = require('playwright');

const BASE = process.env.PW_URL || 'http://hass-4.local:8765';
const TOKEN = process.env.PW_TOKEN;
if (!TOKEN) {
  console.error('ERROR: set PW_TOKEN (fleet server bearer from /data/settings.json)');
  process.exit(2);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1400, height: 900 },
    extraHTTPHeaders: { Authorization: `Bearer ${TOKEN}` },
  });
  // Pre-seed sessionStorage so the SPA's apiFetch picks up the token
  // for the SWR-driven calls that happen post-load.
  await context.addInitScript((token) => {
    sessionStorage.setItem('ingressAuthToken', `Bearer ${token}`);
  }, TOKEN);
  const page = await context.newPage();

  await page.goto(`${BASE}/`, { waitUntil: 'networkidle', timeout: 30000 });
  // Wait for the Devices tab to render real rows.
  await page.waitForSelector('.device-name, tbody tr', { timeout: 15000 });
  await page.waitForTimeout(1200);

  // Prefer a row we know has history: cyd-office-info is the designated
  // test target on hass-4.
  const targetRow = page.locator('tr').filter({ hasText: 'cyd-office-info' }).first();
  if (await targetRow.count() === 0) {
    console.error('cyd-office-info row not found on Devices tab — bail');
    await page.screenshot({ path: '/tmp/tp-fallback.png' });
    await browser.close();
    process.exit(3);
  }
  const hamburger = targetRow.locator('[aria-label="More actions"]').first();
  await hamburger.click();
  await page.waitForTimeout(300);
  const item = page.getByRole('menuitem', { name: /Config history/ });
  const disabled = await item.getAttribute('aria-disabled');
  if (disabled === 'true') {
    console.error('Config history menu item disabled for cyd-office-info');
    await page.screenshot({ path: '/tmp/tp-fallback.png' });
    await browser.close();
    process.exit(4);
  }
  await item.click();
  // Give the drawer time to populate.
  await page.waitForTimeout(1500);
  // Click the second commit if there are multiple so we get a real diff.
  const commits = page.locator('[role="dialog"] button, [role="listitem"]').filter({
    hasText: /\b[0-9a-f]{6,}\b|ago\b|commit/i,
  });
  const count = await commits.count();
  if (count >= 2) {
    // Try clicking the 2nd entry to load that commit's diff
    try { await commits.nth(1).click({ timeout: 2000 }); } catch { /* may already be active */ }
    await page.waitForTimeout(800);
  }

  await page.screenshot({ path: '/tmp/screenshot-history-diff.png', fullPage: false });
  console.log('Wrote /tmp/screenshot-history-diff.png');
  await browser.close();
})().catch(err => {
  console.error(err);
  process.exit(1);
});
