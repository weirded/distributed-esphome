export function stripYaml(s: string | undefined | null): string {
  return s ? s.replace(/\.ya?ml$/i, '') : (s ?? '');
}

function parseBoolFlag(value: string | null): boolean | null {
  if (value == null) return null;
  const v = value.trim().toLowerCase();
  if (['1', 'true', 'yes', 'on', 'enabled'].includes(v)) return true;
  if (['0', 'false', 'no', 'off', 'disabled'].includes(v)) return false;
  return null;
}

export function isSensitiveModeEnabled(): boolean {
  if (typeof window === 'undefined') return false;

  const keys = [
    'sensitiveMode',
    'sensitive_mode',
    'privacyMode',
    'privacy_mode',
    'hideSensitive',
    'hide_sensitive',
  ];

  for (const key of keys) {
    const fromLocalStorage = parseBoolFlag(window.localStorage.getItem(key));
    if (fromLocalStorage != null) return fromLocalStorage;

    const fromSessionStorage = parseBoolFlag(window.sessionStorage.getItem(key));
    if (fromSessionStorage != null) return fromSessionStorage;
  }

  const dataAttr = parseBoolFlag(
    document.documentElement.getAttribute('data-sensitive-mode') ||
    document.body.getAttribute('data-sensitive-mode'),
  );
  if (dataAttr != null) return dataAttr;

  return document.documentElement.classList.contains('sensitive-mode')
    || document.body.classList.contains('sensitive-mode');
}

export function maskIpAddress(ip: string | undefined | null): string {
  if (!ip) return '—';
  if (ip.includes(':')) return '****:****:****:****';
  if (ip.includes('.')) return '***.***.***.***';
  return '***';
}

export function displayIpAddress(ip: string | undefined | null, sensitiveMode: boolean): string {
  if (!ip) return '—';
  return sensitiveMode ? maskIpAddress(ip) : ip;
}

export function fmtDuration(secs: number | null | undefined): string {
  if (secs == null) return '—';
  const s = Math.round(secs);
  if (s < 60) return s + 's';
  return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
}

/** Job is fully done and successful (compile + OTA both succeeded) */
export function isJobSuccessful(job: { state: string; ota_result?: string }): boolean {
  return job.state === 'success' && job.ota_result === 'success';
}

/** Job is still in progress (not yet reached a terminal state) */
export function isJobInProgress(job: { state: string; ota_result?: string }): boolean {
  if (job.state === 'pending' || job.state === 'working') return true;
  // Compile succeeded but OTA hasn't finished yet
  if (job.state === 'success' && job.ota_result !== 'success' && job.ota_result !== 'failed') return true;
  return false;
}

/** Job is in a terminal failed state (not running, not successful) */
export function isJobFailed(job: { state: string; ota_result?: string }): boolean {
  return !isJobInProgress(job) && !isJobSuccessful(job);
}

/** Job is in a terminal state (not running) */
export function isJobFinished(job: { state: string; ota_result?: string }): boolean {
  return !isJobInProgress(job);
}

/** Job can be retried (terminal and not successful) */
export function isJobRetryable(job: { state: string; ota_result?: string }): boolean {
  return isJobFailed(job);
}

export function getJobBadge(job: {
  state: string;
  ota_only?: boolean;
  validate_only?: boolean;
  ota_result?: string;
  status_text?: string;
}): { label: string; cls: string } {
  if (job.state === 'pending' && job.validate_only) {
    return { label: 'Validate', cls: 'badge badge-pending' };
  } else if (job.state === 'pending' && job.ota_only) {
    return { label: 'OTA Retry', cls: 'badge badge-timed_out' };
  } else if (job.state === 'pending') {
    return { label: 'Pending', cls: 'badge badge-pending' };
  } else if (job.state === 'working' && job.validate_only) {
    return { label: job.status_text || 'Validating', cls: 'badge badge-working' };
  } else if (job.state === 'working') {
    return { label: job.status_text || 'Working', cls: 'badge badge-working' };
  } else if (job.state === 'failed') {
    return { label: 'Failed', cls: 'badge badge-failed' };
  } else if (job.state === 'success' && job.validate_only) {
    return { label: 'Valid', cls: 'badge badge-success' };
  } else if (job.state === 'success') {
    if (job.ota_result === 'success') {
      return { label: 'Success', cls: 'badge badge-success' };
    } else if (job.ota_result === 'failed') {
      return { label: 'OTA Failed', cls: 'badge badge-timed_out' };
    } else {
      return { label: 'OTA Pending', cls: 'badge badge-working' };
    }
  } else if (job.state === 'timed_out') {
    return { label: 'Timed Out', cls: 'badge badge-timed_out' };
  } else {
    return { label: job.state, cls: 'badge badge-' + job.state };
  }
}
