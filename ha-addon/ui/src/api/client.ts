import { toast } from 'sonner';
import type { Device, EsphomeVersions, Job, ServerInfo, Target, Worker } from '../types';

// Version sentinel for auto-reload detection
let _initialAddonVersion: string | null = null;
let _reloadScheduled = false;

export function buildWsUrl(path: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const base = document.querySelector('base')?.getAttribute('href') || '/';
  const a = document.createElement('a');
  a.href = base + path;
  return `${proto}//${location.host}${a.pathname}`;
}

export async function apiFetch(path: string, opts: RequestInit = {}): Promise<Response> {
  const r = await fetch(path, opts);
  // Detect server version changes from response header
  const sv = r.headers.get('X-Server-Version');
  if (sv && _initialAddonVersion && sv !== _initialAddonVersion && !_reloadScheduled) {
    _reloadScheduled = true;
    console.log('Server version changed (header):', _initialAddonVersion, '→', sv);
    toast.info('New server version — reloading...');
    setTimeout(() => location.reload(), 1000);
  }
  return r;
}

export function setInitialAddonVersion(version: string) {
  if (_initialAddonVersion === null) {
    _initialAddonVersion = version;
  }
}

export function getInitialAddonVersion(): string | null {
  return _initialAddonVersion;
}

export async function getServerInfo(): Promise<ServerInfo> {
  const r = await apiFetch('./ui/api/server-info');
  if (!r.ok) throw new Error('Failed to fetch server info');
  return r.json();
}

export async function getEsphomeVersions(): Promise<EsphomeVersions> {
  const r = await apiFetch('./ui/api/esphome-versions');
  if (!r.ok) throw new Error('Failed to fetch ESPHome versions');
  return r.json();
}

export async function setEsphomeVersion(version: string): Promise<void> {
  const r = await apiFetch('./ui/api/esphome-version', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version }),
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({})) as { error?: string };
    throw new Error(data.error || String(r.status));
  }
}

export async function getTargets(): Promise<Target[]> {
  const r = await apiFetch('./ui/api/targets');
  if (!r.ok) throw new Error('Failed to fetch targets');
  return r.json();
}

export async function getDevices(): Promise<Device[]> {
  const r = await apiFetch('./ui/api/devices');
  if (!r.ok) throw new Error('Failed to fetch devices');
  return r.json();
}

export async function getWorkers(): Promise<Worker[]> {
  const r = await apiFetch('./ui/api/workers');
  if (!r.ok) throw new Error('Failed to fetch workers');
  return r.json();
}

export async function getQueue(): Promise<Job[]> {
  const r = await apiFetch('./ui/api/queue');
  if (!r.ok) throw new Error('Failed to fetch queue');
  return r.json();
}

/**
 * Trigger a compile run.
 *
 * @param targets       'all', 'outdated', or an explicit list of YAML filenames
 * @param pinnedClientId optional — pin every job to one specific worker
 * @param esphomeVersion optional — override the global default ESPHome version
 *                        for this run only (#16). The server does NOT mutate
 *                        the global default; it just stamps the version onto
 *                        the enqueued jobs.
 */
export async function compile(
  targets: string[] | 'all' | 'outdated',
  pinnedClientId?: string,
  esphomeVersion?: string,
): Promise<{ enqueued: number }> {
  const body: Record<string, unknown> = { targets };
  if (pinnedClientId) body.pinned_client_id = pinnedClientId;
  if (esphomeVersion) body.esphome_version = esphomeVersion;
  const r = await apiFetch('./ui/api/compile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) throw new Error((data as { error?: string }).error || String(r.status));
  return data as { enqueued: number };
}

export async function cancelJobs(ids: string[]): Promise<{ cancelled: number }> {
  const r = await apiFetch('./ui/api/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_ids: ids }),
  });
  const data = await r.json();
  if (!r.ok) throw new Error((data as { error?: string }).error || String(r.status));
  return data as { cancelled: number };
}

export async function retryJobs(ids: string[] | 'all_failed'): Promise<{ retried: number }> {
  const r = await apiFetch('./ui/api/retry', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_ids: ids }),
  });
  const data = await r.json();
  if (!r.ok) throw new Error((data as { error?: string }).error || String(r.status));
  return data as { retried: number };
}

export async function retryAllFailed(): Promise<{ retried: number }> {
  return retryJobs('all_failed');
}

export async function removeJobs(ids: string[]): Promise<{ removed: number }> {
  const r = await apiFetch('./ui/api/queue/remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  });
  const data = await r.json();
  if (!r.ok) throw new Error((data as { error?: string }).error || String(r.status));
  return data as { removed: number };
}

export async function clearQueue(
  states: string[],
  requireOtaSuccess?: boolean,
): Promise<{ cleared: number }> {
  const body: Record<string, unknown> = { states };
  if (requireOtaSuccess) body.require_ota_success = true;
  const r = await apiFetch('./ui/api/queue/clear', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) throw new Error((data as { error?: string }).error || String(r.status));
  return data as { cleared: number };
}

export async function getTargetContent(filename: string): Promise<string> {
  const r = await apiFetch(`./ui/api/targets/${encodeURIComponent(filename)}/content`);
  if (!r.ok) throw new Error(String(r.status));
  const data = await r.json() as { content?: string };
  return data.content || '';
}

export async function saveTargetContent(filename: string, content: string): Promise<void> {
  const r = await apiFetch(`./ui/api/targets/${encodeURIComponent(filename)}/content`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({})) as { error?: string };
    throw new Error(data.error || String(r.status));
  }
}

export async function disableWorker(id: string, disabled: boolean): Promise<void> {
  const r = await apiFetch(`./ui/api/workers/${id}/disable`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ disabled }),
  });
  if (!r.ok) throw new Error('Failed to update worker');
}

export async function setWorkerParallelJobs(id: string, maxParallelJobs: number): Promise<void> {
  const r = await apiFetch(`./ui/api/workers/${id}/parallel-jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ max_parallel_jobs: maxParallelJobs }),
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({})) as { error?: string };
    throw new Error(data.error || String(r.status));
  }
}

export async function cleanWorkerCache(id: string): Promise<void> {
  const r = await apiFetch(`./ui/api/workers/${id}/clean`, { method: 'POST' });
  if (!r.ok) {
    const data = await r.json().catch(() => ({})) as { error?: string };
    throw new Error(data.error || String(r.status));
  }
}

export async function removeWorker(id: string): Promise<void> {
  const r = await apiFetch(`./ui/api/workers/${id}`, { method: 'DELETE' });
  if (!r.ok) {
    const data = await r.json().catch(() => ({})) as { error?: string };
    throw new Error(data.error || String(r.status));
  }
}

export async function getJobLog(
  jobId: string,
  offset: number,
): Promise<{ log: string; offset: number; finished: boolean }> {
  const r = await apiFetch(`./ui/api/jobs/${jobId}/log?offset=${offset}`);
  if (!r.ok) throw new Error(String(r.status));
  return r.json();
}

export async function getApiKey(filename: string): Promise<string> {
  const r = await apiFetch(`./ui/api/targets/${encodeURIComponent(filename)}/api-key`);
  const data = await r.json() as { key?: string; error?: string };
  if (!r.ok) throw new Error(data.error || String(r.status));
  return data.key!;
}

/**
 * Validate a target's config via ``esphome config`` (direct subprocess on
 * the server). Returns immediately with the output — no queue, no polling.
 *
 * Bug #25: previously this enqueued a validate-only job on the queue and
 * any worker could pick it up; now it runs directly on the server.
 */
export async function validateConfig(target: string): Promise<{ success: boolean; output: string }> {
  const r = await apiFetch('./ui/api/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target }),
  });
  const data = await r.json() as { success?: boolean; output?: string; error?: string };
  if (!r.ok) throw new Error(data.error || data.output || String(r.status));
  return { success: !!data.success, output: data.output || '' };
}

export async function getSecretKeys(): Promise<string[]> {
  const r = await apiFetch('./ui/api/secret-keys');
  if (!r.ok) return [];
  const data = await r.json() as { keys?: string[] };
  return data.keys || [];
}

export async function getEsphomeSchema(): Promise<string[]> {
  const r = await apiFetch('./ui/api/esphome-schema');
  if (!r.ok) return [];
  const data = await r.json() as { components?: string[] };
  return data.components || [];
}

export interface ArchivedConfig {
  filename: string;
  size: number;
  archived_at: number;
}

export async function getArchivedConfigs(): Promise<ArchivedConfig[]> {
  const r = await apiFetch('./ui/api/archive');
  return await r.json() as ArchivedConfig[];
}

export async function restoreArchivedConfig(filename: string): Promise<void> {
  const r = await apiFetch(`./ui/api/archive/${encodeURIComponent(filename)}/restore`, { method: 'POST' });
  if (!r.ok) {
    const data = await r.json() as { error?: string };
    throw new Error(data.error || String(r.status));
  }
}

export async function deleteArchivedConfig(filename: string): Promise<void> {
  const r = await apiFetch(`./ui/api/archive/${encodeURIComponent(filename)}`, { method: 'DELETE' });
  if (!r.ok) {
    const data = await r.json() as { error?: string };
    throw new Error(data.error || String(r.status));
  }
}

/**
 * Create a new YAML target (CD.3). Without ``source``, creates a minimal
 * stub YAML. With ``source``, duplicates the source file and rewrites
 * ``esphome.name`` to the new filename. Returns the created target name
 * (e.g. "kitchen.yaml").
 */
export async function createTarget(
  filename: string,
  source?: string,
): Promise<string> {
  const body: Record<string, string> = { filename };
  if (source) body.source = source;
  const r = await apiFetch('./ui/api/targets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({})) as { target?: string; error?: string };
  if (!r.ok) throw new Error(data.error || String(r.status));
  if (!data.target) throw new Error('Server did not return a target name');
  return data.target;
}

export async function deleteTarget(filename: string, archive = true): Promise<void> {
  const r = await apiFetch(
    `./ui/api/targets/${encodeURIComponent(filename)}?archive=${archive}`,
    { method: 'DELETE' },
  );
  if (!r.ok) {
    const data = await r.json().catch(() => ({})) as { error?: string };
    throw new Error(data.error || String(r.status));
  }
}

export async function restartDevice(filename: string): Promise<void> {
  const r = await apiFetch(
    `./ui/api/targets/${encodeURIComponent(filename)}/restart`,
    { method: 'POST' },
  );
  if (!r.ok) {
    const data = await r.json().catch(() => ({})) as { error?: string };
    throw new Error(data.error || String(r.status));
  }
}

export async function renameTarget(
  filename: string,
  newName: string,
): Promise<{ new_filename: string }> {
  const r = await apiFetch(
    `./ui/api/targets/${encodeURIComponent(filename)}/rename`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_name: newName }),
    },
  );
  if (!r.ok) {
    const data = await r.json().catch(() => ({})) as { error?: string };
    throw new Error(data.error || String(r.status));
  }
  return r.json() as Promise<{ new_filename: string }>;
}

// ---------------------------------------------------------------------------
// Per-device metadata + schedule
// ---------------------------------------------------------------------------

export async function updateTargetMeta(
  filename: string,
  meta: Record<string, unknown>,
): Promise<void> {
  const r = await apiFetch(
    `./ui/api/targets/${encodeURIComponent(filename)}/meta`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(meta),
    },
  );
  if (!r.ok) {
    const data = await r.json().catch(() => ({})) as { error?: string };
    throw new Error(data.error || String(r.status));
  }
}

export async function setTargetSchedule(
  filename: string,
  cron: string,
): Promise<{ schedule_enabled: boolean }> {
  const r = await apiFetch(
    `./ui/api/targets/${encodeURIComponent(filename)}/schedule`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cron }),
    },
  );
  const data = await r.json() as { schedule_enabled?: boolean; error?: string };
  if (!r.ok) throw new Error(data.error || String(r.status));
  return { schedule_enabled: data.schedule_enabled ?? true };
}

export async function deleteTargetSchedule(filename: string): Promise<void> {
  const r = await apiFetch(
    `./ui/api/targets/${encodeURIComponent(filename)}/schedule`,
    { method: 'DELETE' },
  );
  if (!r.ok) {
    const data = await r.json().catch(() => ({})) as { error?: string };
    throw new Error(data.error || String(r.status));
  }
}

export async function toggleTargetSchedule(
  filename: string,
): Promise<{ schedule_enabled: boolean }> {
  const r = await apiFetch(
    `./ui/api/targets/${encodeURIComponent(filename)}/schedule/toggle`,
    { method: 'POST' },
  );
  const data = await r.json() as { schedule_enabled?: boolean; error?: string };
  if (!r.ok) throw new Error(data.error || String(r.status));
  return { schedule_enabled: data.schedule_enabled ?? false };
}

// ---------------------------------------------------------------------------
// Version pinning
// ---------------------------------------------------------------------------

export async function pinTargetVersion(
  filename: string,
  version: string,
): Promise<void> {
  const r = await apiFetch(
    `./ui/api/targets/${encodeURIComponent(filename)}/pin`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version }),
    },
  );
  if (!r.ok) {
    const data = await r.json().catch(() => ({})) as { error?: string };
    throw new Error(data.error || String(r.status));
  }
}

export async function unpinTargetVersion(filename: string): Promise<void> {
  const r = await apiFetch(
    `./ui/api/targets/${encodeURIComponent(filename)}/pin`,
    { method: 'DELETE' },
  );
  if (!r.ok) {
    const data = await r.json().catch(() => ({})) as { error?: string };
    throw new Error(data.error || String(r.status));
  }
}

export async function setTargetScheduleOnce(
  filename: string,
  datetime: string,
): Promise<void> {
  const r = await apiFetch(
    `./ui/api/targets/${encodeURIComponent(filename)}/schedule/once`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ datetime }),
    },
  );
  if (!r.ok) {
    const data = await r.json().catch(() => ({})) as { error?: string };
    throw new Error(data.error || String(r.status));
  }
}
