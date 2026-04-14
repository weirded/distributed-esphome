import { toast } from 'sonner';
import type { Device, EsphomeVersions, Job, ServerInfo, Target, Worker } from '../types';

// ---------------------------------------------------------------------------
// Response shapes (QS.9)
//
// Named at module top so the wire contract is self-documenting and so callers
// importing them get IntelliSense. Used as the type argument to
// `parseResponse<T>()` instead of inline `as { ... }` casts.
// ---------------------------------------------------------------------------

export interface CompileResponse { enqueued: number }
export interface CancelResponse { cancelled: number }
export interface RetryResponse { retried: number }
export interface RemoveResponse { removed: number }
export interface ClearResponse { cleared: number }
export interface ScheduleResponse { schedule_enabled: boolean }
export interface SaveTargetResponse { renamed_to?: string | null }
export interface CreateTargetResponse { target?: string }
export interface RenameTargetResponse { new_filename: string }
export interface ApiKeyResponse { key?: string }
export interface JobLogResponse { log: string; offset: number; finished: boolean }
export interface ValidateResponse { success?: boolean; output?: string; error?: string }
export interface SecretKeysResponse { keys?: string[] }
export interface EsphomeSchemaResponse { components?: string[] }

// ---------------------------------------------------------------------------
// Response helpers (QS.8 + QS.10)
//
// `parseResponse` does the standard error-handling pattern that was repeated
// ~30 times in this file: parse JSON, throw with the server's `error` message
// when present, fall back to the HTTP status code. Reduces ~150 lines of
// boilerplate and ensures every caller surfaces server-side error detail
// (QS.10 — previously getTargets/getDevices/etc. threw "Failed to fetch X"
// even when the server returned a useful message).
//
// `expectOk` is the bodyless variant — for endpoints that return 200/204 with
// no JSON body that callers care about.
// ---------------------------------------------------------------------------

async function _readError(r: Response, fallback: string): Promise<string> {
  // Try to read the server-provided error string. Falls back to the supplied
  // tag (e.g. "fetching workers") + status code when the body isn't JSON or
  // doesn't contain `error`.
  try {
    const data = await r.json() as { error?: string };
    if (data && typeof data.error === 'string' && data.error) return data.error;
  } catch { /* not JSON or empty body */ }
  return `${fallback} (HTTP ${r.status})`;
}

async function parseResponse<T = unknown>(r: Response, errorTag: string): Promise<T> {
  if (!r.ok) throw new Error(await _readError(r, errorTag));
  return r.json() as Promise<T>;
}

async function expectOk(r: Response, errorTag: string): Promise<void> {
  if (!r.ok) throw new Error(await _readError(r, errorTag));
}

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
  return parseResponse<ServerInfo>(await apiFetch('./ui/api/server-info'), 'fetching server info');
}

export async function getEsphomeVersions(): Promise<EsphomeVersions> {
  return parseResponse<EsphomeVersions>(await apiFetch('./ui/api/esphome-versions'), 'fetching ESPHome versions');
}

export async function setEsphomeVersion(version: string): Promise<void> {
  await expectOk(await apiFetch('./ui/api/esphome-version', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version }),
  }), 'setting ESPHome version');
}

export async function getTargets(): Promise<Target[]> {
  return parseResponse<Target[]>(await apiFetch('./ui/api/targets'), 'fetching targets');
}

export async function getDevices(): Promise<Device[]> {
  return parseResponse<Device[]>(await apiFetch('./ui/api/devices'), 'fetching devices');
}

export async function getWorkers(): Promise<Worker[]> {
  return parseResponse<Worker[]>(await apiFetch('./ui/api/workers'), 'fetching workers');
}

export async function getQueue(): Promise<Job[]> {
  return parseResponse<Job[]>(await apiFetch('./ui/api/queue'), 'fetching queue');
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
): Promise<CompileResponse> {
  const body: Record<string, unknown> = { targets };
  if (pinnedClientId) body.pinned_client_id = pinnedClientId;
  if (esphomeVersion) body.esphome_version = esphomeVersion;
  return parseResponse<CompileResponse>(
    await apiFetch('./ui/api/compile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    'enqueuing compile',
  );
}

export async function cancelJobs(ids: string[]): Promise<CancelResponse> {
  return parseResponse<CancelResponse>(
    await apiFetch('./ui/api/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_ids: ids }),
    }),
    'cancelling jobs',
  );
}

export async function retryJobs(ids: string[] | 'all_failed'): Promise<RetryResponse> {
  return parseResponse<RetryResponse>(
    await apiFetch('./ui/api/retry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_ids: ids }),
    }),
    'retrying jobs',
  );
}

export async function retryAllFailed(): Promise<RetryResponse> {
  return retryJobs('all_failed');
}

export async function removeJobs(ids: string[]): Promise<RemoveResponse> {
  return parseResponse<RemoveResponse>(
    await apiFetch('./ui/api/queue/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    }),
    'removing jobs',
  );
}

export async function clearQueue(
  states: string[],
  requireOtaSuccess?: boolean,
): Promise<ClearResponse> {
  const body: Record<string, unknown> = { states };
  if (requireOtaSuccess) body.require_ota_success = true;
  return parseResponse<ClearResponse>(
    await apiFetch('./ui/api/queue/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    'clearing queue',
  );
}

export async function getTargetContent(filename: string): Promise<string> {
  const data = await parseResponse<{ content?: string }>(
    await apiFetch(`./ui/api/targets/${encodeURIComponent(filename)}/content`),
    'fetching target content',
  );
  return data.content || '';
}

/**
 * Save YAML content to a target file. Returns the final target name,
 * which may differ from *filename* when saving a staged new device
 * (#62 — ``.pending.<name>.yaml`` → ``<name>.yaml`` on first save).
 */
export async function saveTargetContent(
  filename: string,
  content: string,
): Promise<{ renamedTo: string | null }> {
  const data = await parseResponse<SaveTargetResponse>(
    await apiFetch(`./ui/api/targets/${encodeURIComponent(filename)}/content`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }),
    'saving target content',
  );
  return { renamedTo: data.renamed_to ?? null };
}

export async function disableWorker(id: string, disabled: boolean): Promise<void> {
  await expectOk(await apiFetch(`./ui/api/workers/${id}/disable`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ disabled }),
  }), 'updating worker');
}

export async function setWorkerParallelJobs(id: string, maxParallelJobs: number): Promise<void> {
  await expectOk(await apiFetch(`./ui/api/workers/${id}/parallel-jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ max_parallel_jobs: maxParallelJobs }),
  }), 'setting worker parallel-jobs');
}

export async function cleanWorkerCache(id: string): Promise<void> {
  await expectOk(
    await apiFetch(`./ui/api/workers/${id}/clean`, { method: 'POST' }),
    'cleaning worker cache',
  );
}

export async function removeWorker(id: string): Promise<void> {
  await expectOk(
    await apiFetch(`./ui/api/workers/${id}`, { method: 'DELETE' }),
    'removing worker',
  );
}

export async function getJobLog(jobId: string, offset: number): Promise<JobLogResponse> {
  return parseResponse<JobLogResponse>(
    await apiFetch(`./ui/api/jobs/${jobId}/log?offset=${offset}`),
    'fetching job log',
  );
}

export async function getApiKey(filename: string): Promise<string> {
  // Fetched separately rather than via parseResponse because the success
  // branch needs to validate the `key` field is actually present (QS.4).
  const r = await apiFetch(`./ui/api/targets/${encodeURIComponent(filename)}/api-key`);
  const data = await parseResponse<ApiKeyResponse>(r, 'fetching API key');
  if (!data.key) throw new Error('Server did not return an API key');
  return data.key;
}

/**
 * Validate a target's config via ``esphome config`` (direct subprocess on
 * the server). Returns immediately with the output — no queue, no polling.
 *
 * Bug #25: previously this enqueued a validate-only job on the queue and
 * any worker could pick it up; now it runs directly on the server.
 */
export async function validateConfig(target: string): Promise<{ success: boolean; output: string }> {
  // Bespoke handling: validate may return non-OK status with a useful `output`
  // body (e.g. "config has 3 errors..."). We fall through to .output on error.
  const r = await apiFetch('./ui/api/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target }),
  });
  const data = await r.json() as ValidateResponse;
  if (!r.ok) throw new Error(data.error || data.output || `validation failed (HTTP ${r.status})`);
  return { success: !!data.success, output: data.output || '' };
}

export async function getSecretKeys(): Promise<string[]> {
  const r = await apiFetch('./ui/api/secret-keys');
  if (!r.ok) return [];
  const data = await r.json() as SecretKeysResponse;
  return data.keys || [];
}

export async function getEsphomeSchema(): Promise<string[]> {
  const r = await apiFetch('./ui/api/esphome-schema');
  if (!r.ok) return [];
  const data = await r.json() as EsphomeSchemaResponse;
  return data.components || [];
}

export interface ArchivedConfig {
  filename: string;
  size: number;
  archived_at: number;
}

export async function getArchivedConfigs(): Promise<ArchivedConfig[]> {
  return parseResponse<ArchivedConfig[]>(
    await apiFetch('./ui/api/archive'),
    'fetching archived configs',
  );
}

export async function restoreArchivedConfig(filename: string): Promise<void> {
  await expectOk(
    await apiFetch(`./ui/api/archive/${encodeURIComponent(filename)}/restore`, { method: 'POST' }),
    'restoring archived config',
  );
}

export async function deleteArchivedConfig(filename: string): Promise<void> {
  await expectOk(
    await apiFetch(`./ui/api/archive/${encodeURIComponent(filename)}`, { method: 'DELETE' }),
    'deleting archived config',
  );
}

/**
 * Create a new YAML target (CD.3). Without ``source``, creates a minimal
 * stub YAML. With ``source``, duplicates the source file and rewrites
 * ``esphome.name`` to the new filename. Returns the created target name,
 * which is staged as ``.pending.<name>.yaml`` until the first save promotes
 * it to ``<name>.yaml`` (#62). Cancelling the editor deletes the dotfile.
 */
export async function createTarget(
  filename: string,
  source?: string,
): Promise<string> {
  const body: Record<string, string> = { filename };
  if (source) body.source = source;
  const data = await parseResponse<CreateTargetResponse>(
    await apiFetch('./ui/api/targets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    'creating target',
  );
  if (!data.target) throw new Error('Server did not return a target name');
  return data.target;
}

export async function deleteTarget(filename: string, archive = true): Promise<void> {
  await expectOk(
    await apiFetch(
      `./ui/api/targets/${encodeURIComponent(filename)}?archive=${archive}`,
      { method: 'DELETE' },
    ),
    'deleting target',
  );
}

export async function restartDevice(filename: string): Promise<void> {
  await expectOk(
    await apiFetch(
      `./ui/api/targets/${encodeURIComponent(filename)}/restart`,
      { method: 'POST' },
    ),
    'restarting device',
  );
}

export async function renameTarget(
  filename: string,
  newName: string,
): Promise<RenameTargetResponse> {
  return parseResponse<RenameTargetResponse>(
    await apiFetch(
      `./ui/api/targets/${encodeURIComponent(filename)}/rename`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_name: newName }),
      },
    ),
    'renaming target',
  );
}

// ---------------------------------------------------------------------------
// Per-device metadata + schedule
// ---------------------------------------------------------------------------

export async function updateTargetMeta(
  filename: string,
  meta: Record<string, unknown>,
): Promise<void> {
  await expectOk(await apiFetch(
    `./ui/api/targets/${encodeURIComponent(filename)}/meta`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(meta),
    },
  ), 'updating target metadata');
}

export async function setTargetSchedule(
  filename: string,
  cron: string,
  tz?: string,
): Promise<ScheduleResponse> {
  const data = await parseResponse<Partial<ScheduleResponse>>(
    await apiFetch(
      `./ui/api/targets/${encodeURIComponent(filename)}/schedule`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(tz ? { cron, tz } : { cron }),
      },
    ),
    'setting schedule',
  );
  return { schedule_enabled: data.schedule_enabled ?? true };
}

export async function deleteTargetSchedule(filename: string): Promise<void> {
  await expectOk(
    await apiFetch(
      `./ui/api/targets/${encodeURIComponent(filename)}/schedule`,
      { method: 'DELETE' },
    ),
    'deleting schedule',
  );
}

export async function toggleTargetSchedule(filename: string): Promise<ScheduleResponse> {
  const data = await parseResponse<Partial<ScheduleResponse>>(
    await apiFetch(
      `./ui/api/targets/${encodeURIComponent(filename)}/schedule/toggle`,
      { method: 'POST' },
    ),
    'toggling schedule',
  );
  return { schedule_enabled: data.schedule_enabled ?? false };
}

// ---------------------------------------------------------------------------
// Version pinning
// ---------------------------------------------------------------------------

export async function pinTargetVersion(filename: string, version: string): Promise<void> {
  await expectOk(await apiFetch(
    `./ui/api/targets/${encodeURIComponent(filename)}/pin`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version }),
    },
  ), 'pinning version');
}

export async function unpinTargetVersion(filename: string): Promise<void> {
  await expectOk(
    await apiFetch(
      `./ui/api/targets/${encodeURIComponent(filename)}/pin`,
      { method: 'DELETE' },
    ),
    'unpinning version',
  );
}

export async function setTargetScheduleOnce(filename: string, datetime: string): Promise<void> {
  await expectOk(await apiFetch(
    `./ui/api/targets/${encodeURIComponent(filename)}/schedule/once`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ datetime }),
    },
  ), 'setting one-time schedule');
}

export interface ScheduleHistoryEntry {
  fired_at: string;
  job_id: string;
  outcome: string;
}

export async function getScheduleHistory(): Promise<Record<string, ScheduleHistoryEntry[]>> {
  const r = await apiFetch('./ui/api/schedule-history');
  if (!r.ok) return {};
  return r.json() as Promise<Record<string, ScheduleHistoryEntry[]>>;
}
