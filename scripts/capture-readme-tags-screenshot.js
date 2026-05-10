/* Sibling to capture-readme-screenshot.js — refreshes the second
   README hero image (docs/screenshot-tags.png), the "fleet tags +
   tag filter pills" view of the Devices tab. No drawer open; the
   point is to show tag chips on rows + the filter pill bar.

   Usage:
     PW_TOKEN=$(ssh root@hass-4.local \
       "python3 -c 'import json; print(json.load(open(\"/usr/share/hassio/addons/data/local_esphome_dist_server/settings.json\"))[\"server_token\"])'") \
       node scripts/capture-readme-tags-screenshot.js
     cp /tmp/screenshot-tags.png docs/screenshot-tags.png
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
  await context.addInitScript((token) => {
    sessionStorage.setItem('ingressAuthToken', `Bearer ${token}`);
  }, TOKEN);
  const page = await context.newPage();

  await page.goto(`${BASE}/`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForSelector('.device-name, tbody tr', { timeout: 15000 });
  // Let SWR settle so tag chips are populated rather than flickering in.
  await page.waitForTimeout(1500);

  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);

  await page.screenshot({ path: '/tmp/screenshot-tags.png', fullPage: false });
  console.log('Wrote /tmp/screenshot-tags.png');
  await browser.close();
})().catch(err => {
  console.error(err);
  process.exit(1);
});
