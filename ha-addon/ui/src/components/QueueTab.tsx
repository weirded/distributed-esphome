import { useMemo, useState } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
  type RowSelectionState,
  type SortingFn,
} from '@tanstack/react-table';
import type { Job, Target, Worker } from '../types';
import { Button } from './ui/button';
import { fmtDuration, getJobBadge, stripYaml, timeAgo, isJobSuccessful, isJobInProgress, isJobFailed, isJobFinished, isJobRetryable } from '../utils';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from './ui/dropdown-menu';

interface Props {
  queue: Job[];
  targets: Target[];
  workers: Worker[];
  onCancel: (ids: string[]) => void;
  onRetry: (ids: string[]) => void;
  onClear: (ids: string[]) => void;
  onRetryAllFailed: () => void;
  onClearSucceeded: () => void;
  onClearFinished: () => void;
  onOpenLog: (jobId: string) => void;
  onEdit: (target: string) => void;
}

const STATE_ORDER: Record<string, number> = {
  working: 0,
  pending: 1,
  timed_out: 2,
  failed: 3,
  success: 4,
};

// Custom sorting function: sort by STATE_ORDER, break ties by created_at descending.
// Registered as a named function so TanStack can reference it in column defs.
const stateSort: SortingFn<Job> = (rowA, rowB) => {
  const orderA = STATE_ORDER[rowA.original.state] ?? 9;
  const orderB = STATE_ORDER[rowB.original.state] ?? 9;
  if (orderA !== orderB) return orderA - orderB;
  // Secondary: newer jobs first
  return new Date(rowB.original.created_at).getTime() - new Date(rowA.original.created_at).getTime();
};

// Inline sort header — mirrors the pattern used in DevicesTab
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

const columnHelper = createColumnHelper<Job>();

export function QueueTab({
  queue,
  targets,
  workers,
  onCancel,
  onRetry,
  onClear,
  onRetryAllFailed,
  onClearSucceeded,
  onClearFinished,
  onOpenLog,
  onEdit,
}: Props) {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'created_at', desc: true }]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [filter, setFilter] = useState('');

  // Build target → display name map so queue shows friendly names
  const targetNameMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of targets) {
      map.set(t.target, t.friendly_name || t.device_name || stripYaml(t.target));
    }
    return map;
  }, [targets]);

  // Filter before handing data to TanStack (same pattern as DevicesTab)
  const filteredQueue = useMemo(() => {
    if (!filter) return queue;
    const q = filter.toLowerCase();
    return queue.filter(j => {
      const name = targetNameMap.get(j.target) || '';
      return (
        name.toLowerCase().includes(q) ||
        j.target.toLowerCase().includes(q) ||
        j.state.includes(q) ||
        (j.assigned_hostname || '').toLowerCase().includes(q)
      );
    });
  }, [queue, filter, targetNameMap]);

  const columns = useMemo(() => [
    columnHelper.display({
      id: 'select',
      header: ({ table }) => (
        <input
          type="checkbox"
          checked={table.getIsAllRowsSelected()}
          ref={el => {
            if (el) el.indeterminate = table.getIsSomeRowsSelected();
          }}
          onChange={table.getToggleAllRowsSelectedHandler()}
        />
      ),
      cell: ({ row }) => (
        <input
          type="checkbox"
          className="queue-cb"
          value={row.original.id}
          checked={row.getIsSelected()}
          onChange={row.getToggleSelectedHandler()}
        />
      ),
    }),
    columnHelper.accessor(row => targetNameMap.get(row.target) || stripYaml(row.target), {
      id: 'device',
      header: ({ column }) => <SortHeader label="Device" column={column} />,
      cell: ({ row: { original: job } }) => (
        <>
          <span className="device-name">{targetNameMap.get(job.target) || stripYaml(job.target)}</span>
          <div className="device-filename">{stripYaml(job.target)}</div>
        </>
      ),
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(row => row.state, {
      id: 'state',
      header: ({ column }) => <SortHeader label="State" column={column} />,
      cell: ({ row: { original: job } }) => {
        const { label: badgeLabel, cls: badgeCls } = getJobBadge(job);
        return <span className={badgeCls}>{badgeLabel}</span>;
      },
      sortingFn: stateSort,
    }),
    columnHelper.accessor(row => row.assigned_hostname || '', {
      id: 'worker',
      header: ({ column }) => <SortHeader label="Worker" column={column} />,
      cell: ({ row: { original: job } }) => {
        const assignedClient = job.assigned_client_id
          ? workers.find(c => c.client_id === job.assigned_client_id)
          : null;
        const pinnedClient = job.pinned_client_id
          ? workers.find(c => c.client_id === job.pinned_client_id)
          : null;

        const baseHostname = job.assigned_hostname || assignedClient?.hostname || null;
        const showSlot =
          baseHostname &&
          job.worker_id != null &&
          (assignedClient?.max_parallel_jobs || 1) > 1;
        const clientName = baseHostname
          ? showSlot
            ? `${baseHostname}/${job.worker_id}`
            : baseHostname
          : '—';

        const pinnedHostname = pinnedClient?.hostname || job.assigned_hostname;
        const showPinned =
          pinnedHostname && job.pinned_client_id && job.state === 'pending';

        return (
          <span style={{ fontSize: 12 }}>
            {clientName}
            {showPinned && (
              <><br /><span style={{ fontSize: 10, color: 'var(--text-muted)' }}>→ {pinnedHostname}</span></>
            )}
          </span>
        );
      },
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(row => row.created_at, {
      id: 'created_at',
      header: ({ column }) => <SortHeader label="Start Time" column={column} />,
      cell: ({ row: { original: job } }) => {
        const d = new Date(job.created_at);
        const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        return (
          <span style={{ fontSize: 12 }} title={d.toLocaleString()}>
            {time}
            <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{timeAgo(job.created_at)}</div>
          </span>
        );
      },
      sortingFn: 'datetime',
    }),
    columnHelper.accessor(row => row.finished_at ?? '', {
      id: 'finished_at',
      header: ({ column }) => <SortHeader label="Finish Time" column={column} />,
      cell: ({ row: { original: job } }) => {
        const inProgress = isJobInProgress(job);
        if (inProgress) {
          const elapsed = job.assigned_at
            ? fmtDuration((Date.now() - new Date(job.assigned_at).getTime()) / 1000)
            : '—';
          return <span style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>{elapsed}</span>;
        }
        if (!job.finished_at) return <span style={{ fontSize: 12 }}>—</span>;
        const d = new Date(job.finished_at);
        const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const dur = job.duration_seconds != null ? fmtDuration(job.duration_seconds) : null;
        return (
          <span style={{ fontSize: 12 }} title={d.toLocaleString()}>
            {time}
            {dur && <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{dur}</div>}
          </span>
        );
      },
      sortingFn: 'datetime',
    }),
    columnHelper.display({
      id: 'actions',
      header: () => 'Actions',
      cell: ({ row: { original: job } }) => {
        const inProgress = isJobInProgress(job);
        const hasLog = !!(job.log || inProgress);
        const canRetry = isJobRetryable(job);
        const canCancel = inProgress;
        return (
          <div style={{ display: 'flex', gap: 4 }}>
            {canCancel && (
              <Button variant="destructive" size="sm" onClick={() => onCancel([job.id])}>Cancel</Button>
            )}
            {canRetry && (
              <Button variant="warn" size="sm" onClick={() => onRetry([job.id])}>Retry</Button>
            )}
            {hasLog && (
              <Button variant="secondary" size="sm" onClick={() => onOpenLog(job.id)}>Log</Button>
            )}
            <Button variant="secondary" size="sm" onClick={() => onEdit(job.target)}>Edit</Button>
            {isJobFinished(job) && (
              <Button variant="secondary" size="sm" onClick={() => onClear([job.id])}>Clear</Button>
            )}
          </div>
        );
      },
    }),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [workers, onCancel, onRetry, onClear, onOpenLog, onEdit, targetNameMap]);

  const table = useReactTable({
    data: filteredQueue,
    columns,
    state: { sorting, rowSelection },
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: row => row.id,
  });

  const selectedIds = table.getSelectedRowModel().rows.map(r => r.original.id);

  function handleCancelSelected() {
    if (selectedIds.length > 0) onCancel(selectedIds);
  }

  function handleRetrySelected() {
    const retryable = selectedIds.filter(id => {
      const job = queue.find(j => j.id === id);
      return job && isJobRetryable(job);
    });
    if (retryable.length > 0) onRetry(retryable);
  }

  // Button state
  const hasFailedJobs = queue.some(j => isJobFailed(j));
  const hasSuccessfulJobs = queue.some(j => isJobSuccessful(j));
  const hasFinishedJobs = queue.some(j => isJobFinished(j));

  return (
    <div className="block" id="tab-queue">
      <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-sm">
        <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] bg-[var(--surface2)] px-4 py-3">
          <h2 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--text-muted)] mr-1">Queue</h2>
          <div className="relative max-w-[280px]">
            <input
              type="text"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="Search queue..."
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
            {/* Retry dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger className="inline-flex items-center gap-1 rounded-lg bg-[#78350f] px-2.5 py-1 text-xs font-medium text-[#fcd34d] hover:bg-[#92400e] cursor-pointer">
                Retry &#9662;
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                  <DropdownMenuItem onClick={onRetryAllFailed} disabled={!hasFailedJobs}>
                    Retry All Failed
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={handleRetrySelected} disabled={queue.length === 0}>
                    Retry Selected
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={handleCancelSelected} disabled={queue.length === 0}>
                    Cancel Selected
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Clear dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface2)] px-2.5 py-1 text-xs font-medium text-[var(--text)] hover:bg-[var(--border)] cursor-pointer">
                Clear &#9662;
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                  <DropdownMenuItem onClick={onClearSucceeded} disabled={!hasSuccessfulJobs}>
                    Clear Succeeded
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={onClearFinished} disabled={!hasFinishedJobs}>
                    Clear All Finished
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
                <tr className="empty-row"><td colSpan={6}>No jobs in queue</td></tr>
              ) : (
                table.getRowModel().rows.map(row => (
                  <tr key={row.id} data-job={row.original.id}>
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
