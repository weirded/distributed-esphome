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
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
} from './ui/dropdown-menu';
import { stripYaml, timeAgo } from '../utils';
import { StatusDot } from './StatusDot';

interface Props {
  workers: Worker[];
  queue: Job[];
  serverClientVersion?: string;
  minImageVersion?: string;
  onRemove: (id: string) => void;
  onSetParallelJobs: (id: string, count: number) => void;
  onCleanCache: (id: string) => void;
  onCleanAllCaches: () => void;
  onConnectWorker: (preset?: import('../types').WorkerPreset | null) => void;
}

function workerPlatformHtml(si: SystemInfo): React.ReactNode {
  const lines: React.ReactNode[] = [];
  if (si.os_version) {
    lines.push(<span key="os" className="text-[10px] text-[var(--text-muted)]">{si.os_version}</span>);
  }
  if (si.cpu_model) {
    lines.push(<span key="cpu" className="text-[10px] text-[var(--text-muted)]">{si.cpu_model}</span>);
  }
  const hwParts: string[] = [];
  if (si.cpu_arch) hwParts.push(si.cpu_arch);
  if (si.cpu_cores) hwParts.push(si.cpu_cores + ' cores');
  if (si.total_memory) hwParts.push(si.total_memory);
  if (hwParts.length) {
    lines.push(<span key="hw" className="text-[10px] text-[var(--text-muted)]">{hwParts.join(' · ')}</span>);
  }
  const metrics: string[] = [];
  if (si.perf_score != null) metrics.push(`Score: ${si.perf_score}`);
  if (si.cpu_usage != null) metrics.push(`CPU: ${si.cpu_usage}%`);
  if (metrics.length) {
    lines.push(
      <span key="metrics" className="text-[10px] text-[var(--text-muted)]" title="Perf score (SHA256 benchmark) · CPU utilization">
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
      <span key="disk" className="text-[10px]" style={{ color: diskColor }} title={`Build volume: ${si.disk_free} free of ${si.disk_total} (${si.disk_used_pct ?? '?'}% used)`}>
        Disk: {si.disk_free} / {si.disk_total}{pctStr}
      </span>
    );
  }
  // 5.2: build cache stats
  if (si.cached_targets != null) {
    const cacheStr = si.cache_size_mb != null ? ` (${si.cache_size_mb} MB)` : '';
    lines.push(
      <span key="cache" className="text-[10px] text-[var(--text-muted)]" title={`Build cache: ${si.cached_targets} target(s) cached${cacheStr}`}>
        Cache: {si.cached_targets} target{si.cached_targets !== 1 ? 's' : ''}{cacheStr}
      </span>
    );
  }
  return lines.length === 0 ? null : (
    <>{lines.map((l, i) => <>{i > 0 && <br />}{l}</>)}</>
  );
}

function ClientVersionCell({
  ver,
  scv,
  imageVer,
  minImageVer,
  onReinstall,
}: {
  ver?: string;
  scv?: string;
  imageVer?: string | null;
  minImageVer?: string;
  onReinstall: () => void;
}) {
  // Docker image version is checked first — a stale image blocks source-code
  // auto-updates entirely, so that's the more important warning to surface.
  const imageStale = imageIsStale(imageVer, minImageVer);

  if (!ver) {
    return (
      <span className="text-[var(--text-muted)]">
        —
        {imageStale && <ImageStaleBadge imageVer={imageVer} minImageVer={minImageVer} onReinstall={onReinstall} />}
      </span>
    );
  }

  const isOutdated = scv && ver !== scv;
  const color = imageStale ? 'var(--destructive)' : isOutdated ? 'var(--warn)' : 'var(--text-muted)';
  const title = isOutdated ? `Source outdated — server: ${scv}` : undefined;

  return (
    <span className="inline-flex items-center gap-1">
      <code className="text-[11px]" style={{ color }} title={title}>
        {ver}
        {isOutdated && ' ↑'}
      </code>
      {imageStale && <ImageStaleBadge imageVer={imageVer} minImageVer={minImageVer} onReinstall={onReinstall} />}
    </span>
  );
}

function ImageStaleBadge({
  imageVer,
  minImageVer,
  onReinstall,
}: {
  imageVer?: string | null;
  minImageVer?: string;
  onReinstall: () => void;
}) {
  const reported = imageVer ?? 'pre-LIB.0';
  return (
    <button
      type="button"
      onClick={onReinstall}
      title={
        `This worker's Docker image is out of date ` +
        `(IMAGE_VERSION=${reported}, server requires ${minImageVer}). ` +
        `Source-code auto-updates are disabled until the image is rebuilt.\n\n` +
        `We recommend reinstalling the worker using the latest "docker run" ` +
        `command from the Connect Worker modal — click this badge to open it.`
      }
      className="inline-flex items-center rounded-full border border-[var(--destructive)] bg-[var(--destructive)]/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-[var(--destructive)] cursor-pointer hover:bg-[var(--destructive)]/20"
    >
      image stale
    </button>
  );
}

/** Return true iff the reported image version is missing or below the server minimum. */
function imageIsStale(reported: string | null | undefined, minimum: string | undefined): boolean {
  if (!minimum) return false; // server doesn't enforce a minimum
  if (reported == null) return true; // pre-LIB.0 worker
  const r = parseInt(reported, 10);
  const m = parseInt(minimum, 10);
  if (Number.isNaN(r) || Number.isNaN(m)) return false;
  return r < m;
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
      className="inline-flex items-center gap-0.5 text-[11px] text-[var(--text-muted)] whitespace-nowrap"
      title="Parallel build slots (0 = paused, accepts no jobs)"
    >
      <Button
        variant="secondary"
        size="sm"
        className="px-1.5 py-px text-[11px] min-w-0"
        disabled={displayed <= 0}
        onClick={() => change(-1)}
      >-</Button>
      <span className="min-w-[16px] text-center">
        {pending != null && pending !== displayed ? `${slots}→${pending}` : String(displayed)}
      </span>
      <Button
        variant="secondary"
        size="sm"
        className="px-1.5 py-px text-[11px] min-w-0"
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

export function WorkersTab({ workers, queue, serverClientVersion, minImageVersion, onRemove, onSetParallelJobs, onCleanCache, onCleanAllCaches, onConnectWorker }: Props) {
  const [filter, setFilter] = useState('');
  const [sorting, setSorting] = useState<SortingState>([{ id: 'hostname', desc: false }]);


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
    };
    const rowClass = isLocal ? 'local-worker-row' : '';

    const displaySlots = Math.max(slots, 1); // show at least 1 row even if 0 slots
    for (let slot = 1; slot <= displaySlots; slot++) {
      const slotJob = slots > 0 ? queue.find(
        j =>
          j.assigned_client_id === c.client_id &&
          (j.worker_id === slot || (slot === 1 && j.worker_id == null)) &&
          j.state === 'working',
      ) : null;

      const slotNameEl = slots > 1
        ? <>{c.hostname}<span className="text-[11px] text-[var(--text-muted)]">/{slot}</span></>
        : <>{c.hostname}</>;

      const jobEl = slots === 0
        ? <span className="text-[12px] italic text-[var(--text-muted)]">Paused</span>
        : slotJob
          ? <>
              <code className="text-[12px]">{stripYaml(slotJob.target)}</code>
              {slotJob.status_text && (
                <><br /><span className="text-[10px] text-[var(--text-muted)]">{slotJob.status_text}</span></>
              )}
            </>
          : <span className="text-[12px] text-[var(--text-muted)]">Idle</span>;

      // When offline, show how long it's been gone instead of stale process uptime.
      // When online, show worker process uptime from the last heartbeat.
      let uptimeEl: React.ReactNode = null;
      if (!c.online && c.last_seen) {
        const duration = timeAgo(c.last_seen).replace(/ ago$/, '');
        uptimeEl = (
          <><br /><span className="text-[10px] text-[var(--text-muted)]" title={`Last heartbeat: ${new Date(c.last_seen).toLocaleString()}`}>offline for {duration}</span></>
        );
      } else if (c.online && c.system_info?.uptime) {
        uptimeEl = (
          <><br /><span className="text-[10px] text-[var(--text-muted)]" title="Worker process uptime">up {c.system_info.uptime}</span></>
        );
      }

      if (slot === 1) {
        rows.push(
          <tr key={`${c.client_id}-1`} style={rowStyle} className={rowClass}>
            <td>
              {slotNameEl}
              {isLocal && <span className="ml-1.5 text-[9px] font-semibold uppercase text-[var(--accent)]">built-in</span>}
            </td>
            <td>{c.system_info ? workerPlatformHtml(c.system_info) : null}</td>
            <td>{statusEl}{uptimeEl}</td>
            <td>{jobEl}</td>
            <td><ClientVersionCell ver={c.client_version} scv={serverClientVersion} imageVer={c.image_version} minImageVer={minImageVersion} onReinstall={() => onConnectWorker({
              hostname: c.hostname,
              max_parallel_jobs: c.max_parallel_jobs,
              host_platform: c.system_info?.os_version,
            })} /></td>
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
          <tr key={`${c.client_id}-${slot}`} style={rowStyle} className={rowClass}>
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
            {/* #88: standardized layout — primary "add new" action FIRST, Actions dropdown LAST */}
            <Button size="sm" onClick={() => onConnectWorker()}>+ Connect Worker</Button>
            <DropdownMenu>
              <DropdownMenuTrigger className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2.5 h-7 text-[0.8rem] font-medium text-foreground hover:bg-muted cursor-pointer">
                Actions <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                  <DropdownMenuItem onClick={onCleanAllCaches} disabled={!workers.some(w => w.online)}>
                    Clean All Caches
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
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
