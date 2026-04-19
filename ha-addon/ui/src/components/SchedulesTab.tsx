import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Calendar, Check, Circle, Clock, Pin, X } from 'lucide-react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
  type RowSelectionState,
} from '@tanstack/react-table';
import type { Target, Worker } from '../types';
import { stripYaml, timeAgo, formatCronHuman, usePersistedState } from '../utils';
import { Button } from './ui/button';
import { SortHeader, getAriaSort } from './ui/sort-header';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
} from './ui/dropdown-menu';
import { deleteTargetSchedule, getScheduleHistory, type ScheduleHistoryEntry } from '../api/client';


function formatNextRun(schedule: string | null | undefined, lastRun: string | null | undefined, scheduleOnce: string | null | undefined): string {
  if (scheduleOnce) {
    const d = new Date(scheduleOnce);
    return `Once: ${d.toLocaleString()}`;
  }
  if (!schedule) return '—';
  if (!lastRun) return 'Pending (first run)';
  return `Last: ${timeAgo(lastRun)}`;
}

interface Props {
  targets: Target[];
  workers: Worker[];
  onSchedule: (target: string) => void;
  onRefresh: () => void;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
}

const columnHelper = createColumnHelper<Target>();

export function SchedulesTab({ targets, workers, onSchedule, onRefresh, onToast }: Props) {
  void workers;

  const scheduled = useMemo(
    () => targets.filter(t => t.schedule || t.schedule_once),
    [targets],
  );

  // QS.27: persist sort across reloads via localStorage.
  const [sorting, setSorting] = usePersistedState<SortingState>('schedules-sort', []);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [filter, setFilter] = useState('');

  // #81: fetch schedule history for display
  const [history, setHistory] = useState<Record<string, ScheduleHistoryEntry[]>>({});
  useEffect(() => {
    let cancelled = false;
    const fetchHistory = async () => {
      try {
        const data = await getScheduleHistory();
        if (!cancelled) setHistory(data);
      } catch { /* ignore */ }
    };
    fetchHistory();
    const id = setInterval(fetchHistory, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const filteredScheduled = useMemo(() => {
    if (!filter) return scheduled;
    const lc = filter.toLowerCase();
    return scheduled.filter(t => {
      const name = t.friendly_name || t.device_name || stripYaml(t.target);
      return name.toLowerCase().includes(lc) || t.target.toLowerCase().includes(lc);
    });
  }, [scheduled, filter]);

  const columns = useMemo(() => [
    columnHelper.display({
      id: 'select',
      header: ({ table }) => (
        <input
          type="checkbox"
          checked={table.getIsAllRowsSelected()}
          onChange={table.getToggleAllRowsSelectedHandler()}
        />
      ),
      cell: ({ row }) => (
        <input
          type="checkbox"
          checked={row.getIsSelected()}
          onChange={row.getToggleSelectedHandler()}
        />
      ),
    }),
    columnHelper.accessor(row => row.friendly_name || row.device_name || stripYaml(row.target), {
      id: 'device',
      header: ({ column }) => <SortHeader label="Device" column={column} />,
      cell: ({ row: { original: t } }) => (
        <>
          <span className="device-name">{t.friendly_name || t.device_name || stripYaml(t.target)}</span>
          <div className="device-filename">{stripYaml(t.target)}</div>
        </>
      ),
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(row => row.schedule || row.schedule_once || '', {
      id: 'schedule',
      header: ({ column }) => <SortHeader label="Schedule" column={column} />,
      cell: ({ row: { original: t } }) => {
        const enabled = t.schedule_enabled !== false;
        // #40: use humanized cron for recurring schedules and a local-time
        // format for one-time. Render in the default (proportional) table
        // font to match the other columns — previously forced monospace.
        // #92: render both recurring and one-time when both are present.
        const cronHuman = t.schedule ? (formatCronHuman(t.schedule) ?? t.schedule) : null;
        const onceWhen = t.schedule_once ? new Date(t.schedule_once).toLocaleString() : null;
        const tzLabel = t.schedule ? ` (${t.schedule_tz || 'UTC'})` : '';
        const titleParts: string[] = [];
        if (t.schedule) titleParts.push(`${t.schedule}${tzLabel}${enabled ? '' : ' (paused)'}`);
        if (t.schedule_once) titleParts.push(`One-time: ${t.schedule_once}`);
        return (
          <span
            className="cursor-pointer text-[var(--accent)]"
            title={`${titleParts.join(' • ')} — click to edit`}
            onClick={() => onSchedule(t.target)}
          >
            {cronHuman && (
              <span className="inline-flex items-center gap-1" style={{ opacity: enabled ? 1 : 0.5 }}>
                <Clock className="size-3" aria-hidden="true" />
                {cronHuman}
                {!enabled && <span className="text-[var(--text-muted)] ml-2">(paused)</span>}
              </span>
            )}
            {cronHuman && onceWhen && <br />}
            {onceWhen && (
              <span className="inline-flex items-center gap-1">
                <Calendar className="size-3" aria-hidden="true" />
                Once: {onceWhen}
              </span>
            )}
            {!cronHuman && !onceWhen && <span className="text-[var(--text-muted)]">—</span>}
          </span>
        );
      },
    }),
    columnHelper.accessor(row => {
      // #92: combined status when both kinds are set.
      const tags: string[] = [];
      if (row.schedule) tags.push(row.schedule_enabled !== false ? 'active' : 'paused');
      if (row.schedule_once) tags.push('once');
      return tags.join(' + ') || '—';
    }, {
      id: 'status',
      header: ({ column }) => <SortHeader label="Status" column={column} />,
      cell: ({ row: { original: t } }) => {
        const labels: ReactNode[] = [];
        if (t.schedule) {
          labels.push(
            t.schedule_enabled !== false
              ? <span key="r" className="text-[var(--success)]">Active</span>
              : <span key="r" className="text-[var(--text-muted)]">Paused</span>,
          );
        }
        if (t.schedule_once) {
          labels.push(<span key="o" className="text-[var(--accent)]">One-time</span>);
        }
        return <>{labels.map((l, i) => <span key={i}>{i > 0 && ' + '}{l}</span>)}</>;
      },
    }),
    columnHelper.accessor(row => row.schedule_last_run || row.schedule_once || '', {
      id: 'nextRun',
      header: ({ column }) => <SortHeader label="Last Run" column={column} />,
      cell: ({ row: { original: t } }) => {
        const targetHistory = history[t.target] ?? [];
        const lastEntry = targetHistory.length > 0 ? targetHistory[targetHistory.length - 1] : null;
        const historyTooltip = targetHistory.length > 0
          ? targetHistory.slice(-5).reverse().map(h =>
              `${new Date(h.fired_at).toLocaleString()} — ${h.outcome}`
            ).join('\n')
          : undefined;
        return (
          <span title={historyTooltip}>
            {lastEntry
              ? <>
                  {timeAgo(lastEntry.fired_at)}
                  {lastEntry.outcome === 'enqueued' && (
                    <Circle className="ml-1 inline size-3 align-text-bottom text-[var(--accent)]" fill="currentColor" aria-label="enqueued" />
                  )}
                  {lastEntry.outcome === 'success' && (
                    <Check className="ml-1 inline size-3 align-text-bottom text-[var(--success)]" aria-label="success" />
                  )}
                  {lastEntry.outcome === 'failed' && (
                    <X className="ml-1 inline size-3 align-text-bottom text-[var(--destructive)]" aria-label="failed" />
                  )}
                </>
              : <span className="text-[var(--text-muted)]">{formatNextRun(t.schedule, t.schedule_last_run, t.schedule_once)}</span>
            }
          </span>
        );
      },
    }),
    columnHelper.accessor(row => row.pinned_version || row.server_version || '', {
      id: 'version',
      // Bug #29: disambiguate — this is the ESPHome compiler version the
      // schedule will build against (pinned per-device, else server default).
      header: ({ column }) => <SortHeader label="ESPHome" column={column} />,
      cell: ({ row: { original: t } }) => {
        const version = t.pinned_version || t.server_version || '—';
        return (
          <span className="text-[12px]">
            {version}
            {t.pinned_version && (
              <span title={`Pinned ESPHome version: ${t.pinned_version}`} className="ml-1 inline-flex align-text-bottom">
                <Pin className="size-3" aria-label="Pinned ESPHome version" />
              </span>
            )}
          </span>
        );
      },
    }),
    columnHelper.display({
      id: 'actions',
      cell: ({ row }) => (
        <Button variant="secondary" size="sm" onClick={() => onSchedule(row.original.target)}>
          Edit
        </Button>
      ),
    }),
  ], [onSchedule, history]);

  const table = useReactTable({
    data: filteredScheduled,
    columns,
    state: { sorting, rowSelection },
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row) => row.target,
  });

  const selectedTargets = table.getSelectedRowModel().rows.map(r => r.original.target);

  async function handleRemoveSelected() {
    const toRemove = selectedTargets.filter(t => scheduled.some(s => s.target === t));
    if (toRemove.length === 0) return;
    try {
      await Promise.all(toRemove.map(t => deleteTargetSchedule(t)));
      onToast(`Removed schedule from ${toRemove.length} device(s)`, 'success');
      setRowSelection({});
      onRefresh();
    } catch (err) {
      onToast('Remove failed: ' + (err as Error).message, 'error');
    }
  }

  return (
    <div className="block" id="tab-schedules">
      <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-sm">
        <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] bg-[var(--surface2)] px-4 py-3">
          <h2 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--text-muted)] mr-1">Schedules</h2>
          <div className="relative max-w-[280px]">
            <input
              type="text"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="Search schedules..."
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface2)] px-2.5 py-1 pr-7 text-[13px] text-[var(--text)] outline-none placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]"
            />
            {filter && (
              <button
                onClick={() => setFilter('')}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 border-none bg-transparent text-sm leading-none text-[var(--text-muted)] cursor-pointer px-0.5"
              >&times;</button>
            )}
          </div>
          <div className="actions">
            {/* #88: Actions dropdown — always visible, items disabled when nothing selected */}
            <DropdownMenu>
              <DropdownMenuTrigger className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2.5 h-7 text-[0.8rem] font-medium text-foreground hover:bg-muted cursor-pointer">
                Actions <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                  <DropdownMenuItem
                    onClick={handleRemoveSelected}
                    disabled={selectedTargets.length === 0}
                    title={selectedTargets.length === 0 ? 'Select one or more scheduled devices first' : undefined}
                  >
                    Remove Selected{selectedTargets.length > 0 ? ` (${selectedTargets.length})` : ''}
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              {table.getHeaderGroups().map(headerGroup => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map(header => (
                    <th
                      key={header.id}
                      aria-sort={header.column.getCanSort() ? getAriaSort(header.column) : undefined}
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(header.column.columnDef.header, header.getContext())}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.length === 0 ? (
                <tr className="empty-row"><td colSpan={7}>
                  {scheduled.length === 0
                    ? /* UX.1: the menu item this used to reference was removed in #93. */
                      'No devices have a schedule configured — click Upgrade on a device, then choose Scheduled.'
                    : 'No schedules match filter'}
                </td></tr>
              ) : (
                table.getRowModel().rows.map(row => (
                  <tr key={row.id}>
                    {row.getVisibleCells().map(cell => (
                      <td key={cell.id}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
