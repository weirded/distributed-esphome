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
 * #83: cron expressions used to be stored in UTC. This helper converts the
 * UTC hour+minute to the user's local timezone for display. As of #90, new
 * schedules are tz-aware (stored with a `schedule_tz` field), so this helper
 * is only invoked for legacy schedules without that field.
 */
function _cronUtcToLocal(utcHour: number, utcMinute: number, utcDow?: number): { hour: number; minute: number; dow: number } {
  const d = new Date();
  if (utcDow !== undefined) {
    const daysAhead = ((utcDow - d.getUTCDay()) % 7 + 7) % 7;
    d.setUTCDate(d.getUTCDate() + daysAhead);
  }
  d.setUTCHours(utcHour, utcMinute, 0, 0);
  return { hour: d.getHours(), minute: d.getMinutes(), dow: d.getDay() };
}

/**
 * #89: convert a cron expression's hour (and possibly day-of-week) field
 * between local time and UTC. Cron is stored in UTC server-side; the user
 * thinks in local time.
 *
 * Handles the common case: simple integer hour and (optional) integer dow.
 * Other fields (minute, dom, month) are timezone-agnostic and pass through.
 * If the hour or dow field is anything more exotic (range, list, step,
 * wildcard), `cronTimeShift()` returns the cron unchanged and `complex: true`
 * — those expressions are stored verbatim and the user is shown a note.
 */
function _shiftCron(cron: string, mode: 'localToUtc' | 'utcToLocal'): { cron: string; complex: boolean } {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return { cron, complex: false };
  const [min, hour, dom, mon, dow] = parts;
  const minNum = parseInt(min, 10);
  const hourNum = parseInt(hour, 10);
  // Min must be a simple integer; hour must be a simple integer.
  if (isNaN(minNum) || String(minNum) !== min) return { cron, complex: true };
  if (isNaN(hourNum) || String(hourNum) !== hour) return { cron, complex: true };

  // Build a reference Date with the source-side hour/minute, then read it
  // back in the target timezone to learn how the day shifted.
  const ref = new Date();
  ref.setHours(0, 0, 0, 0);
  if (mode === 'localToUtc') {
    ref.setHours(hourNum, minNum);
    const newHour = ref.getUTCHours();
    const newMin = ref.getUTCMinutes();
    const dayShift = ref.getUTCDate() - ref.getDate();
    return _withShift(newMin, newHour, dom, mon, dow, dayShift, 'localToUtc');
  } else {
    ref.setUTCHours(hourNum, minNum);
    const newHour = ref.getHours();
    const newMin = ref.getMinutes();
    const dayShift = ref.getDate() - ref.getUTCDate();
    return _withShift(newMin, newHour, dom, mon, dow, dayShift, 'utcToLocal');
  }
}

function _withShift(
  newMin: number, newHour: number, dom: string, mon: string, dow: string,
  dayShift: number, mode: 'localToUtc' | 'utcToLocal',
): { cron: string; complex: boolean } {
  if (dow === '*' || dayShift === 0) {
    return { cron: `${newMin} ${newHour} ${dom} ${mon} ${dow}`, complex: false };
  }
  const dowNum = parseInt(dow, 10);
  if (isNaN(dowNum) || String(dowNum) !== dow) {
    // Day-shifted but dow is complex (range/list) — can't safely rewrite.
    void mode;
    return { cron: `${newMin} ${newHour} ${dom} ${mon} ${dow}`, complex: true };
  }
  const newDow = ((dowNum + dayShift) % 7 + 7) % 7;
  return { cron: `${newMin} ${newHour} ${dom} ${mon} ${newDow}`, complex: false };
}

export function localCronToUtc(cron: string): { cron: string; complex: boolean } {
  return _shiftCron(cron, 'localToUtc');
}

export function utcCronToLocal(cron: string): { cron: string; complex: boolean } {
  return _shiftCron(cron, 'utcToLocal');
}

/**
 * Format a 5-field cron expression for display.
 *
 * #90: when `tz` is set, the cron is interpreted in that tz already — render
 * the hour/dow literally. When `tz` is null/undefined, the schedule predates
 * #90 and is interpreted as UTC; convert hour/dow to the user's local zone
 * for display so legacy schedules don't appear time-shifted.
 */
export function formatCronHuman(cron: string | null | undefined, tz?: string | null): string | null {
  if (!cron) return null;
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return cron;
  const [min, hour, dom, _mon, dow] = parts;
  void _mon;

  if (min === '0' && hour.startsWith('*/')) {
    const n = parseInt(hour.slice(2), 10);
    return n === 1 ? 'Hourly' : `Every ${n}h`;
  }
  const renderTime = (h: number, m: number, dowNum?: number) => {
    if (tz) {
      return { hour: h, minute: m, dow: dowNum ?? 0 };
    }
    return _cronUtcToLocal(h, m, dowNum);
  };
  if (dom === '*' && dow === '*' && !hour.includes('/') && !min.includes('/')) {
    const h = parseInt(hour, 10);
    const m = parseInt(min, 10);
    if (isNaN(h) || isNaN(m)) return cron;
    const local = renderTime(h, m);
    return `Daily ${String(local.hour).padStart(2, '0')}:${String(local.minute).padStart(2, '0')}`;
  }
  const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  if (dom === '*' && dow !== '*' && !hour.includes('/')) {
    const h = parseInt(hour, 10);
    const m = parseInt(min, 10);
    const dowNum = parseInt(dow, 10);
    if (isNaN(h) || isNaN(m)) return cron;
    const local = renderTime(h, m, dowNum);
    const day = dayNames[local.dow] ?? dow;
    return `${day} ${String(local.hour).padStart(2, '0')}:${String(local.minute).padStart(2, '0')}`;
  }
  if (dom !== '*' && dow === '*' && !hour.includes('/')) {
    const h = parseInt(hour, 10);
    const m = parseInt(min, 10);
    if (isNaN(h) || isNaN(m)) return cron;
    const local = renderTime(h, m);
    const suffix = dom === '1' ? 'st' : dom === '2' ? 'nd' : dom === '3' ? 'rd' : 'th';
    return `${dom}${suffix} ${String(local.hour).padStart(2, '0')}:${String(local.minute).padStart(2, '0')}`;
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
