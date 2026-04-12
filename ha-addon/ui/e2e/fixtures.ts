import { type Page } from '@playwright/test';

// C.6: import the canonical TS types from the app and assert each fixture
// against them. A field rename in src/types/index.ts now triggers a TS error
// in the e2e tests, so the contract between mocks and runtime types stays
// in lockstep. Without these annotations the mocks were duck-typed and a
// rename would silently desynchronize them from the real client.
import type {
  ServerInfo,
  EsphomeVersions,
  Target,
  Device,
  Worker,
  Job,
} from '../src/types';

// --- Mock API data ---

export const serverInfo: ServerInfo = {
  token: 'test-token',
  port: 8765,
  addon_version: '1.3.0-dev.4',
  server_client_version: '1.3.0-dev.4',
  min_image_version: '3',
};

export const esphomeVersions: EsphomeVersions = {
  selected: '2026.3.2',
  detected: '2026.3.2',
  available: ['2026.3.2', '2026.2.0', '2026.1.0'],
};

export const targets: Target[] = [
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

export const devices: Device[] = [
  { name: 'living-room', ip_address: '192.168.1.10', online: true, compile_target: 'living-room.yaml' },
  { name: 'bedroom-light', ip_address: '192.168.1.11', online: true, compile_target: 'bedroom-light.yaml' },
  { name: 'garage-door', ip_address: '192.168.1.12', online: false, compile_target: 'garage-door.yaml' },
];

export const workers: Worker[] = [
  {
    client_id: 'worker-1',
    hostname: 'build-server-1',
    online: true,
    disabled: false,
    max_parallel_jobs: 2,
    requested_max_parallel_jobs: null,
    client_version: '1.3.0-dev.4',
    image_version: '2',
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
    last_seen: new Date(Date.now() - 15 * 60_000).toISOString(), // 15 min ago
  },
];

// All job states are exercised so a regression in any badge / row class
// path is caught by the existing Playwright tests. Order: success, failed,
// working, pending, timed_out — covers the full state machine.
export const queue: Job[] = [
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
  {
    id: 'job-004',
    target: 'kitchen.yaml',
    state: 'pending',
    created_at: new Date(Date.now() - 10_000).toISOString(),
  },
  {
    id: 'job-005',
    target: 'office.yaml',
    state: 'timed_out',
    assigned_client_id: 'worker-1',
    assigned_hostname: 'build-server-1',
    created_at: new Date(Date.now() - 900_000).toISOString(),
    duration_seconds: 600,
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
  await page.route('**/ui/api/targets', async (route) => {
    const method = route.request().method();
    if (method === 'POST') {
      // CD.3: create/duplicate. Echo the requested filename back as the
      // canonical target name so the client can open the editor on it.
      let body: { filename?: string; source?: string } = {};
      try {
        body = JSON.parse(route.request().postData() ?? '{}');
      } catch {
        /* empty */
      }
      const raw = (body.filename ?? '').trim();
      const slug = raw.toLowerCase().endsWith('.yaml') ? raw.slice(0, -5) : raw;
      // #62: server returns .pending. prefix; editor strips it for display
      return route.fulfill({ json: { ok: true, target: `.pending.${slug}.yaml` } });
    }
    return route.fulfill({ json: targets });
  });
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
