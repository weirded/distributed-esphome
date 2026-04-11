import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Select } from './ui/select';
import type { Worker } from '../types';

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

function buildCron(interval: string, every: number, time: string, dow: string): string {
  const [hh, mm] = time.split(':').map(Number);
  const minute = isNaN(mm) ? 0 : mm;
  const hour = isNaN(hh) ? 2 : hh;
  switch (interval) {
    case 'hours': return every === 1 ? `${minute} * * * *` : `${minute} */${every} * * *`;
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
  }) => void;
  /**
   * Save a recurring cron schedule. `version` is the user's pin choice —
   * `null` means "Latest" (unpin / use server default at run time), a
   * specific string means "pin the device to this version".
   */
  onSaveSchedule: (cron: string, version: string | null) => void;
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

  // --- Mode: now vs schedule ---
  const [mode, setMode] = useState<'now' | 'schedule'>(scheduleOnly ? 'schedule' : defaultMode);

  // --- Schedule state ---
  const parsed = currentSchedule ? parseCron(currentSchedule) : null;
  const [scheduleType, setScheduleType] = useState<'recurring' | 'once'>(currentOnce ? 'once' : 'recurring');
  const [interval, setInterval] = useState(parsed?.interval ?? 'days');
  const [every, setEvery] = useState(parsed?.every ?? 1);
  const [time, setTime] = useState(parsed?.time ?? '02:00');
  const [dow, setDow] = useState(parsed?.dow ?? '0');
  const [rawCron, setRawCron] = useState(currentSchedule ?? '');
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

  const effectiveCron = cronMode === 'cron' ? rawCron.trim() : buildCron(interval, every, time, dow);
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
        updatePin: shouldUpdatePin ? selectedVersion : null,
      });
    } else {
      if (scheduleType === 'once') {
        onSaveOnce(new Date(onceDate).toISOString(), scheduleVersion);
      } else {
        onSaveSchedule(effectiveCron, scheduleVersion);
      }
    }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent style={{ maxWidth: 480 }}>
        <DialogHeader>
          <DialogTitle>
            {mode === 'schedule' ? 'Schedule Upgrade' : 'Upgrade'} — {displayName}
          </DialogTitle>
        </DialogHeader>
        <div className="p-[18px] flex flex-col gap-4">

          {/* Shared: Worker + Version (hidden in scheduleOnly mode) */}
          {!scheduleOnly && (
            <>
              <div>
                <label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1">Worker</label>
                <Select value={selectedWorker} onChange={e => setSelectedWorker(e.target.value)}>
                  <option value="">&lt;any&gt; — let the scheduler pick</option>
                  {eligibleWorkers.map(w => (
                    <option key={w.client_id} value={w.client_id}>{w.hostname}</option>
                  ))}
                </Select>
              </div>

              <div>
                <label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1">ESPHome version</label>
                <Select value={selectedVersion} onChange={e => setSelectedVersion(e.target.value)}>
                  <option value="">
                    Current{defaultEsphomeVersion ? ` (${defaultEsphomeVersion})` : ''}
                  </option>
                  {versionList.map(v => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </Select>
              </div>

              {/* Pin warning */}
              {shouldUpdatePin && mode === 'now' && (
                <div className="rounded-lg border border-[var(--accent)] bg-[var(--accent)]/10 px-3 py-2 text-[12px]" style={{ color: 'var(--accent)' }}>
                  <strong>Pin update.</strong> Currently pinned to <code className="bg-[var(--surface)] px-1 rounded">{pinnedVersion}</code>. Upgrading will update the pin to <code className="bg-[var(--surface)] px-1 rounded">{selectedVersion}</code>.
                </div>
              )}
            </>
          )}

          {/* Mode radio: Now vs Schedule (hidden in scheduleOnly mode).
              #34: Radios sit *below* the worker+version selectors so the
              primary choice (what to upgrade to) comes before the
              secondary choice (when to run it). */}
          {!scheduleOnly && (
            <div className="flex items-center gap-4 pt-1 border-t border-[var(--border)]">
              <label className="flex items-center gap-1.5 text-[13px] cursor-pointer pt-2">
                <input type="radio" name="upgrade-mode" checked={mode === 'now'} onChange={() => setMode('now')} />
                Now
              </label>
              <label className="flex items-center gap-1.5 text-[13px] cursor-pointer pt-2">
                <input type="radio" name="upgrade-mode" checked={mode === 'schedule'} onChange={() => setMode('schedule')} />
                Scheduled
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
                    <div className="mt-1 text-[10px] text-[var(--text-muted)]">minute hour day-of-month month day-of-week</div>
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
                  Cron: <code className="bg-[var(--surface)] px-1 rounded">{effectiveCron}</code>
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
              {mode === 'now' ? 'Upgrade' : 'Save Schedule'}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
