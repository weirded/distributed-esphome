/**
 * Grafana-style time-range picker (bug #49, bug #59).
 *
 * Popover with a preset list on the left and an absolute-range panel on
 * the right (calendar + time inputs). Emits an epoch-seconds
 * ``{since, until}`` pair — ``null`` on either side means "open-ended".
 *
 * Bug #59: the previous rev hand-rolled the popover as an ``absolute
 * left-0 mt-1`` div which reliably clipped against the Queue-History
 * dialog's gutters — presets column disappeared, calendar truncated to
 * 4 columns. Swapped for Base-UI's Popover primitive (already bundled;
 * it's the floating-UI-backed component shadcn's own patterns use) so
 * positioning + collision detection + outside-click are handled
 * correctly by proven code.
 */

import { useCallback, useEffect, useState } from 'react';
import { DayPicker, type DateRange } from 'react-day-picker';
import { Calendar, ChevronDown } from 'lucide-react';

import 'react-day-picker/style.css';
import './TimeRangePicker.css';

import { Popover } from '@base-ui/react/popover';

import { Button } from '@/components/ui/button';
import { fmtEpochAbsolute } from '@/utils/format';


export interface TimeRange {
  /** Epoch seconds (UTC). null = open-ended on this side. */
  since: number | null;
  until: number | null;
}

/**
 * Preset definitions. Each preset resolves to a since-only range
 * (``until`` defaults to null == "now or later"). Order matters —
 * rendered top-to-bottom in the left column.
 */
export interface Preset {
  label: string;
  /** Returns the since epoch at the moment of selection. */
  since: () => number;
}

const DEFAULT_PRESETS: Preset[] = [
  { label: 'Last 5 minutes', since: () => Math.floor(Date.now() / 1000) - 5 * 60 },
  { label: 'Last 15 minutes', since: () => Math.floor(Date.now() / 1000) - 15 * 60 },
  { label: 'Last 1 hour', since: () => Math.floor(Date.now() / 1000) - 3600 },
  { label: 'Last 6 hours', since: () => Math.floor(Date.now() / 1000) - 6 * 3600 },
  { label: 'Last 24 hours', since: () => Math.floor(Date.now() / 1000) - 86_400 },
  { label: 'Last 7 days', since: () => Math.floor(Date.now() / 1000) - 7 * 86_400 },
  { label: 'Last 30 days', since: () => Math.floor(Date.now() / 1000) - 30 * 86_400 },
  { label: 'Last 90 days', since: () => Math.floor(Date.now() / 1000) - 90 * 86_400 },
  { label: 'Last year', since: () => Math.floor(Date.now() / 1000) - 365 * 86_400 },
];


interface Props {
  value: TimeRange;
  onChange: (range: TimeRange, presetLabel: string | null) => void;
  /** Label used on the trigger button when a preset is active. */
  activePresetLabel: string | null;
}


export function TimeRangePicker({ value, onChange, activePresetLabel }: Props) {
  const [open, setOpen] = useState(false);

  // Calendar + time inputs state. Seeded from the current value each
  // time the popover opens so re-opening shows the active selection.
  const [draftRange, setDraftRange] = useState<DateRange | undefined>(undefined);
  const [fromTime, setFromTime] = useState('00:00');
  const [toTime, setToTime] = useState('23:59');

  useEffect(() => {
    if (!open) return;
    const fromDate = value.since != null ? new Date(value.since * 1000) : undefined;
    const toDate = value.until != null ? new Date(value.until * 1000) : undefined;
    setDraftRange({ from: fromDate, to: toDate });
    if (fromDate) setFromTime(fmtTimeHHMM(fromDate));
    if (toDate) setToTime(fmtTimeHHMM(toDate));
  }, [open, value.since, value.until]);

  const applyAbsolute = useCallback(() => {
    if (!draftRange?.from) return;
    const from = combineDateAndTime(draftRange.from, fromTime);
    const to = combineDateAndTime(draftRange.to ?? draftRange.from, toTime);
    onChange({ since: Math.floor(from.getTime() / 1000), until: Math.floor(to.getTime() / 1000) }, null);
    setOpen(false);
  }, [draftRange, fromTime, toTime, onChange]);

  const triggerLabel = activePresetLabel ?? (() => {
    if (value.since == null && value.until == null) return 'All time';
    const from = fmtEpochAbsolute(value.since);
    const to = fmtEpochAbsolute(value.until) || 'now';
    return `${from || '…'} → ${to}`;
  })();

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface2)] px-2.5 py-1 text-[12px] text-[var(--text)] hover:border-[var(--accent)] cursor-pointer"
        title="Select time range"
      >
        <Calendar className="size-3.5 text-[var(--text-muted)]" aria-hidden="true" />
        <span className="truncate max-w-[260px]">{triggerLabel}</span>
        <ChevronDown className="size-3 text-[var(--text-muted)]" aria-hidden="true" />
      </Popover.Trigger>
      {/* Popover.Portal renders outside the modal's overflow region so
          clipping can't chop the popover. Positioner handles collision
          detection via floating-ui — the popover flips, shifts, and
          constrains its size to the viewport automatically. */}
      <Popover.Portal>
        <Popover.Positioner
          sideOffset={6}
          align="start"
          collisionPadding={8}
          className="z-[300]"
        >
          <Popover.Popup
            className="flex flex-wrap rounded-md border border-[var(--border)] bg-[var(--surface)] shadow-xl text-[12px] outline-none"
            style={{ width: 'min(640px, 92vw)' }}
          >
            {/* Presets column */}
            <div className="flex-none w-[180px] border-r border-[var(--border)] py-2">
              <div className="px-3 pb-1 text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                Quick ranges
              </div>
              {DEFAULT_PRESETS.map((p) => {
                const active = activePresetLabel === p.label;
                return (
                  <button
                    key={p.label}
                    type="button"
                    className={
                      'block w-full px-3 py-1 text-left hover:bg-[var(--surface2)] cursor-pointer ' +
                      (active ? 'text-[var(--accent)] font-semibold' : 'text-[var(--text)]')
                    }
                    onClick={() => {
                      onChange({ since: p.since(), until: null }, p.label);
                      setOpen(false);
                    }}
                  >
                    {p.label}
                  </button>
                );
              })}
              <button
                type="button"
                className="block w-full px-3 py-1 text-left text-[var(--text-muted)] hover:bg-[var(--surface2)] cursor-pointer border-t border-[var(--border)] mt-1"
                onClick={() => {
                  onChange({ since: null, until: null }, 'All time');
                  setOpen(false);
                }}
              >
                All time
              </button>
            </div>

            {/* Absolute range column */}
            <div className="flex-1 py-2 px-3 min-w-0">
              <div className="pb-1 text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                Absolute range
              </div>
              <div className="rdp-tight flex justify-center">
                <DayPicker
                  mode="range"
                  selected={draftRange}
                  onSelect={setDraftRange}
                  numberOfMonths={1}
                  // #102: first-day-of-week follows the browser locale
                  // (Monday in most of Europe, Sunday in the US + most
                  // Asia). ``navigator.language`` is what ``Intl`` also
                  // resolves against, so the calendar matches Pat's
                  // date expectations.
                  weekStartsOn={firstDayOfWeekForLocale()}
                  className="text-[12px]"
                  // Match the app's dark surface — react-day-picker ships
                  // a light default that's jarring against our theme.
                  style={{
                    ['--rdp-accent-color' as string]: 'var(--accent, #2472c8)',
                    ['--rdp-accent-background-color' as string]: 'color-mix(in srgb, var(--accent, #2472c8) 25%, transparent)',
                    ['--rdp-background-color' as string]: 'var(--surface)',
                    color: 'var(--text)',
                  }}
                />
              </div>
              <div className="mt-2 grid grid-cols-[auto_1fr_auto_1fr] items-center gap-2">
                <label className="text-[var(--text-muted)]">From:</label>
                <input
                  type="time"
                  className="rounded border border-[var(--border)] bg-[var(--surface2)] px-1 py-0.5 text-[12px] text-[var(--text)] outline-none focus:border-[var(--accent)]"
                  value={fromTime}
                  onChange={(e) => setFromTime(e.target.value)}
                />
                <label className="text-[var(--text-muted)]">To:</label>
                <input
                  type="time"
                  className="rounded border border-[var(--border)] bg-[var(--surface2)] px-1 py-0.5 text-[12px] text-[var(--text)] outline-none focus:border-[var(--accent)]"
                  value={toTime}
                  onChange={(e) => setToTime(e.target.value)}
                />
              </div>
              <div className="mt-3 flex justify-end gap-2">
                <Button variant="secondary" size="sm" onClick={() => setOpen(false)}>Cancel</Button>
                <Button size="sm" onClick={applyAbsolute} disabled={!draftRange?.from}>
                  Apply
                </Button>
              </div>
            </div>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}


function fmtTimeHHMM(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * #102: Derive the first day of the week from the browser's locale.
 * Returns ``0`` (Sunday) or ``1`` (Monday) — the two values
 * react-day-picker's ``weekStartsOn`` prop accepts most cleanly for
 * our Pat-mix user base. Uses ``Intl.Locale.weekInfo`` where supported
 * (Chrome 130+, Safari 17+, Firefox 134+); falls back to a region
 * heuristic for older UAs.
 */
function firstDayOfWeekForLocale(): 0 | 1 {
  const lang = typeof navigator !== 'undefined' ? navigator.language : 'en-US';
  try {
    // weekInfo is a stage-3 Intl extension; TS doesn't type it yet.
    const locale = new Intl.Locale(lang) as Intl.Locale & {
      weekInfo?: { firstDay?: number };
      getWeekInfo?: () => { firstDay?: number };
    };
    const weekInfo = locale.weekInfo ?? locale.getWeekInfo?.();
    // Intl uses 1-7 (Mon-Sun). rdp uses 0-6 (Sun-Sat).
    if (weekInfo?.firstDay === 7) return 0;
    if (typeof weekInfo?.firstDay === 'number') return 1;
  } catch {
    // Intl.Locale.weekInfo unsupported — fall through.
  }
  const ll = lang.toLowerCase();
  // US / CA / JP / KR / IL / BR / MX default Sunday-first.
  if (
    ll.startsWith('en-us') || ll.startsWith('en-ca') ||
    ll.startsWith('ja') || ll.startsWith('ko') ||
    ll.startsWith('he') || ll.startsWith('pt-br') ||
    ll.startsWith('es-mx')
  ) {
    return 0;
  }
  // Most European / ISO 8601 locales default to Monday.
  return 1;
}

function combineDateAndTime(date: Date, time: string): Date {
  const [hhRaw, mmRaw] = time.split(':');
  const hh = Number.parseInt(hhRaw ?? '0', 10);
  const mm = Number.parseInt(mmRaw ?? '0', 10);
  const out = new Date(date);
  out.setHours(Number.isFinite(hh) ? hh : 0, Number.isFinite(mm) ? mm : 0, 0, 0);
  return out;
}
