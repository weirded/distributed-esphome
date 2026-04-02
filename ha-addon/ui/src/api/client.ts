import type { Device, EsphomeVersions, Job, ServerInfo, Target, Worker } from '../types';

// Version sentinel for auto-reload detection
let _initialAddonVersion: string | null = null;
let _reloadScheduled = false;

type ToastFn = (msg: string, type?: 'info' | 'success' | 'error') => void;
let _toastFn: ToastFn | null = null;

export function setToastFn(fn: ToastFn) {
  _toastFn = fn;
}

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
    _toastFn?.('New server version — reloading...', 'info');
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

export async function compile(targets: string[] | 'all' | 'outdated'): Promise<{ enqueued: number }> {
  const r = await apiFetch('./ui/api/compile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ targets }),
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

export async function validateConfig(target: string): Promise<{ job_id?: string; error?: string }> {
  const r = await apiFetch('./ui/api/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target }),
  });
  const data = await r.json() as { job_id?: string; error?: string };
  if (!r.ok) throw new Error(data.error || String(r.status));
  return data;
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
