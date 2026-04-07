import { type Page } from '@playwright/test';

// --- Mock API data ---

export const serverInfo = {
  token: 'test-token',
  port: 8765,
  addon_version: '1.3.0-dev.4',
  server_client_version: '1.3.0-dev.4',
  min_image_version: '1',
};

export const esphomeVersions = {
  selected: '2026.3.2',
  detected: '2026.3.2',
  available: ['2026.3.2', '2026.2.0', '2026.1.0'],
};

export const targets = [
  {
    target: 'living-room.yaml',
    device_name: 'living-room',
    friendly_name: 'Living Room Sensor',
    ip_address: '192.168.1.10',
    running_version: '2026.3.2',
    online: true,
    needs_update: false,
    server_version: '2026.3.2',
    has_api_key: true,
    has_web_server: false,
    area: 'Living Room',
  },
  {
    target: 'bedroom-light.yaml',
    device_name: 'bedroom-light',
    friendly_name: 'Bedroom Light',
    ip_address: '192.168.1.11',
    running_version: '2026.2.0',
    online: true,
    needs_update: true,
    server_version: '2026.3.2',
    has_api_key: false,
    area: 'Bedroom',
  },
  {
    target: 'garage-door.yaml',
    device_name: 'garage-door',
    friendly_name: 'Garage Door',
    ip_address: '192.168.1.12',
    running_version: '2026.3.2',
    online: false,
    needs_update: false,
    server_version: '2026.3.2',
  },
];

export const devices = [
  { name: 'living-room', ip_address: '192.168.1.10', online: true, compile_target: 'living-room.yaml' },
  { name: 'bedroom-light', ip_address: '192.168.1.11', online: true, compile_target: 'bedroom-light.yaml' },
  { name: 'garage-door', ip_address: '192.168.1.12', online: false, compile_target: 'garage-door.yaml' },
];

export const workers = [
  {
    client_id: 'worker-1',
    hostname: 'build-server-1',
    online: true,
    disabled: false,
    max_parallel_jobs: 2,
    requested_max_parallel_jobs: null,
    client_version: '1.3.0-dev.4',
    image_version: '1',
    system_info: {
      os_version: 'Debian 12',
      cpu_model: 'Intel i7-12700',
      cpu_cores: 8,
      total_memory: '32 GB',
      disk_total: '500 GB',
      disk_free: '350 GB',
      disk_used_pct: 30,
    },
  },
  {
    client_id: 'worker-2',
    hostname: 'build-server-2',
    online: false,
    disabled: false,
    max_parallel_jobs: 1,
    client_version: '1.3.0-dev.3',
    image_version: null, // pre-LIB.0 worker
  },
];

export const queue = [
  {
    id: 'job-001',
    target: 'bedroom-light.yaml',
    state: 'success',
    assigned_client_id: 'worker-1',
    assigned_hostname: 'build-server-1',
    created_at: new Date(Date.now() - 600_000).toISOString(),
    duration_seconds: 120,
    ota_result: 'success',
  },
  {
    id: 'job-002',
    target: 'garage-door.yaml',
    state: 'failed',
    assigned_client_id: 'worker-1',
    assigned_hostname: 'build-server-1',
    created_at: new Date(Date.now() - 300_000).toISOString(),
    duration_seconds: 45,
  },
  {
    id: 'job-003',
    target: 'living-room.yaml',
    state: 'working',
    assigned_client_id: 'worker-1',
    assigned_hostname: 'build-server-1',
    created_at: new Date(Date.now() - 60_000).toISOString(),
    status_text: 'Compiling...',
  },
];

const configContent = `esphome:
  name: living-room
  friendly_name: "Living Room Sensor"

esp32:
  board: esp32dev

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

logger:
api:
ota:
`;

// --- Route interceptor ---

export async function mockApi(page: Page) {
  await page.route('**/ui/api/server-info', route =>
    route.fulfill({ json: serverInfo }),
  );
  await page.route('**/ui/api/esphome-versions', route =>
    route.fulfill({ json: esphomeVersions }),
  );
  await page.route('**/ui/api/targets', route =>
    route.fulfill({ json: targets }),
  );
  await page.route('**/ui/api/devices', route =>
    route.fulfill({ json: devices }),
  );
  await page.route('**/ui/api/workers', route =>
    route.fulfill({ json: workers }),
  );
  await page.route('**/ui/api/queue', route =>
    route.fulfill({ json: queue }),
  );
  await page.route('**/ui/api/secret-keys', route =>
    route.fulfill({ json: { keys: ['wifi_ssid', 'wifi_password', 'api_key'] } }),
  );
  await page.route('**/ui/api/esphome-schema', route =>
    route.fulfill({ json: { components: ['wifi', 'logger', 'api', 'ota', 'esp32'] } }),
  );
  await page.route('**/ui/api/targets/*/content', route =>
    route.fulfill({ json: { content: configContent } }),
  );
  await page.route('**/ui/api/compile', route =>
    route.fulfill({ json: { enqueued: 1 } }),
  );
  await page.route('**/ui/api/cancel', route =>
    route.fulfill({ json: { cancelled: 1 } }),
  );
  await page.route('**/ui/api/retry', route =>
    route.fulfill({ json: { retried: 1 } }),
  );
  await page.route('**/ui/api/validate', route =>
    route.fulfill({ json: { job_id: 'validate-001' } }),
  );
  await page.route('**/ui/api/queue/clear', route =>
    route.fulfill({ json: { cleared: 1 } }),
  );
  await page.route('**/ui/api/queue/remove', route =>
    route.fulfill({ json: { removed: 1 } }),
  );
  await page.route('**/ui/api/jobs/*/log*', route =>
    route.fulfill({ json: { log: 'INFO Compiling...\nINFO Done.\n', offset: 100, finished: true } }),
  );
  await page.route('**/ui/api/targets/*/rename', route =>
    route.fulfill({ json: { new_filename: 'renamed.yaml' } }),
  );
  await page.route('**/ui/api/targets/*', route => {
    if (route.request().method() === 'DELETE') {
      return route.fulfill({ status: 200, json: {} });
    }
    return route.fallback();
  });
}
