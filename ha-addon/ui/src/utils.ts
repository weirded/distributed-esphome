export function timeAgo(isoString: string): string {
  const ago = Math.round((Date.now() - new Date(isoString).getTime()) / 1000);
  if (ago < 60) return ago + 's ago';
  if (ago < 3600) return Math.floor(ago / 60) + 'm ago';
  return Math.floor(ago / 3600) + 'h ago';
}

/**
 * Format a 5-field cron expression as a human-readable string.
 *
 * Recognises the preset patterns produced by the UpgradeModal's cron builder:
 * "every Nh", "Daily HH:MM", "<Weekday> HH:MM", "<N>th HH:MM". Falls back to
 * the raw cron string for anything more exotic. Used by the Schedule column
 * in both DevicesTab and SchedulesTab (#40) so both tabs display schedules
 * identically.
 */

/**
 * Format a 5-field cron expression for display.
 *
 * #91: cron is rendered literally — no tz conversion. Schedules with a
 * `schedule_tz` are interpreted in that tz; legacy schedules without one
 * are interpreted as UTC server-side. Callers add a "(<tz>)" qualifier.
 */
export function formatCronHuman(cron: string | null | undefined): string | null {
  if (!cron) return null;
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return cron;
  const [min, hour, dom, _mon, dow] = parts;
  void _mon;

  if (min === '0' && hour.startsWith('*/')) {
    const n = parseInt(hour.slice(2), 10);
    return n === 1 ? 'Hourly' : `Every ${n}h`;
  }
  if (dom === '*' && dow === '*' && !hour.includes('/') && !min.includes('/')) {
    const h = parseInt(hour, 10);
    const m = parseInt(min, 10);
    if (isNaN(h) || isNaN(m)) return cron;
    return `Daily ${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  }
  const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  if (dom === '*' && dow !== '*' && !hour.includes('/')) {
    const h = parseInt(hour, 10);
    const m = parseInt(min, 10);
    const dowNum = parseInt(dow, 10);
    if (isNaN(h) || isNaN(m)) return cron;
    const day = dayNames[dowNum] ?? dow;
    return `${day} ${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  }
  if (dom !== '*' && dow === '*' && !hour.includes('/')) {
    const h = parseInt(hour, 10);
    const m = parseInt(min, 10);
    if (isNaN(h) || isNaN(m)) return cron;
    const suffix = dom === '1' ? 'st' : dom === '2' ? 'nd' : dom === '3' ? 'rd' : 'th';
    return `${dom}${suffix} ${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  }
  return cron;
}

/**
 * Build an absolute URL for a Home Assistant deep-link (#35).
 *
 * When the add-on is loaded via HA Ingress (the primary deployment), the
 * parent window is HA itself, so we use `window.top.location.origin`. When
 * accessed directly on the add-on's port (e.g. http://hass-4.local:8765),
 * we fall back to the same hostname on the default HA port 8123.
 *
 * Returns null if window.top access throws (cross-origin) and we can't
 * derive a reasonable fallback.
 */
export function haDeepLink(path: string): string | null {
  try {
    if (typeof window === 'undefined') return null;
    const top = window.top;
    if (top && top !== window) {
      try {
        return `${top.location.origin}${path}`;
      } catch {
        /* cross-origin parent — fall through */
      }
    }
    const loc = window.location;
    return `${loc.protocol}//${loc.hostname}:8123${path}`;
  } catch {
    return null;
  }
}

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

/** Job is in a terminal failed state (not running, not successful, not cancelled) */
export function isJobFailed(job: { state: string; ota_result?: string }): boolean {
  if (job.state === 'cancelled') return false;
  return !isJobInProgress(job) && !isJobSuccessful(job);
}

export function isJobCancelled(job: { state: string }): boolean {
  return job.state === 'cancelled';
}

/** Job is in a terminal state (not running) */
export function isJobFinished(job: { state: string; ota_result?: string }): boolean {
  return !isJobInProgress(job);
}

/** Job can be retried (any terminal state — failed or successful) */
export function isJobRetryable(job: { state: string; ota_result?: string }): boolean {
  return isJobFinished(job);
}

const BADGE_BASE = 'inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide';
const BADGE_VARIANTS: Record<string, string> = {
  pending:   `${BADGE_BASE} bg-[#374151] text-[#9ca3af]`,
  working:   `${BADGE_BASE} bg-[#1e3a5f] text-[#60a5fa]`,
  success:   `${BADGE_BASE} bg-[#14532d] text-[#4ade80]`,
  failed:    `${BADGE_BASE} bg-[#450a0a] text-[#f87171]`,
  timed_out: `${BADGE_BASE} bg-[#431407] text-[#fb923c]`,
  cancelled: `${BADGE_BASE} bg-[#374151] text-[#9ca3af]`,
};

export function getJobBadge(job: {
  state: string;
  ota_only?: boolean;
  validate_only?: boolean;
  ota_result?: string;
  status_text?: string;
}): { label: string; cls: string } {
  if (job.state === 'pending' && job.validate_only) {
    return { label: 'Validate', cls: BADGE_VARIANTS.pending };
  } else if (job.state === 'pending' && job.ota_only) {
    return { label: 'OTA Retry', cls: BADGE_VARIANTS.timed_out };
  } else if (job.state === 'pending') {
    return { label: 'Pending', cls: BADGE_VARIANTS.pending };
  } else if (job.state === 'working' && job.validate_only) {
    return { label: job.status_text || 'Validating', cls: BADGE_VARIANTS.working };
  } else if (job.state === 'working') {
    return { label: job.status_text || 'Working', cls: BADGE_VARIANTS.working };
  } else if (job.state === 'failed') {
    return { label: 'Failed', cls: BADGE_VARIANTS.failed };
  } else if (job.state === 'success' && job.validate_only) {
    return { label: 'Valid', cls: BADGE_VARIANTS.success };
  } else if (job.state === 'success') {
    if (job.ota_result === 'success') {
      return { label: 'Success', cls: BADGE_VARIANTS.success };
    } else if (job.ota_result === 'failed') {
      return { label: 'OTA Failed', cls: BADGE_VARIANTS.timed_out };
    } else {
      return { label: 'OTA Pending', cls: BADGE_VARIANTS.working };
    }
  } else if (job.state === 'timed_out') {
    return { label: 'Timed Out', cls: BADGE_VARIANTS.timed_out };
  } else if (job.state === 'cancelled') {
    return { label: 'Cancelled', cls: BADGE_VARIANTS.cancelled };
  } else {
    return { label: job.state, cls: BADGE_VARIANTS[job.state] || BADGE_VARIANTS.pending };
  }
}
