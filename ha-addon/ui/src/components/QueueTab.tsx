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
  onClearAll: () => void;
  onOpenLog: (jobId: string) => void;
  onEdit: (target: string) => void;
}

const STATE_ORDER: Record<string, number> = {
  working: 0,
  pending: 1,
  timed_out: 2,
  failed: 3,
  cancelled: 4,
  success: 5,
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
  onClearAll,
  onOpenLog,
  onEdit,
}: Props) {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'state', desc: false }]);
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
        return (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span className={badgeCls}>{badgeLabel}</span>
            {/* #23: a follow-up job is "queued behind" another running job
                for the same target. Show a small badge next to the State so
                the user knows it won't start until the predecessor finishes. */}
            {job.is_followup && job.state === 'pending' && (
              <span
                className="inline-flex items-center rounded-full border border-[var(--accent)]/40 bg-[var(--accent)]/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-[var(--accent)]"
                title="This compile is queued and will start after the running compile for the same device finishes. Re-clicking Upgrade replaces this entry instead of adding more."
              >
                Queued
              </span>
            )}
          </span>
        );
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
        const showPinnedHint =
          pinnedHostname && job.pinned_client_id && job.state === 'pending';

        // #17: pushpin icon when the user explicitly pinned the job to a
        // specific worker (UpgradeModal worker selector). Visible on every
        // pinned row regardless of state, so the user can audit history.
        return (
          <span style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            {job.scheduled && (
              <span
                title={job.schedule_kind === 'once' ? 'Triggered by one-time schedule' : 'Triggered by recurring schedule'}
                aria-label={job.schedule_kind === 'once' ? 'one-time scheduled run' : 'recurring scheduled run'}
                style={{ color: 'var(--accent)', fontSize: 11, lineHeight: 1 }}
              >
                {job.schedule_kind === 'once' ? '📅' : '🕐'}
              </span>
            )}
            {job.pinned_client_id && (
              <span
                title={
                  pinnedHostname
                    ? `Pinned to ${pinnedHostname} via Upgrade modal`
                    : 'Pinned to a specific worker via Upgrade modal'
                }
                aria-label="pinned to specific worker"
                style={{ color: 'var(--accent)', fontSize: 11, lineHeight: 1 }}
              >
                📌
              </span>
            )}
            <span>
              {clientName}
              {showPinnedHint && !job.assigned_hostname && (
                <><br /><span style={{ fontSize: 10, color: 'var(--text-muted)' }}>→ {pinnedHostname}</span></>
              )}
            </span>
          </span>
        );
      },
      sortingFn: 'alphanumeric',
    }),
    // #17: ESPHome version column. Shows the version stamped on each job,
    // which may differ from the global default when the user picked a
    // non-default in the Upgrade modal.
    columnHelper.accessor(row => row.esphome_version || '', {
      id: 'esphome_version',
      header: ({ column }) => <SortHeader label="Version" column={column} />,
      cell: ({ row: { original: job } }) => {
        const target = targets.find(t => t.target === job.target);
        const isPinned = target?.pinned_version && target.pinned_version === job.esphome_version;
        return (
          <span style={{ fontSize: 12 }}>
            {job.esphome_version || <span style={{ color: 'var(--text-muted)' }}>—</span>}
            {isPinned && <span title={`Pinned to ${target.pinned_version}`} style={{ marginLeft: 4, fontSize: 10 }}>📌</span>}
          </span>
        );
      },
      sortingFn: 'alphanumeric',
    }),
    // #21/#92: triggered-by column — recurring schedule, one-time, or user.
    columnHelper.accessor(row => row.scheduled ? (row.schedule_kind ?? 'schedule') : 'user', {
      id: 'triggered_by',
      header: ({ column }) => <SortHeader label="Triggered" column={column} />,
      cell: ({ row: { original: job } }) => {
        if (!job.scheduled) {
          return <span style={{ fontSize: 12 }} title="Triggered by user action">👤 User</span>;
        }
        if (job.schedule_kind === 'once') {
          return <span style={{ fontSize: 12 }} title="Triggered by one-time schedule">📅 One-time</span>;
        }
        // Default for scheduled (covers 'recurring' and legacy nulls).
        return <span style={{ fontSize: 12 }} title="Triggered by recurring cron schedule">🕐 Recurring</span>;
      },
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(row => new Date(row.created_at), {
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
    columnHelper.accessor(row => (row.finished_at ? new Date(row.finished_at) : null), {
      id: 'finished_at',
      header: ({ column }) => <SortHeader label="Finish Time" column={column} />,
      cell: ({ row: { original: job } }) => {
        const inProgress = isJobInProgress(job);
        if (inProgress) {
          // Wall-clock elapsed since enqueue (not since worker pickup)
          const elapsed = fmtDuration((Date.now() - new Date(job.created_at).getTime()) / 1000);
          return <span style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>Elapsed {elapsed}</span>;
        }
        if (!job.finished_at) return <span style={{ fontSize: 12 }}>—</span>;
        const finished = new Date(job.finished_at);
        const time = finished.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        // Duration = wall clock from enqueue to finish, not just worker compile time
        const wallSeconds = (finished.getTime() - new Date(job.created_at).getTime()) / 1000;
        const dur = wallSeconds >= 0 ? fmtDuration(wallSeconds) : null;
        return (
          <span style={{ fontSize: 12 }} title={finished.toLocaleString()}>
            {time}
            {dur && <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>Took {dur}</div>}
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
              // #20: successful jobs get "Rerun" (green) since "Retry" implies
              // failure recovery — re-running a successful job is just a
              // re-compile, not a retry. Failed/timed-out jobs keep "Retry"
              // (warn / amber).
              isJobSuccessful(job)
                ? <Button variant="success" size="sm" onClick={() => onRetry([job.id])}>Rerun</Button>
                : <Button variant="warn" size="sm" onClick={() => onRetry([job.id])}>Retry</Button>
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
              <DropdownMenuTrigger className="inline-flex items-center gap-1 rounded-lg border border-transparent bg-[#78350f] px-2.5 h-7 text-[0.8rem] font-medium text-[#fcd34d] hover:bg-[#92400e] cursor-pointer">
                Retry <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
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
              <DropdownMenuTrigger className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2.5 h-7 text-[0.8rem] font-medium text-foreground hover:bg-muted cursor-pointer">
                Clear <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                  <DropdownMenuItem onClick={onClearSucceeded} disabled={!hasSuccessfulJobs}>
                    Clear Succeeded
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={onClearFinished} disabled={!hasFinishedJobs}>
                    Clear All Finished
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={onClearAll} disabled={queue.length === 0}>
                    Clear Entire Queue
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
