import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Select } from './ui/select';
import type { Worker } from '../types';

const BROWSER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

/**
 * Unified Upgrade modal (#22).
 *
 * Two modes via radio buttons: "Now" (compile immediately) or "Scheduled"
 * (set a recurring or one-time schedule). Both share the worker + version
 * selectors. The confirm button adapts: "Upgrade" vs "Save Schedule".
 *
 * Entry points:
 * - Row "Upgrade" button → defaultMode: 'now'
 * - Hamburger "Schedule Upgrade..." → defaultMode: 'schedule'
 * - Schedules tab "Edit" → defaultMode: 'schedule', schedule pre-filled
 */

// ---------------------------------------------------------------------------
// Cron builder helpers (from the old ScheduleModal)
// ---------------------------------------------------------------------------

// #90: cron expressions in this modal are timezone-naive — they're stored as
// the user enters them, paired with a `schedule_tz` field that APScheduler
// uses to evaluate them on the server. No client-side hour conversion needed.
function buildCron(interval: string, every: number, time: string, dow: string): string {
  const [hh, mm] = time.split(':').map(Number);
  const minute = isNaN(mm) ? 0 : mm;
  const hour = isNaN(hh) ? 2 : hh;

  if (interval === 'hours') {
    return every === 1 ? `${minute} * * * *` : `${minute} */${every} * * *`;
  }

  switch (interval) {
    case 'days': return every === 1 ? `${minute} ${hour} * * *` : `${minute} ${hour} */${every} * *`;
    case 'weeks': return `${minute} ${hour} * * ${dow}`;
    default: return `${minute} ${hour} * * *`;
  }
}

function parseCron(cron: string): { interval: string; every: number; time: string; dow: string } | null {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [min, hour, dom, , dow] = parts;
  const minute = parseInt(min, 10);
  if (isNaN(minute)) return null;
  if (hour.startsWith('*/') && dom === '*' && dow === '*') {
    return { interval: 'hours', every: parseInt(hour.slice(2), 10), time: `00:${String(minute).padStart(2, '0')}`, dow: '0' };
  }
  if (hour === '*' && dom === '*' && dow === '*') {
    return { interval: 'hours', every: 1, time: `00:${String(minute).padStart(2, '0')}`, dow: '0' };
  }
  const h = parseInt(hour, 10);
  if (isNaN(h)) return null;
  const timeStr = `${String(h).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;

  if (dow === '*') {
    if (dom === '*') return { interval: 'days', every: 1, time: timeStr, dow: '0' };
    if (dom.startsWith('*/')) return { interval: 'days', every: parseInt(dom.slice(2), 10), time: timeStr, dow: '0' };
    return null;
  }
  if (dom === '*') return { interval: 'weeks', every: 1, time: timeStr, dow };
  return null;
}

const DAY_OPTIONS = [
  { label: 'Sunday', value: '0' },
  { label: 'Monday', value: '1' },
  { label: 'Tuesday', value: '2' },
  { label: 'Wednesday', value: '3' },
  { label: 'Thursday', value: '4' },
  { label: 'Friday', value: '5' },
  { label: 'Saturday', value: '6' },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  target: string;
  displayName: string;
  workers: Worker[];
  esphomeVersions: string[];
  defaultEsphomeVersion: string | null;
  pinnedVersion?: string | null;
  /** Pre-existing recurring schedule (cron expression). */
  currentSchedule?: string | null;
  currentScheduleEnabled?: boolean;
  /** IANA tz the existing cron is interpreted in. Absent means legacy/UTC. */
  currentScheduleTz?: string | null;
  /** Pre-existing one-time schedule (ISO datetime). */
  currentOnce?: string | null;
  /** Which mode to open in: 'now' for immediate upgrade, 'schedule' for scheduling. */
  defaultMode?: 'now' | 'schedule';
  /** If true, only show the schedule UI — hide mode radios and worker/version pickers.
   *  Used for bulk "Schedule Selected" where version/worker are per-device concerns. */
  scheduleOnly?: boolean;
  onUpgradeNow: (params: {
    pinnedClientId: string | null;
    esphomeVersion: string | null;
    updatePin?: string | null;
    /** FD.3: when true, enqueue a compile-and-download job instead of compile+OTA. */
    downloadOnly?: boolean;
  }) => void;
  /**
   * Save a recurring cron schedule. `version` is the user's pin choice —
   * `null` means "Latest" (unpin / use server default at run time), a
   * specific string means "pin the device to this version". `tz` is the
   * IANA tz the cron is interpreted in (#90).
   */
  onSaveSchedule: (cron: string, version: string | null, tz: string) => void;
  onSaveOnce: (datetime: string, version: string | null) => void;
  onDeleteSchedule: () => void;
  onClose: () => void;
}

export function UpgradeModal({
  target: _target,
  displayName,
  workers,
  esphomeVersions,
  defaultEsphomeVersion,
  pinnedVersion,
  currentSchedule,
  currentScheduleEnabled: _currentScheduleEnabled,
  currentScheduleTz,
  currentOnce,
  defaultMode = 'now',
  scheduleOnly = false,
  onUpgradeNow,
  onSaveSchedule,
  onSaveOnce,
  onDeleteSchedule,
  onClose,
}: Props) {
  void _target;

  // --- Shared state: worker + version ---
  const eligibleWorkers = workers
    .filter(w => w.online && !w.disabled && (w.max_parallel_jobs ?? 0) > 0)
    .slice()
    .sort((a, b) => a.hostname.localeCompare(b.hostname, undefined, { sensitivity: 'base' }));

  const [selectedWorker, setSelectedWorker] = useState<string>('');
  // #31: selectedVersion = '' means "Latest" (no pin / use current default at
  // run time). If the device is currently pinned, default to that pin. Otherwise
  // default to "Latest" so the schedule auto-updates with new ESPHome releases.
  const [selectedVersion, setSelectedVersion] = useState<string>(pinnedVersion ?? '');

  const versionList: string[] = [];
  if (defaultEsphomeVersion) versionList.push(defaultEsphomeVersion);
  for (const v of esphomeVersions) {
    if (v && !versionList.includes(v)) versionList.push(v);
  }

  // #64: searchable + beta-filterable version list
  const [versionSearch, setVersionSearch] = useState('');
  const [showBetas, setShowBetas] = useState(false);
  const isBeta = (v: string) => /\d(a|b|rc|dev)\d/i.test(v);
  const filteredVersions = versionList.filter(v => {
    if (!showBetas && isBeta(v)) return false;
    if (versionSearch && !v.toLowerCase().includes(versionSearch.toLowerCase())) return false;
    return true;
  });

  // UX.8: One 3-option action radio replaces the earlier "Now | Scheduled"
  // + nested "Compile + OTA | Compile + Download" toggles. The legal
  // combinations are:
  //   upgrade-now   → mode=now, nowAction=ota      (most common, default)
  //   download-now  → mode=now, nowAction=download (compile-only, OTA skipped)
  //   schedule      → mode=schedule, always OTA    (no download-while-scheduled)
  type Action = 'upgrade-now' | 'download-now' | 'schedule';
  const initialAction: Action = scheduleOnly
    ? 'schedule'
    : defaultMode === 'schedule' ? 'schedule' : 'upgrade-now';
  const [action, setAction] = useState<Action>(initialAction);
  const mode: 'now' | 'schedule' = action === 'schedule' ? 'schedule' : 'now';
  const nowAction: 'ota' | 'download' = action === 'download-now' ? 'download' : 'ota';

  // --- Schedule state ---
  // #90/#91: cron is shown literally in the picker — no client-side hour
  // conversion. For schedules with `currentScheduleTz` set, the literal
  // cron is what fires in that tz. For legacy schedules without a tz
  // (interpreted as UTC server-side), we still show the literal cron — the
  // user re-saves to claim it for their browser tz, which is honest about
  // what's stored.
  void currentScheduleTz;
  const seedCron = currentSchedule ?? '';
  const parsed = seedCron ? parseCron(seedCron) : null;
  const [scheduleType, setScheduleType] = useState<'recurring' | 'once'>(currentOnce ? 'once' : 'recurring');
  const [interval, setInterval] = useState(parsed?.interval ?? 'days');
  const [every, setEvery] = useState(parsed?.every ?? 1);
  const [time, setTime] = useState(parsed?.time ?? '02:00');
  const [dow, setDow] = useState(parsed?.dow ?? '0');
  const [rawCron, setRawCron] = useState(seedCron);
  const [cronMode, setCronMode] = useState<'friendly' | 'cron'>(parsed || !currentSchedule ? 'friendly' : 'cron');
  // #33: datetime-local expects a *local* wall-clock value (no timezone). Using
  // `toISOString()` returns UTC, so east-of-UTC users would see a time in the
  // past and west-of-UTC users (e.g. the author) would see a time many hours
  // in the future. Build the value from local components instead.
  const [onceDate, setOnceDate] = useState(() => {
    const pad = (n: number) => String(n).padStart(2, '0');
    const toLocalInput = (d: Date) =>
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    return toLocalInput(currentOnce ? new Date(currentOnce) : new Date());
  });

  const effectiveCron = cronMode === 'cron'
    ? rawCron.trim()
    : buildCron(interval, every, time, dow);
  const hasExistingSchedule = !!(currentSchedule || currentOnce);

  // --- Pin warning ---
  // Shows when the user's version choice in "Now" mode would change an
  // existing pin. selectedVersion === '' means "Latest" which is treated as
  // leaving the pin alone in Now mode (don't auto-unpin a manual pin on a
  // one-off upgrade).
  const shouldUpdatePin = pinnedVersion && selectedVersion && selectedVersion !== pinnedVersion;

  // For schedule saves: '' ("Latest") → null (unpin), otherwise the string.
  const scheduleVersion: string | null = selectedVersion || null;

  function handleConfirm() {
    if (mode === 'now') {
      onUpgradeNow({
        pinnedClientId: selectedWorker || null,
        esphomeVersion: selectedVersion && selectedVersion !== defaultEsphomeVersion ? selectedVersion : null,
        // FD.3: don't update the pin when we're only producing a
        // binary to download — the device state hasn't changed.
        updatePin: nowAction === 'ota' && shouldUpdatePin ? selectedVersion : null,
        downloadOnly: nowAction === 'download',
      });
    } else {
      if (scheduleType === 'once') {
        onSaveOnce(new Date(onceDate).toISOString(), scheduleVersion);
      } else {
        onSaveSchedule(effectiveCron, scheduleVersion, BROWSER_TZ);
      }
    }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent style={{ maxWidth: 480 }}>
        <DialogHeader>
          <DialogTitle>
            {/* UX.8: title matches the selected action verb. */}
            {action === 'schedule'
              ? 'Schedule Upgrade'
              : action === 'download-now' ? 'Download' : 'Upgrade'}{' '}— {displayName}
          </DialogTitle>
        </DialogHeader>
        <div className="p-[18px] flex flex-col gap-4">

          {/* Shared: Worker + Version (hidden in scheduleOnly mode) */}
          {!scheduleOnly && (
            <>
              <div>
                <Label htmlFor="upgrade-worker-select">Worker</Label>
                <Select
                  id="upgrade-worker-select"
                  value={selectedWorker}
                  onChange={e => setSelectedWorker(e.target.value)}
                  title="Fleet will pick the fastest available worker at compile time."
                >
                  {/* UX.7: dropped the <any> coder-syntax label. */}
                  <option value="">Any available worker (auto)</option>
                  {eligibleWorkers.map(w => (
                    <option key={w.client_id} value={w.client_id}>{w.hostname}</option>
                  ))}
                </Select>
              </div>

              <div>
                <Label>ESPHome version</Label>
                <input
                  type="text"
                  value={versionSearch}
                  onChange={e => setVersionSearch(e.target.value)}
                  placeholder="Search versions..."
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface2)] px-2.5 py-1 text-[12px] text-[var(--text)] outline-none placeholder:text-[var(--text-muted)] focus:border-[var(--accent)] mb-1"
                />
                {/* #73: scrollable list matching the header dropdown style */}
                <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] overflow-y-auto" style={{ maxHeight: 160 }}>
                  <button
                    type="button"
                    className={`w-full text-left px-2.5 py-1.5 text-[12px] cursor-pointer hover:bg-[var(--surface2)] ${selectedVersion === '' ? 'text-[var(--accent)] font-semibold' : 'text-[var(--text)]'}`}
                    onClick={() => setSelectedVersion('')}
                  >
                    Current{defaultEsphomeVersion ? ` (${defaultEsphomeVersion})` : ''}
                  </button>
                  {filteredVersions.map(v => (
                    <button
                      key={v}
                      type="button"
                      className={`w-full text-left px-2.5 py-1.5 text-[12px] cursor-pointer hover:bg-[var(--surface2)] ${selectedVersion === v ? 'text-[var(--accent)] font-semibold' : 'text-[var(--text)]'}`}
                      onClick={() => setSelectedVersion(v)}
                    >
                      {v}
                    </button>
                  ))}
                  {filteredVersions.length === 0 && (
                    <div className="px-2.5 py-1.5 text-[12px] text-[var(--text-muted)]">No matches</div>
                  )}
                </div>
                <label className="flex items-center gap-1.5 mt-1 text-[11px] text-[var(--text-muted)] cursor-pointer">
                  <input type="checkbox" checked={showBetas} onChange={e => setShowBetas(e.target.checked)} />
                  Show betas
                </label>
              </div>

              {/* Pin warning */}
              {shouldUpdatePin && mode === 'now' && (
                <div className="rounded-lg border border-[var(--accent)] bg-[var(--accent)]/10 px-3 py-2 text-[12px]" style={{ color: 'var(--accent)' }}>
                  <strong>Pin update.</strong> Currently pinned to <code className="bg-[var(--surface)] px-1 rounded">{pinnedVersion}</code>. Upgrading will update the pin to <code className="bg-[var(--surface)] px-1 rounded">{selectedVersion}</code>.
                </div>
              )}
            </>
          )}

          {/* UX.8: single Action radio (3 options) replaces the former
              nested Now/Scheduled + Compile-OTA/Compile-Download toggles.
              #34: sits below the worker+version selectors so the primary
              choice (what to upgrade to) comes first. */}
          {!scheduleOnly && (
            <div className="flex flex-col gap-1.5 pt-2 border-t border-[var(--border)]">
              <Label>Action</Label>
              <label className="flex items-center gap-1.5 text-[13px] cursor-pointer">
                <input
                  type="radio"
                  name="upgrade-action"
                  checked={action === 'upgrade-now'}
                  onChange={() => setAction('upgrade-now')}
                />
                Upgrade Now
                <span className="text-[11px] text-[var(--text-muted)]">— compile + OTA flash</span>
              </label>
              <label className="flex items-center gap-1.5 text-[13px] cursor-pointer">
                <input
                  type="radio"
                  name="upgrade-action"
                  checked={action === 'download-now'}
                  onChange={() => setAction('download-now')}
                />
                Download Now
                <span className="text-[11px] text-[var(--text-muted)]">— compile only, no OTA; grab the .bin from the Queue tab</span>
              </label>
              <label className="flex items-center gap-1.5 text-[13px] cursor-pointer">
                <input
                  type="radio"
                  name="upgrade-action"
                  checked={action === 'schedule'}
                  onChange={() => setAction('schedule')}
                />
                Schedule Upgrade
                <span className="text-[11px] text-[var(--text-muted)]">— run the OTA upgrade on a cron or a one-time timestamp</span>
              </label>
            </div>
          )}

          {/* Schedule options (only visible in schedule mode) */}
          {mode === 'schedule' && (
            <div className="flex flex-col gap-3 pt-1 border-t border-[var(--border)]">
              {/* Recurring vs Once */}
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-1.5 text-[12px] cursor-pointer">
                  <input type="radio" name="schedule-type" checked={scheduleType === 'recurring'} onChange={() => setScheduleType('recurring')} />
                  Recurring
                </label>
                <label className="flex items-center gap-1.5 text-[12px] cursor-pointer">
                  <input type="radio" name="schedule-type" checked={scheduleType === 'once'} onChange={() => setScheduleType('once')} />
                  One-time
                </label>
                {scheduleType === 'recurring' && (
                  <button
                    className="ml-auto text-[10px] text-[var(--text-muted)] cursor-pointer hover:text-[var(--text)]"
                    onClick={() => setCronMode(cronMode === 'friendly' ? 'cron' : 'friendly')}
                  >
                    {cronMode === 'friendly' ? 'Advanced (cron)' : 'Simple'}
                  </button>
                )}
              </div>

              {scheduleType === 'recurring' ? (
                cronMode === 'friendly' ? (
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[12px]">Every</span>
                    <Input type="number" min={1} max={30} value={every} onChange={e => setEvery(Math.max(1, parseInt(e.target.value, 10) || 1))} className="w-[60px]" />
                    <Select value={interval} onChange={e => setInterval(e.target.value)} className="w-[100px]">
                      <option value="hours">hour(s)</option>
                      <option value="days">day(s)</option>
                      <option value="weeks">week(s)</option>
                    </Select>
                    {interval === 'weeks' && (
                      <>
                        <span className="text-[12px]">on</span>
                        <Select value={dow} onChange={e => setDow(e.target.value)} className="w-[120px]">
                          {DAY_OPTIONS.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
                        </Select>
                      </>
                    )}
                    {interval !== 'hours' && (
                      <>
                        <span className="text-[12px]">at</span>
                        <Input type="time" value={time} onChange={e => setTime(e.target.value)} className="w-[100px]" />
                      </>
                    )}
                  </div>
                ) : (
                  <div>
                    <Input type="text" value={rawCron} placeholder="0 2 * * *" onChange={e => setRawCron(e.target.value)} />
                    <div className="mt-1 text-[10px] text-[var(--text-muted)]">minute hour day-of-month month day-of-week — interpreted in {BROWSER_TZ}</div>
                  </div>
                )
              ) : (
                <div>
                  <Input type="datetime-local" value={onceDate} onChange={e => setOnceDate(e.target.value)} />
                  <div className="mt-1 text-[10px] text-[var(--text-muted)]">Upgrades once at this time, then the schedule is removed.</div>
                </div>
              )}

              {scheduleType === 'recurring' && cronMode === 'friendly' && (
                <div className="text-[10px] text-[var(--text-muted)]">
                  Cron: <code className="bg-[var(--surface)] px-1 rounded">{effectiveCron}</code> <span className="opacity-70">({BROWSER_TZ})</span>
                </div>
              )}

              {hasExistingSchedule && (
                <button
                  className="text-[11px] text-[var(--destructive)] cursor-pointer hover:underline self-start"
                  onClick={() => { onDeleteSchedule(); onClose(); }}
                >
                  Remove existing schedule
                </button>
              )}
            </div>
          )}

          {/* Confirm */}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={onClose}>Cancel</Button>
            <Button
              variant={mode === 'now' ? 'success' : 'default'}
              disabled={mode === 'schedule' && scheduleType === 'once' && !onceDate}
              onClick={handleConfirm}
            >
              {/* UX.8: confirm-button label mirrors the action verb. */}
              {action === 'upgrade-now' && 'Upgrade'}
              {action === 'download-now' && 'Compile & Download'}
              {action === 'schedule' && 'Save Schedule'}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
