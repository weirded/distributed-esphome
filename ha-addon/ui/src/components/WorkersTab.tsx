import { useCallback, useMemo, useRef, useState } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from '@tanstack/react-table';
import type { Job, SystemInfo, Worker } from '../types';
import { Button } from './ui/button';
import { stripYaml } from '../utils';
import { StatusDot } from './StatusDot';

interface Props {
  workers: Worker[];
  queue: Job[];
  serverClientVersion?: string;
  onRemove: (id: string) => void;
  onSetParallelJobs: (id: string, count: number) => void;
  onCleanCache: (id: string) => void;
  onConnectWorker: () => void;
}

function workerPlatformHtml(si: SystemInfo): React.ReactNode {
  const lines: React.ReactNode[] = [];
  if (si.os_version) {
    lines.push(<span key="os" style={{ fontSize: 10, color: 'var(--text-muted)' }}>{si.os_version}</span>);
  }
  if (si.cpu_model) {
    lines.push(<span key="cpu" style={{ fontSize: 10, color: 'var(--text-muted)' }}>{si.cpu_model}</span>);
  }
  const hwParts: string[] = [];
  if (si.cpu_arch) hwParts.push(si.cpu_arch);
  if (si.cpu_cores) hwParts.push(si.cpu_cores + ' cores');
  if (si.total_memory) hwParts.push(si.total_memory);
  if (hwParts.length) {
    lines.push(<span key="hw" style={{ fontSize: 10, color: 'var(--text-muted)' }}>{hwParts.join(' · ')}</span>);
  }
  const metrics: string[] = [];
  if (si.perf_score != null) metrics.push(`Score: ${si.perf_score}`);
  if (si.cpu_usage != null) metrics.push(`CPU: ${si.cpu_usage}%`);
  if (metrics.length) {
    lines.push(
      <span key="metrics" style={{ fontSize: 10, color: 'var(--text-muted)' }} title="Perf score (SHA256 benchmark) · CPU utilization">
        {metrics.join(' · ')}
      </span>
    );
  }
  // Disk space on separate line (#109)
  if (si.disk_free && si.disk_total) {
    const pctFree = si.disk_used_pct != null ? 100 - si.disk_used_pct : null;
    const diskColor = (si.disk_used_pct ?? 0) > 90 ? 'var(--danger)' : (si.disk_used_pct ?? 0) > 80 ? 'var(--warn)' : 'var(--text-muted)';
    const pctStr = pctFree != null ? ` (${pctFree}% free)` : '';
    lines.push(
      <span key="disk" style={{ fontSize: 10, color: diskColor }} title={`Build volume: ${si.disk_free} free of ${si.disk_total} (${si.disk_used_pct ?? '?'}% used)`}>
        Disk: {si.disk_free} / {si.disk_total}{pctStr}
      </span>
    );
  }
  return lines.length === 0 ? null : (
    <>{lines.map((l, i) => <>{i > 0 && <br />}{l}</>)}</>
  );
}

function ClientVersionCell({ ver, scv }: { ver?: string; scv?: string }) {
  if (!ver) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  if (!scv || ver === scv) {
    return <code style={{ fontSize: 11, color: 'var(--text-muted)' }}>{ver}</code>;
  }
  return (
    <code style={{ fontSize: 11, color: 'var(--warn)' }} title={`Outdated — server: ${scv}`}>
      {ver} ↑
    </code>
  );
}

/* Debounced slot control (#108) */
function SlotControl({ slots, requested, onSet }: { slots: number; requested: number | null; onSet: (n: number) => void }) {
  const [localValue, setLocalValue] = useState<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const displayed = localValue ?? slots;
  const pending = localValue != null ? localValue : (requested != null && requested !== slots ? requested : null);

  const change = useCallback((delta: number) => {
    const next = Math.max(0, Math.min(32, (localValue ?? slots) + delta));
    setLocalValue(next);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      onSet(next);
      setLocalValue(null);
      timerRef.current = null;
    }, 600);
  }, [localValue, slots, onSet]);

  return (
    <span
      style={{ display: 'inline-flex', alignItems: 'center', gap: 2, fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}
      title="Parallel build slots (0 = paused, accepts no jobs)"
    >
      <Button
        variant="secondary"
        size="sm"
        className="px-1.5 text-xs min-w-0"
        style={{ padding: '1px 6px', fontSize: 11, minWidth: 0 }}
        disabled={displayed <= 0}
        onClick={() => change(-1)}
      >-</Button>
      <span style={{ minWidth: 16, textAlign: 'center' }}>
        {pending != null && pending !== displayed ? `${slots}→${pending}` : String(displayed)}
      </span>
      <Button
        variant="secondary"
        size="sm"
        className="px-1.5 text-xs min-w-0"
        style={{ padding: '1px 6px', fontSize: 11, minWidth: 0 }}
        onClick={() => change(1)}
      >+</Button>
    </span>
  );
}

const LOCAL_WORKER_HOSTNAME = 'local-worker';

// Sort accessor values for each sortable column
function getWorkerSortValue(w: Worker, colId: string): string {
  if (colId === 'hostname') return w.hostname;
  if (colId === 'status') {
    if ((w.max_parallel_jobs ?? 0) === 0) return 'paused';
    return w.online ? 'online' : 'offline';
  }
  if (colId === 'version') return w.client_version || '';
  return '';
}

const columnHelper = createColumnHelper<Worker>();

export function WorkersTab({ workers, queue, serverClientVersion, onRemove, onSetParallelJobs, onCleanCache, onConnectWorker }: Props) {
  const [filter, setFilter] = useState('');
  const [sorting, setSorting] = useState<SortingState>([{ id: 'hostname', desc: false }]);

  const online = workers.filter(c => c.online).length;
  const countText = online + '/' + workers.length + ' online';

  // Filter before handing to TanStack — keeps filter state local, same as DevicesTab pattern
  const filteredWorkers = useMemo(() => {
    if (!filter) return workers;
    const q = filter.toLowerCase();
    return workers.filter(w =>
      w.hostname.toLowerCase().includes(q)
      || (w.system_info?.os_version || '').toLowerCase().includes(q)
      || (w.system_info?.cpu_model || '').toLowerCase().includes(q)
      || (w.client_version || '').toLowerCase().includes(q)
    );
  }, [workers, filter]);

  const columns = useMemo(() => [
    columnHelper.accessor(w => getWorkerSortValue(w, 'hostname'), {
      id: 'hostname',
      header: 'Hostname',
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(w => getWorkerSortValue(w, 'status'), {
      id: 'status',
      header: 'Status',
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(w => getWorkerSortValue(w, 'version'), {
      id: 'version',
      header: 'Version',
      sortingFn: 'alphanumeric',
    }),
    // Non-sortable display columns — included so flexRender can handle headers uniformly
    columnHelper.display({ id: 'platform', header: 'Platform' }),
    columnHelper.display({ id: 'currentJob', header: 'Current Job' }),
    columnHelper.display({ id: 'slots', header: 'Slots' }),
    columnHelper.display({ id: 'actions', header: '' }),
  ], []);

  const table = useReactTable({
    data: filteredWorkers,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    // Disable multi-sort; simple single-column sort
    enableMultiSort: false,
  });

  // TanStack sorted rows, then pin local-worker to top (#107)
  const sortedWorkers = useMemo(() => {
    const tanstackRows = table.getSortedRowModel().rows.map(r => r.original);
    return [
      ...tanstackRows.filter(w => w.hostname === LOCAL_WORKER_HOSTNAME),
      ...tanstackRows.filter(w => w.hostname !== LOCAL_WORKER_HOSTNAME),
    ];
  }, [table.getSortedRowModel().rows]); // eslint-disable-line react-hooks/exhaustive-deps

  // Expand each worker into per-slot rows after TanStack sorting
  const rows: React.ReactNode[] = [];

  for (const c of sortedWorkers) {
    const slots = c.max_parallel_jobs ?? 0;
    const isLocal = c.hostname === LOCAL_WORKER_HOSTNAME;
    const paused = slots === 0;
    const statusEl = paused
      ? <StatusDot status="paused" />
      : c.online
        ? <StatusDot status="online" />
        : <StatusDot status="offline" />;

    const rowStyle: React.CSSProperties = {
      ...(paused ? { opacity: 0.6 } : {}),
      ...(isLocal ? { background: 'var(--surface2)' } : {}),
    };

    const displaySlots = Math.max(slots, 1); // show at least 1 row even if 0 slots
    for (let slot = 1; slot <= displaySlots; slot++) {
      const slotJob = slots > 0 ? queue.find(
        j =>
          j.assigned_client_id === c.client_id &&
          (j.worker_id === slot || (slot === 1 && j.worker_id == null)) &&
          j.state === 'working',
      ) : null;

      const slotNameEl = slots > 1
        ? <>{c.hostname}<span style={{ color: 'var(--text-muted)', fontSize: 11 }}>/{slot}</span></>
        : <>{c.hostname}</>;

      const jobEl = slots === 0
        ? <span style={{ color: 'var(--text-muted)', fontSize: 12, fontStyle: 'italic' }}>Paused</span>
        : slotJob
          ? <>
              <code style={{ fontSize: 12 }}>{stripYaml(slotJob.target)}</code>
              {slotJob.status_text && (
                <><br /><span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{slotJob.status_text}</span></>
              )}
            </>
          : <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>Idle</span>;

      const uptimeEl = c.system_info?.uptime
        ? <><br /><span style={{ fontSize: 10, color: 'var(--text-muted)' }} title="Worker process uptime">up {c.system_info.uptime}</span></>
        : null;

      if (slot === 1) {
        rows.push(
          <tr key={`${c.client_id}-1`} style={rowStyle}>
            <td>
              {slotNameEl}
              {isLocal && <span style={{ fontSize: 9, color: 'var(--accent)', marginLeft: 6, textTransform: 'uppercase', fontWeight: 600 }}>built-in</span>}
            </td>
            <td>{c.system_info ? workerPlatformHtml(c.system_info) : null}</td>
            <td>{statusEl}{uptimeEl}</td>
            <td>{jobEl}</td>
            <td><ClientVersionCell ver={c.client_version} scv={serverClientVersion} /></td>
            <td>
              <SlotControl
                slots={slots}
                requested={c.requested_max_parallel_jobs ?? null}
                onSet={(n) => onSetParallelJobs(c.client_id, n)}
              />
            </td>
            <td>
              {c.online ? (
                <Button variant="secondary" size="sm" onClick={() => onCleanCache(c.client_id)}>Clean Cache</Button>
              ) : !isLocal ? (
                <Button variant="destructive" size="sm" onClick={() => onRemove(c.client_id)}>Remove</Button>
              ) : null}
            </td>
          </tr>
        );
      } else {
        rows.push(
          <tr key={`${c.client_id}-${slot}`} style={rowStyle}>
            <td>{slotNameEl}</td>
            <td></td>
            <td></td>
            <td>{jobEl}</td>
            <td></td>
            <td></td>
            <td></td>
          </tr>
        );
      }
    }
  }

  // Build header cells from TanStack column defs in the order we want to render them
  // Column order: hostname, platform, status, currentJob, version, slots, actions
  const HEADER_ORDER = ['hostname', 'platform', 'status', 'currentJob', 'version', 'slots', 'actions'];
  const headerCells = table.getHeaderGroups()[0].headers;
  const headerByid = Object.fromEntries(headerCells.map(h => [h.id, h]));

  function renderHeader(id: string) {
    const h = headerByid[id];
    if (!h) return <th key={id}></th>;
    const canSort = h.column.getCanSort();
    const sorted = h.column.getIsSorted();
    const indicator = sorted === 'asc' ? ' \u25b2' : sorted === 'desc' ? ' \u25bc' : '';
    const title = !canSort ? undefined
      : sorted === 'asc' ? 'Click to sort descending'
      : sorted === 'desc' ? 'Click to reset sort'
      : 'Click to sort ascending';
    return (
      <th
        key={id}
        onClick={canSort ? h.column.getToggleSortingHandler() : undefined}
        style={canSort ? { cursor: 'pointer', userSelect: 'none' } : undefined}
        title={title}
      >
        {flexRender(h.column.columnDef.header, h.getContext())}{indicator}
      </th>
    );
  }

  return (
    <div className="block" id="tab-workers">
      <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-sm">
        <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] bg-[var(--surface2)] px-4 py-3">
          <h2 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--text-muted)] mr-1">Workers</h2>
          <div className="relative max-w-[280px]">
            <input
              type="text"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="Search workers..."
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
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{countText}</span>
            <Button variant="secondary" size="sm" onClick={() => {
              const onlineWorkers = workers.filter(w => w.online);
              onlineWorkers.forEach(w => onCleanCache(w.client_id));
            }} disabled={!workers.some(w => w.online)}>Clean All Caches</Button>
            <Button size="sm" onClick={onConnectWorker}>+ Connect Worker</Button>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {HEADER_ORDER.map(id => renderHeader(id))}
              </tr>
            </thead>
            <tbody>
              {workers.length === 0 ? (
                <tr className="empty-row">
                  <td colSpan={7}>No workers registered — click &quot;+ Connect Worker&quot; to add one</td>
                </tr>
              ) : rows}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
