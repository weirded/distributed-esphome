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
import { getJobBadge, stripYaml, timeAgo, usePersistedState } from '../utils';
import { StatusDot } from './StatusDot';
import { SortHeader, getAriaSort } from './ui/sort-header';

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
  onViewLogs: (clientId: string) => void;
  // #109: "Request diagnostics" runs py-spy on the worker and downloads
  // the thread dump. Online-workers only (offline workers can't reply).
  onRequestDiagnostics: (id: string) => void;
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
  hostname,
  onReinstall,
}: {
  ver?: string;
  scv?: string;
  imageVer?: string | null;
  minImageVer?: string;
  /** Worker hostname — used as the default container name in the
   *  WU.2 refresh-command tooltip. Falls back to a placeholder when
   *  the worker hasn't reported a hostname yet. */
  hostname?: string;
  onReinstall: () => void;
}) {
  // Docker image version is checked first — a stale image blocks source-code
  // auto-updates entirely, so that's the more important warning to surface.
  const imageStale = imageIsStale(imageVer, minImageVer);

  if (!ver) {
    return (
      <span className="text-[var(--text-muted)]">
        —
        {imageStale && <ImageStaleBadge imageVer={imageVer} minImageVer={minImageVer} hostname={hostname} onReinstall={onReinstall} />}
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
      {imageStale && <ImageStaleBadge imageVer={imageVer} minImageVer={minImageVer} hostname={hostname} onReinstall={onReinstall} />}
    </span>
  );
}

function ImageStaleBadge({
  imageVer,
  minImageVer,
  hostname,
  onReinstall,
}: {
  imageVer?: string | null;
  minImageVer?: string;
  hostname?: string;
  onReinstall: () => void;
}) {
  const reported = imageVer ?? 'pre-LIB.0';
  // WU.2: surface the two-liner refresh command directly in the tooltip
  // so the user doesn't have to find the Connect Worker modal first.
  // Hostname defaults to a visible placeholder so the user sees where
  // their container name goes even when we haven't got it on file.
  const containerName = hostname || '<your-worker-container>';
  return (
    <button
      type="button"
      onClick={onReinstall}
      title={
        `Worker image out of date ` +
        `(IMAGE_VERSION=${reported}, server requires ${minImageVer}). ` +
        `Source-code auto-updates are disabled until the image is refreshed.\n\n` +
        `Refresh in-place (same token, same slots):\n` +
        `  docker pull ghcr.io/weirded/esphome-dist-client:latest\n` +
        `  docker restart ${containerName}\n\n` +
        `Full re-install (new token / changed host platform / stepping past MIN_IMAGE_VERSION): ` +
        `click this badge to open Connect Worker and copy a fresh snippet.\n\n` +
        `Details: DOCS → Keeping workers up to date.`
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

export function WorkersTab({ workers, queue, serverClientVersion, minImageVersion, onRemove, onSetParallelJobs, onCleanCache, onCleanAllCaches, onConnectWorker, onViewLogs, onRequestDiagnostics }: Props) {
  // WL.3: lift the actions-dropdown open state out of the TanStack row
  // cell so the 1 Hz SWR poll doesn't tear it down mid-click (bug #2
  // / #71 class — see Design Judgment in CLAUDE.md). Keyed by
  // client_id so only one dropdown is open at a time.
  const [actionsMenuOpenClientId, setActionsMenuOpenClientId] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  // QS.27: persist sort across reloads via localStorage.
  const [sorting, setSorting] = usePersistedState<SortingState>(
    'workers-sort',
    [{ id: 'hostname', desc: false }],
  );


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

  // UX.2: wrap every sortable column header in SortHeader so the sort
  // glyph renders consistently with Devices/Queue/Schedules (QS.21).
  const columns = useMemo(() => [
    columnHelper.accessor(w => getWorkerSortValue(w, 'hostname'), {
      id: 'hostname',
      header: ({ column }) => <SortHeader label="Hostname" column={column} />,
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(w => getWorkerSortValue(w, 'status'), {
      id: 'status',
      header: ({ column }) => <SortHeader label="Status" column={column} />,
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(w => getWorkerSortValue(w, 'version'), {
      id: 'version',
      header: ({ column }) => <SortHeader label="Version" column={column} />,
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

      // UX.6: render the slot on a separate muted line rather than
      // gluing `/N` to the hostname (which reads as "version N"). The
      // tooltip spells out what the slot number means.
      const slotNameEl = slots > 1
        ? (
          <>
            {c.hostname}
            <br />
            <span
              className="text-[10px] text-[var(--text-muted)]"
              title={`Build slot ${slot} of ${slots} on this worker.`}
            >
              slot {slot}
            </span>
          </>
        )
        : <>{c.hostname}</>;

      // UX.3: render the same state badge on the Workers Current Job
      // cell as the one used on the Queue tab, so a state label looks
      // identical regardless of where it appears.
      const jobEl = slots === 0
        ? <span className="text-[12px] italic text-[var(--text-muted)]">Paused</span>
        : slotJob
          ? (() => {
              const { label, cls } = getJobBadge(slotJob);
              return (
                <div className="flex flex-col gap-0.5">
                  <code className="text-[12px]">{stripYaml(slotJob.target)}</code>
                  <span className={cls}>{label}</span>
                </div>
              );
            })()
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
            <td><ClientVersionCell ver={c.client_version} scv={serverClientVersion} imageVer={c.image_version} minImageVer={minImageVersion} hostname={c.hostname} onReinstall={() => onConnectWorker({
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
              <DropdownMenu
                open={actionsMenuOpenClientId === c.client_id}
                onOpenChange={(open) => setActionsMenuOpenClientId(open ? c.client_id : null)}
              >
                <DropdownMenuTrigger
                  className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2.5 h-7 text-[0.8rem] font-medium text-foreground hover:bg-muted cursor-pointer"
                  aria-label={`Actions for ${c.hostname}`}
                  title="Actions"
                >
                  Actions ▾
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuGroup>
                    <DropdownMenuItem onClick={() => onViewLogs(c.client_id)}>
                      View logs
                    </DropdownMenuItem>
                    {c.online && (
                      <DropdownMenuItem onClick={() => onRequestDiagnostics(c.client_id)}>
                        Request diagnostics
                      </DropdownMenuItem>
                    )}
                    {c.online && (
                      <DropdownMenuItem onClick={() => onCleanCache(c.client_id)}>
                        Clean cache
                      </DropdownMenuItem>
                    )}
                    {!c.online && !isLocal && (
                      <DropdownMenuItem
                        onClick={() => onRemove(c.client_id)}
                        className="text-[var(--danger,#ef4444)]"
                      >
                        Remove
                      </DropdownMenuItem>
                    )}
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
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
    // UX.2: click + sort indicators now come from the SortHeader child
    // button (mirroring Devices/Queue/Schedules); the <th> only carries
    // the aria-sort state. Old cell-wide onClick + inline arrow removed.
    const canSort = h.column.getCanSort();
    return (
      <th key={id} aria-sort={canSort ? getAriaSort(h.column) : undefined}>
        {flexRender(h.column.columnDef.header, h.getContext())}
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
                  <DropdownMenuItem
                    onClick={onCleanAllCaches}
                    disabled={!workers.some(w => w.online)}
                    title={!workers.some(w => w.online) ? 'No workers are online' : undefined}
                  >
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
