/**
 * Cron expression helpers (QS.23).
 *
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
