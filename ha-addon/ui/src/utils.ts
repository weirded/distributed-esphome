export function stripYaml(s: string | undefined | null): string {
  return s ? s.replace(/\.ya?ml$/i, '') : (s ?? '');
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
  ota_result?: string;
  status_text?: string;
}): { label: string; cls: string } {
  if (job.state === 'pending' && job.ota_only) {
    return { label: 'OTA Retry', cls: 'badge badge-timed_out' };
  } else if (job.state === 'pending') {
    return { label: 'Pending', cls: 'badge badge-pending' };
  } else if (job.state === 'working') {
    return { label: job.status_text || 'Working', cls: 'badge badge-working' };
  } else if (job.state === 'failed') {
    return { label: 'Failed', cls: 'badge badge-failed' };
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
