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

// #84: typed error so callers can distinguish 401 (session expired) from
// other failures. Previously every non-OK response threw a plain `Error`
// whose message was the only signal — SWR hooks couldn't tell a real
// empty result apart from "you're logged out" and the Devices/Workers/
// Queue tabs ended up rendering "No devices found" after the session
// expired. Keep `Error` as the base so callers that only care about
// `.message` still work unchanged.
export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export function isUnauthorizedError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401;
}

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
  if (!r.ok) throw new ApiError(await _readError(r, errorTag), r.status);
  return r.json() as Promise<T>;
}

async function expectOk(r: Response, errorTag: string): Promise<void> {
  if (!r.ok) throw new ApiError(await _readError(r, errorTag), r.status);
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

// AU.7: when the UI is loaded via direct-port (8765) — e.g. prod smoke
// tests or power users bypassing Ingress — `/ui/api/*` now requires a
// Bearer. If the initial URL carries `?token=X`, stash it in
// sessionStorage and attach it to every api request. When served via
// Ingress, no token arrives, no token is sent, and Supervisor-peer
// trust handles auth. Idempotent: the lookup runs once on first call.
let _authToken: string | null | undefined;
function _getAuthToken(): string | null {
  if (_authToken === undefined) {
    try {
      const url = new URL(window.location.href);
      const tokenFromUrl = url.searchParams.get('token');
      if (tokenFromUrl) {
        sessionStorage.setItem('esphome_fleet_token', tokenFromUrl);
        // Remove ?token=… from the visible URL so the user doesn't bookmark
        // or share a copy with the credential baked in.
        url.searchParams.delete('token');
        window.history.replaceState({}, '', url.toString());
      }
      _authToken = sessionStorage.getItem('esphome_fleet_token');
    } catch {
      _authToken = null;
    }
  }
  return _authToken;
}

export async function apiFetch(path: string, opts: RequestInit = {}): Promise<Response> {
  // Attach the AU.7 Bearer if we have one (direct-port smoke tests,
  // external tooling pasting a `?token=` URL). Ingress access leaves
  // this path a no-op.
  const token = _getAuthToken();
  let finalOpts = opts;
  if (token) {
    const headers = new Headers(opts.headers);
    if (!headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`);
    }
    finalOpts = { ...opts, headers };
  }
  const r = await fetch(path, finalOpts);
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

// AV.3 / AV.4 / AV.5 / AV.6 / AV.11 — per-file history + diff + rollback + manual commit.
export interface FileHistoryEntry {
  hash: string;
  short_hash: string;
  date: number;
  author_name: string;
  author_email: string;
  message: string;
  lines_added: number;
  lines_removed: number;
}

export interface FileStatus {
  has_uncommitted_changes: boolean;
  head_hash: string | null;
  head_short_hash: string | null;
}

export interface CommitResult {
  committed: boolean;
  hash: string | null;
  short_hash: string | null;
  message: string | null;
}

export interface RollbackResult {
  content: string;
  committed: boolean;
  hash: string | null;
  short_hash: string | null;
}

export async function getFileHistory(filename: string, limit = 50, offset = 0): Promise<FileHistoryEntry[]> {
  const qs = `?limit=${limit}&offset=${offset}`;
  return parseResponse<FileHistoryEntry[]>(
    await apiFetch(`./ui/api/files/${encodeURIComponent(filename)}/history${qs}`),
    'fetching file history',
  );
}

export async function getFileStatus(filename: string): Promise<FileStatus> {
  return parseResponse<FileStatus>(
    await apiFetch(`./ui/api/files/${encodeURIComponent(filename)}/status`),
    'fetching file status',
  );
}

export async function getFileContentAt(filename: string, hash?: string | null): Promise<string> {
  const qs = hash ? `?hash=${encodeURIComponent(hash)}` : '';
  const body = await parseResponse<{ content: string }>(
    await apiFetch(`./ui/api/files/${encodeURIComponent(filename)}/content-at${qs}`),
    'fetching file content at commit',
  );
  return body.content;
}

export async function getFileDiff(
  filename: string,
  from?: string | null,
  to?: string | null,
): Promise<string> {
  const params = new URLSearchParams();
  if (from) params.set('from', from);
  if (to) params.set('to', to);
  const qs = params.toString() ? `?${params.toString()}` : '';
  const body = await parseResponse<{ diff: string }>(
    await apiFetch(`./ui/api/files/${encodeURIComponent(filename)}/diff${qs}`),
    'fetching file diff',
  );
  return body.diff;
}

export async function rollbackFile(filename: string, hash: string): Promise<RollbackResult> {
  return parseResponse<RollbackResult>(
    await apiFetch(`./ui/api/files/${encodeURIComponent(filename)}/rollback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hash }),
    }),
    'rolling back file',
  );
}

export async function commitFile(filename: string, message?: string): Promise<CommitResult> {
  return parseResponse<CommitResult>(
    await apiFetch(`./ui/api/files/${encodeURIComponent(filename)}/commit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(message ? { message } : {}),
    }),
    'committing file',
  );
}

// SP.3 — in-app Settings (separate from Supervisor's options.json).
// Keep the shape alphabetical-ish and mirrored from AppSettings in
// ha-addon/server/settings.py. Any rename there is a UI contract change
// — update this interface in the same commit.
export interface AppSettings {
  // #97 + #98: master tristate for the AV.* config-versioning
  // feature. ``'unset'`` = the user hasn't decided yet (show the
  // onboarding modal); ``'on'`` = active; ``'off'`` = explicitly off.
  // Treat anything other than ``'on'`` as disabled when gating UI
  // affordances.
  versioning_enabled: 'on' | 'off' | 'unset';
  auto_commit_on_save: boolean;
  git_author_name: string;
  git_author_email: string;
  job_history_retention_days: number;
  firmware_cache_max_gb: number;
  job_log_retention_days: number;
  // SP.8 — moved from Supervisor options.json in 1.6.
  server_token: string;
  job_timeout: number;
  ota_timeout: number;
  worker_offline_threshold: number;
  device_poll_interval: number;
  require_ha_auth: boolean;
  // #82 — time-of-day presentation. 'auto' defers to the browser's
  // resolved locale; '12h'/'24h' force the format globally.
  time_format: 'auto' | '12h' | '24h';
}

export async function getSettings(): Promise<AppSettings> {
  return parseResponse<AppSettings>(await apiFetch('./ui/api/settings'), 'fetching settings');
}

export async function updateSettings(partial: Partial<AppSettings>): Promise<AppSettings> {
  return parseResponse<AppSettings>(
    await apiFetch('./ui/api/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(partial),
    }),
    'updating settings',
  );
}

export async function getEsphomeVersions(): Promise<EsphomeVersions> {
  return parseResponse<EsphomeVersions>(await apiFetch('./ui/api/esphome-versions'), 'fetching ESPHome versions');
}

export async function refreshEsphomeVersions(): Promise<EsphomeVersions> {
  return parseResponse<EsphomeVersions>(
    await apiFetch('./ui/api/esphome-versions/refresh', { method: 'POST' }),
    'refreshing ESPHome versions',
  );
}

/** SE.8: retry the server-side ESPHome install — wired to the banner's
 * Retry button. Returns immediately; the UI polls /ui/api/server-info
 * for the transition from installing/failed → ready. */
export async function reinstallEsphome(): Promise<void> {
  await expectOk(await apiFetch('./ui/api/esphome/reinstall', { method: 'POST' }),
    'retrying ESPHome install');
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
  downloadOnly?: boolean,
): Promise<CompileResponse> {
  const body: Record<string, unknown> = { targets };
  if (pinnedClientId) body.pinned_client_id = pinnedClientId;
  if (esphomeVersion) body.esphome_version = esphomeVersion;
  if (downloadOnly) body.download_only = true;
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
 *
 * Bug #24: ``commitMessage`` is an optional user-entered subject line
 * that's passed to the auto-commit. When omitted (or auto-commit is
 * off) the server's default ``"save: <file>"`` applies.
 */
export async function saveTargetContent(
  filename: string,
  content: string,
  commitMessage?: string,
): Promise<{ renamedTo: string | null }> {
  const body: Record<string, unknown> = { content };
  if (commitMessage && commitMessage.trim()) body.commit_message = commitMessage.trim();
  const data = await parseResponse<SaveTargetResponse>(
    await apiFetch(`./ui/api/targets/${encodeURIComponent(filename)}/content`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
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

/**
 * WL.3: one-shot hydration snapshot of the server's per-worker log buffer.
 * Returns the raw ANSI-coloured text; live lines after this call arrive
 * via the WS stream, not incremental polling.
 */
export async function getWorkerLogSnapshot(workerId: string): Promise<string> {
  const resp = await apiFetch(`./ui/api/workers/${workerId}/logs`);
  if (!resp.ok) {
    throw new Error(`Fetching worker logs: ${resp.status} ${resp.statusText}`);
  }
  return resp.text();
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
  // CR.5: parsing the body might itself throw (non-JSON on a 500, truncated
  // response, etc.). Isolate the parse so we always surface a meaningful
  // error string rather than a swallowed `SyntaxError: Unexpected token`.
  const r = await apiFetch('./ui/api/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target }),
  });
  let data: ValidateResponse;
  try {
    data = await r.json() as ValidateResponse;
  } catch {
    if (!r.ok) throw new Error(`validation failed (HTTP ${r.status})`);
    throw new Error('validate response was not valid JSON');
  }
  if (!r.ok) throw new Error(data.error || data.output || `validation failed (HTTP ${r.status})`);
  return { success: !!data.success, output: data.output || '' };
}

// CR.5: `getSecretKeys` and `getEsphomeSchema` used to silently return []
// on any error, which looked like "no autocomplete suggestions" to the user
// — the editor appeared to work but autocomplete was dead. Throw instead
// so the SWR `onError` path (QS.7's `logSwrError`) logs it with the key
// attached and the caller can surface a real error state.
export async function getSecretKeys(): Promise<string[]> {
  const r = await apiFetch('./ui/api/secret-keys');
  const data = await parseResponse<SecretKeysResponse>(r, 'getSecretKeys');
  return data.keys || [];
}

export async function getEsphomeSchema(): Promise<string[]> {
  const r = await apiFetch('./ui/api/esphome-schema');
  const data = await parseResponse<EsphomeSchemaResponse>(r, 'getEsphomeSchema');
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

// ---------------------------------------------------------------------------
// JH.4 — Job history (persistent append-only)
// ---------------------------------------------------------------------------

/** One row from the persistent /ui/api/history table. Mirrors the SQL
 *  shape in ha-addon/server/job_history.py — keep in sync. */
export interface JobHistoryEntry {
  id: string;
  target: string;
  state: 'success' | 'failed' | 'cancelled' | 'timed_out';
  // PR #64 review: server's `_triggered_by` in `job_history.py` also
  // emits `'api'` for direct system-token callers (the non-HA bearer
  // path). Type has to include it so the Triggered-badge helpers and
  // filters don't narrow incorrectly.
  triggered_by: 'user' | 'schedule' | 'ha_action' | 'api' | null;
  trigger_detail: string | null;
  download_only: 0 | 1;
  validate_only: 0 | 1;
  pinned_client_id: string | null;
  esphome_version: string | null;
  assigned_client_id: string | null;
  assigned_hostname: string | null;
  /** Epoch seconds (UTC). */
  submitted_at: number | null;
  started_at: number | null;
  finished_at: number | null;
  duration_seconds: number | null;
  ota_result: string | null;
  config_hash: string | null;
  retry_count: number;
  log_excerpt: string | null;
  /** Bug #38: 1 when the job produced firmware. Stays 1 even after the
   *  .bin has been evicted by the firmware budget task — use
   *  `firmware_variants.length > 0` to know whether the binary is
   *  still downloadable right now.
   *
   *  PR #64 review: server always includes this field in the SELECT
   *  projection, so it's required (not optional). Keeping it optional
   *  would force defensive `?? 0` chains in callers and mask contract
   *  regressions if the server ever stops emitting it. */
  has_firmware: 0 | 1;
  /** Bug #38: live list of variants still on disk (e.g. ["factory","ota"]).
   *  Empty when has_firmware is 0, OR when the firmware has been evicted
   *  by the budget enforcer. Drives the Download button's visibility on
   *  history rows. Server always emits a list (possibly empty). */
  firmware_variants: string[];
  /** Bug #8 (1.6.1): worker-selection reason persisted at claim time.
   *  ``null`` on rows that predate the column. */
  selection_reason: string | null;
}

export interface JobHistoryStats {
  total: number;
  success: number;
  failed: number;
  cancelled: number;
  timed_out: number;
  avg_duration_seconds: number | null;
  p95_duration_seconds: number | null;
  last_success_at: number | null;
  last_failure_at: number | null;
  window_days: number;
}

export async function getJobHistory(params: {
  target?: string;
  state?: JobHistoryEntry['state'];
  since?: number;
  /** Bug #49: upper epoch bound for the finished-at window. */
  until?: number;
  limit?: number;
  offset?: number;
  /** Bug #53: column to sort by. Server whitelist enforces valid values. */
  sort?: 'finished_at' | 'started_at' | 'submitted_at' | 'duration_seconds'
    | 'target' | 'state' | 'esphome_version' | 'assigned_hostname' | 'triggered_by';
  /** Bug #53: ``true`` for descending (default). */
  desc?: boolean;
} = {}): Promise<JobHistoryEntry[]> {
  const qs = new URLSearchParams();
  if (params.target) qs.set('target', params.target);
  if (params.state) qs.set('state', params.state);
  if (params.since !== undefined) qs.set('since', String(params.since));
  if (params.until !== undefined) qs.set('until', String(params.until));
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  if (params.offset !== undefined) qs.set('offset', String(params.offset));
  if (params.sort) qs.set('sort', params.sort);
  if (params.desc !== undefined) qs.set('desc', params.desc ? '1' : '0');
  const url = qs.toString() ? `./ui/api/history?${qs}` : './ui/api/history';
  return parseResponse<JobHistoryEntry[]>(await apiFetch(url), 'fetching job history');
}

export async function getJobHistoryStats(params: {
  target?: string;
  window_days?: number;
} = {}): Promise<JobHistoryStats> {
  const qs = new URLSearchParams();
  if (params.target) qs.set('target', params.target);
  if (params.window_days !== undefined) qs.set('window_days', String(params.window_days));
  const url = qs.toString() ? `./ui/api/history/stats?${qs}` : './ui/api/history/stats';
  return parseResponse<JobHistoryStats>(await apiFetch(url), 'fetching job-history stats');
}

export async function getScheduleHistory(): Promise<Record<string, ScheduleHistoryEntry[]>> {
  const r = await apiFetch('./ui/api/schedule-history');
  // CR.5/UI-6: route through parseResponse so SWR's onError path logs
  // the failure with the endpoint name attached, instead of silently
  // reporting an empty map.
  return parseResponse<Record<string, ScheduleHistoryEntry[]>>(r, 'getScheduleHistory');
}
