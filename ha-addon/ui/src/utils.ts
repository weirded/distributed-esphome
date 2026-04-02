export function stripYaml(s: string | undefined | null): string {
  return s ? s.replace(/\.ya?ml$/i, '') : (s ?? '');
}

export function fmtDuration(secs: number | null | undefined): string {
  if (secs == null) return '—';
  const s = Math.round(secs);
  if (s < 60) return s + 's';
  return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
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
