import { useMemo, useState } from 'react';
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
import { stripYaml, timeAgo, formatCronHuman } from '../utils';
import { Button } from './ui/button';
import { deleteTargetSchedule } from '../api/client';

function SortHeader({ label, column }: {
  label: string;
  column: { getIsSorted: () => false | 'asc' | 'desc'; toggleSorting: (desc?: boolean) => void; getCanSort: () => boolean };
}) {
  const sorted = column.getIsSorted();
  const indicator = sorted === 'asc' ? ' \u25b2' : sorted === 'desc' ? ' \u25bc' : '';
  const title = sorted === 'asc' ? 'Click to sort descending' : sorted === 'desc' ? 'Click to reset sort' : 'Click to sort ascending';
  return (
    <span
      onClick={() => column.toggleSorting(sorted === 'asc')}
      style={{ cursor: 'pointer', userSelect: 'none' }}
      title={title}
    >
      {label}{indicator}
    </span>
  );
}

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

  const [sorting, setSorting] = useState<SortingState>([]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [filter, setFilter] = useState('');

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
        let label: string;
        if (t.schedule_once && !t.schedule) {
          label = `Once: ${new Date(t.schedule_once).toLocaleString()}`;
        } else if (t.schedule) {
          label = formatCronHuman(t.schedule) ?? t.schedule;
        } else {
          label = '—';
        }
        return (
          <span style={{ opacity: enabled ? 1 : 0.5 }} title={t.schedule ?? undefined}>
            {label}
            {!enabled && t.schedule && <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>(paused)</span>}
          </span>
        );
      },
    }),
    columnHelper.accessor(row => row.schedule_once ? 'once' : row.schedule_enabled !== false ? 'active' : 'paused', {
      id: 'status',
      header: ({ column }) => <SortHeader label="Status" column={column} />,
      cell: ({ row: { original: t } }) => {
        if (t.schedule_once) return <span style={{ color: 'var(--accent)' }}>One-time</span>;
        if (t.schedule_enabled !== false) return <span style={{ color: 'var(--success)' }}>Active</span>;
        return <span style={{ color: 'var(--text-muted)' }}>Paused</span>;
      },
    }),
    columnHelper.accessor(row => row.schedule_last_run || row.schedule_once || '', {
      id: 'nextRun',
      header: ({ column }) => <SortHeader label="Next / Last Run" column={column} />,
      cell: ({ row: { original: t } }) => (
        <span>{formatNextRun(t.schedule, t.schedule_last_run, t.schedule_once)}</span>
      ),
    }),
    columnHelper.accessor(row => row.pinned_version || row.server_version || '', {
      id: 'version',
      header: ({ column }) => <SortHeader label="Version" column={column} />,
      cell: ({ row: { original: t } }) => {
        const version = t.pinned_version || t.server_version || '—';
        return (
          <span style={{ fontFamily: 'monospace' }}>
            {version}
            {t.pinned_version && <span style={{ marginLeft: 4 }}>📌</span>}
          </span>
        );
      },
    }),
    columnHelper.display({
      id: 'actions',
      cell: ({ row }) => (
        <Button variant="secondary" size="xs" onClick={() => onSchedule(row.original.target)}>
          Edit
        </Button>
      ),
    }),
  ], [onSchedule]);

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

  if (scheduled.length === 0) {
    return (
      <div className="block" id="tab-schedules">
        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-sm">
          <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] bg-[var(--surface2)] px-4 py-3">
            <h2 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--text-muted)] mr-1">Schedules</h2>
          </div>
          <div className="p-8 text-center text-[var(--text-muted)]">
            <p style={{ fontSize: 14 }}>No devices have a schedule configured.</p>
            <p style={{ fontSize: 12, marginTop: 8 }}>
              Open a device's hamburger menu and choose "Schedule Upgrade..." to set one up.
            </p>
          </div>
        </div>
      </div>
    );
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
            {selectedTargets.length > 0 && (
              <Button variant="destructive" size="sm" onClick={handleRemoveSelected}>
                Remove Selected ({selectedTargets.length})
              </Button>
            )}
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              {table.getHeaderGroups().map(headerGroup => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map(header => (
                    <th key={header.id}>
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
                <tr className="empty-row"><td colSpan={7}>No schedules match filter</td></tr>
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
