/**
 * General text/time formatting helpers (QS.23).
 *
 * Split out of the former `src/utils.ts` grab-bag so the job-state predicates
 * and cron-expression helper can live in siblings without pulling in every
 * unrelated function.
 */

export function timeAgo(isoString: string): string {
  const ago = Math.round((Date.now() - new Date(isoString).getTime()) / 1000);
  if (ago < 60) return ago + 's ago';
  if (ago < 3600) return Math.floor(ago / 60) + 'm ago';
  return Math.floor(ago / 3600) + 'h ago';
}

export function stripYaml(s: string | undefined | null): string {
  return s ? s.replace(/\.ya?ml$/i, '') : (s ?? '');
}

export function fmtDuration(secs: number | null | undefined): string {
  if (secs == null) return '—';
  // Bug #48: no fractional seconds anywhere in the app. Round to the
  // nearest second so the Queue tab, Job History drawers, Log modal,
  // and stats strips all format durations the same way.
  const s = Math.round(secs);
  if (s < 60) return s + 's';
  return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
}

/** Bug #48: consolidated epoch-seconds → "Xago" relative time.
 *
 * PR #80 review: clamp at 0 so clock skew (client ahead of server by
 * a few seconds; NTP correction mid-session) doesn't render absurd
 * strings like `"-5s ago"` in the Archive dialog, Compile history,
 * or Queue's "finished" column. A future timestamp is almost
 * certainly a skew artefact, not a real event — render as "just
 * now" so the UI stays readable instead of surfacing a negative
 * number that'd distract the reader from whatever they were
 * actually trying to check.
 */
export function fmtEpochRelative(epoch: number | null | undefined): string {
  if (epoch == null) return '—';
  // Bug #1: floor the diff itself, not just `Date.now()/1000`. Server epochs
  // come from `os.stat().st_mtime` which is a float, so without flooring the
  // sub-60s bucket renders `4.327s ago` instead of `4s ago`.
  const diff = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  if (diff === 0) return 'just now';
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86_400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86_400)}d ago`;
}

/** Bug #48: consolidated epoch-seconds → absolute locale-string. */
export function fmtEpochAbsolute(epoch: number | null | undefined): string {
  if (epoch == null) return '';
  return fmtDateTime(new Date(epoch * 1000));
}

// #82 / UX_REVIEW §3.10 — time-of-day format preference. Module-local
// so every ``fmt*`` helper picks up the current value without threading
// the setting through call-sites. ``App.tsx`` subscribes to
// ``/ui/api/settings`` via SWR and calls ``setTimeFormatPref`` whenever
// the user flips the drawer dropdown, so the next render of every
// Queue / History / Log surface uses the new format.

export type TimeFormatPref = 'auto' | '12h' | '24h';

let _timeFormatPref: TimeFormatPref = 'auto';

export function setTimeFormatPref(pref: TimeFormatPref): void {
  _timeFormatPref = pref;
}

// Bug #5: date format preference. ``'auto'`` follows the browser's
// resolved locale; the named formats force a specific shape regardless.
// Applied alongside ``hour12`` in ``_applyHour12`` so a single
// fmtDateTime call respects both prefs.
export type DateFormatPref = 'auto' | 'iso' | 'us' | 'eu' | 'long';

let _dateFormatPref: DateFormatPref = 'auto';

export function setDateFormatPref(pref: DateFormatPref): void {
  _dateFormatPref = pref;
}

function _applyHour12(opts: Intl.DateTimeFormatOptions): Intl.DateTimeFormatOptions {
  if (_timeFormatPref === '12h') return { ...opts, hour12: true };
  if (_timeFormatPref === '24h') return { ...opts, hour12: false };
  // 'auto' — omit hour12 so the browser's resolved locale decides.
  return opts;
}

/**
 * Bug #5: render the date-portion of a timestamp using the user's
 * ``date_format`` preference. Returns the locale-formatted date string
 * for the configured shape; ``'auto'`` defers to ``date.toLocaleDateString()``
 * with no overrides so the browser's locale wins. Used by ``fmtDateTime``
 * to produce a "date + time" string that respects both prefs.
 */
function _formatDate(date: Date): string {
  switch (_dateFormatPref) {
    case 'iso': {
      // YYYY-MM-DD in the user's local timezone.
      const y = date.getFullYear();
      const m = String(date.getMonth() + 1).padStart(2, '0');
      const d = String(date.getDate()).padStart(2, '0');
      return `${y}-${m}-${d}`;
    }
    case 'us':
      return date.toLocaleDateString('en-US');
    case 'eu':
      return date.toLocaleDateString('en-GB');
    case 'long':
      return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    case 'auto':
    default:
      return date.toLocaleDateString();
  }
}

/**
 * Time-of-day formatter that respects the user's ``time_format``
 * preference. Default options: ``HH:MM:SS`` with 2-digit fields. Callers
 * can override (e.g. to drop seconds). Use in place of direct
 * ``Date.toLocaleTimeString`` calls anywhere the user sees a time.
 */
export function fmtTimeOfDay(date: Date, opts?: Intl.DateTimeFormatOptions): string {
  const base: Intl.DateTimeFormatOptions = {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    ...opts,
  };
  return date.toLocaleTimeString([], _applyHour12(base));
}

/**
 * Full-timestamp formatter that respects the user's time-format AND
 * date-format preferences. Use in place of ``Date.toLocaleString()`` for
 * row tooltips and absolute timestamps. When the caller passes explicit
 * ``opts`` (e.g. a custom shape for a specific surface), only the
 * hour12 override is applied — the caller is opting out of the
 * date-format pref by being prescriptive.
 */
export function fmtDateTime(date: Date, opts?: Intl.DateTimeFormatOptions): string {
  if (opts) {
    return date.toLocaleString([], _applyHour12(opts));
  }
  // Default surface: date + time, both following the user's prefs.
  // ``_formatDate`` handles the date portion (and date-format pref);
  // fmtTimeOfDay covers the time portion (and time-format pref).
  return `${_formatDate(date)}, ${fmtTimeOfDay(date)}`;
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
