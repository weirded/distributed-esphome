import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
  type VisibilityState,
  type RowSelectionState,
} from '@tanstack/react-table';
import { getApiKey, restartDevice } from '../api/client';
import type { Device, Target, Worker } from '../types';
import { stripYaml, timeAgo } from '../utils';
import { StatusDot } from './StatusDot';
import { Button } from './ui/button';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuCheckboxItem,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from './ui/dropdown-menu';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from './ui/dialog';

/* ---- Column configuration ---- */
type OptionalColumnId = 'status' | 'ha' | 'ip' | 'running' | 'area' | 'comment' | 'project';

interface OptionalColumnDef {
  id: OptionalColumnId;
  label: string;
  defaultVisible: boolean;
}

const OPTIONAL_COLUMNS: OptionalColumnDef[] = [
  { id: 'status', label: 'Status', defaultVisible: true },
  { id: 'ha', label: 'HA', defaultVisible: true },
  { id: 'ip', label: 'IP', defaultVisible: true },
  { id: 'running', label: 'Version', defaultVisible: true },
  { id: 'area', label: 'Area', defaultVisible: false },
  { id: 'comment', label: 'Comment', defaultVisible: false },
  { id: 'project', label: 'Project', defaultVisible: false },
];

const STORAGE_KEY = 'device-columns';

function loadColumnVisibility(): VisibilityState {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const visible = new Set<string>(JSON.parse(stored) as string[]);
      return Object.fromEntries(OPTIONAL_COLUMNS.map(c => [c.id, visible.has(c.id)]));
    }
  } catch { /* ignore */ }
  return Object.fromEntries(OPTIONAL_COLUMNS.map(c => [c.id, c.defaultVisible]));
}

function saveColumnVisibility(state: VisibilityState) {
  const visible = OPTIONAL_COLUMNS.filter(c => state[c.id] !== false).map(c => c.id);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(visible));
}

interface Props {
  targets: Target[];
  devices: Device[];
  workers: Worker[];
  onCompile: (targets: string[] | 'all' | 'outdated') => void;
  onCompileOnWorker: (target: string, clientId: string) => void;
  onEdit: (target: string) => void;
  onLogs: (target: string) => void;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
  onDelete: (target: string, archive: boolean) => void;
  onRename: (oldTarget: string, newName: string) => void;
}

function matchesFilter(filter: string, ...fields: (string | null | undefined)[]): boolean {
  if (!filter) return true;
  const q = filter.toLowerCase();
  return fields.some(f => f?.toLowerCase().includes(q));
}

export function RenameModal({ currentName, onConfirm, onClose }: {
  currentName: string;
  onConfirm: (newName: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(stripYaml(currentName));
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.select(); }, []);

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent >
        <DialogHeader>
          <DialogTitle>Rename Device</DialogTitle>
        </DialogHeader>
        <div style={{ padding: '16px' }}>
          <label style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6, display: 'block' }}>
            New device name
          </label>
          <input
            ref={inputRef}
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && name.trim() && name.trim() !== stripYaml(currentName) && onConfirm(name.trim())}
            style={{ width: '100%', padding: '8px 12px', background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', color: 'var(--text)', fontSize: 14 }}
          />
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>
            This will update the config file, rename it, and compile + upgrade the device with the new name via OTA.
          </p>
        </div>
        <DialogFooter>
          <Button variant="secondary" size="sm" onClick={onClose}>Cancel</Button>
          <Button
            size="sm"
            disabled={!name.trim() || name.trim() === stripYaml(currentName)}
            onClick={() => onConfirm(name.trim())}
          >
            Rename &amp; Upgrade
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DeleteModal({ target, onConfirm, onClose }: {
  target: string;
  onConfirm: (archive: boolean) => void;
  onClose: () => void;
}) {
  const [confirmPermanent, setConfirmPermanent] = useState(false);

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent >
        <DialogHeader>
          <DialogTitle>Delete Device</DialogTitle>
        </DialogHeader>
        <div style={{ padding: '16px' }}>
          {!confirmPermanent ? (
            <>
              <p>Are you sure you want to delete <strong>{stripYaml(target)}</strong>?</p>
            </>
          ) : (
            <p style={{ color: 'var(--danger)' }}>
              This will <strong>permanently delete</strong> {stripYaml(target)}. This cannot be undone.
            </p>
          )}
        </div>
        <DialogFooter>
          {!confirmPermanent ? (
            <>
              <Button variant="secondary" size="sm" onClick={onClose}>Cancel</Button>
              <Button variant="warn" size="sm" onClick={() => onConfirm(true)}>Archive</Button>
              <Button variant="destructive" size="sm" onClick={() => setConfirmPermanent(true)}>Delete Permanently</Button>
            </>
          ) : (
            <>
              <Button variant="secondary" size="sm" onClick={() => setConfirmPermanent(false)}>Back</Button>
              <Button variant="destructive" size="sm" onClick={() => onConfirm(false)}>Yes, Delete Forever</Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function DevicesTab({ targets, devices, workers, onCompile, onCompileOnWorker, onEdit, onLogs, onToast, onDelete, onRename }: Props) {
  const [filter, setFilter] = useState('');
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(loadColumnVisibility);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [menuTarget, setMenuTarget] = useState<Target | null>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null);
  const [renameTarget, setRenameTarget] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  // Persist column visibility to localStorage whenever it changes
  useEffect(() => {
    saveColumnVisibility(columnVisibility);
  }, [columnVisibility]);

  // Build a set of device names that are already shown as managed targets
  // to prevent duplicates when compile_target mapping has a race condition
  const managedDeviceNames = useMemo(() => {
    const s = new Set<string>();
    for (const t of targets) {
      if (t.device_name) s.add(t.device_name.toLowerCase().replace(/ /g, '-').replace(/ /g, '_'));
      s.add(stripYaml(t.target).toLowerCase());
    }
    return s;
  }, [targets]);

  const managedIPs = useMemo(() =>
    new Set(targets.map(t => t.ip_address).filter(Boolean) as string[]),
    [targets]
  );

  const unmanaged = useMemo(() =>
    [...devices]
      .filter(d =>
        !d.compile_target &&
        !managedDeviceNames.has(d.name.toLowerCase()) &&
        !(d.ip_address && managedIPs.has(d.ip_address))
      )
      .sort((a, b) => a.name.localeCompare(b.name)),
    [devices, managedDeviceNames, managedIPs]
  );

  // Filter targets before passing to TanStack (filter state owned here, not in TanStack)
  const filteredTargets = useMemo(() => {
    const sorted = [...targets].sort((a, b) => a.target.localeCompare(b.target));
    if (!filter) return sorted;
    return sorted.filter(t =>
      matchesFilter(
        filter,
        t.friendly_name,
        t.device_name,
        stripYaml(t.target),
        t.target,
        t.online == null ? 'unknown' : t.online ? 'online' : 'offline',
        t.ip_address,
        t.running_version,
        t.area,
        t.comment,
        t.project_name,
      )
    );
  }, [targets, filter]);

  const filteredUnmanaged = useMemo(() => {
    if (!filter) return unmanaged;
    return unmanaged.filter(d =>
      matchesFilter(
        filter,
        d.name,
        stripYaml(d.name),
        d.online ? 'online' : 'offline',
        d.ip_address,
        d.running_version,
      )
    );
  }, [unmanaged, filter]);

  const columnHelper = createColumnHelper<Target>();

  const columns = useMemo(() => [
    columnHelper.display({
      id: 'select',
      enableHiding: false,
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
          className="target-cb"
          value={row.original.target}
          checked={row.getIsSelected()}
          onChange={row.getToggleSelectedHandler()}
        />
      ),
    }),
    columnHelper.accessor(
      row => row.friendly_name || row.device_name || stripYaml(row.target),
      {
        id: 'device',
        enableHiding: false,
        header: ({ column }) => (
          <SortHeader label="Device" column={column} />
        ),
        cell: ({ row: { original: t } }) => (
          <>
            <span className="device-name">{t.friendly_name || t.device_name || stripYaml(t.target)}</span>
            <div className="device-filename">{stripYaml(t.target)}</div>
          </>
        ),
        sortingFn: 'alphanumeric',
      }
    ),
    columnHelper.accessor(
      row => row.online == null ? 'unknown' : row.online ? 'online' : 'offline',
      {
        id: 'status',
        header: ({ column }) => <SortHeader label="Status" column={column} />,
        cell: ({ row: { original: t } }) => {
          const lastSeenEl = t.last_seen
            ? <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{timeAgo(t.last_seen)}</div>
            : null;
          if (t.online == null) return <StatusDot status="checking" />;
          if (t.online) return <><StatusDot status="online" />{lastSeenEl}</>;
          return <><StatusDot status="offline" />{lastSeenEl}</>;
        },
        sortingFn: 'alphanumeric',
      }
    ),
    columnHelper.accessor(
      row => row.ha_configured ? 'yes' : '',
      {
        id: 'ha',
        header: ({ column }) => <SortHeader label="HA" column={column} />,
        cell: ({ row: { original: t } }) => (
          <span style={{ fontSize: 12 }}>
            {t.ha_configured
              ? <span style={{ color: 'var(--success)' }}>Yes</span>
              : <span style={{ color: 'var(--text-muted)' }}>—</span>}
          </span>
        ),
        sortingFn: 'alphanumeric',
      }
    ),
    columnHelper.accessor(row => row.ip_address || '', {
      id: 'ip',
      header: ({ column }) => <SortHeader label="IP" column={column} />,
      cell: ({ row: { original: t } }) => {
        const showIpLink = t.has_web_server && t.online && t.ip_address;
        return (
          <span style={{ fontFamily: 'monospace', fontSize: 12 }} className="sensitive">
            {showIpLink
              ? (
                <a
                  href={`http://${t.ip_address}`}
                  target="_blank"
                  rel="noopener"
                  className="ip-link"
                >
                  {t.ip_address}<span style={{ fontSize: 10 }}>&#8599;</span>
                </a>
              )
              : <span style={{ color: 'var(--text-muted)' }}>{t.ip_address || '—'}</span>}
          </span>
        );
      },
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(row => row.running_version || '', {
      id: 'running',
      header: ({ column }) => <SortHeader label="Version" column={column} />,
      cell: ({ row: { original: t } }) => (
        <span style={{ fontSize: 12 }}>
          {t.running_version || '—'}
          {t.config_modified && <div className="config-modified">config changed</div>}
        </span>
      ),
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(row => row.area || '', {
      id: 'area',
      header: ({ column }) => <SortHeader label="Area" column={column} />,
      cell: ({ row: { original: t } }) => (
        <span style={{ fontSize: 12 }}>
          {t.area || <span style={{ color: 'var(--text-muted)' }}>—</span>}
        </span>
      ),
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(row => row.comment || '', {
      id: 'comment',
      header: ({ column }) => <SortHeader label="Comment" column={column} />,
      cell: ({ row: { original: t } }) => (
        <span style={{ fontSize: 12, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>
          {t.comment || <span style={{ color: 'var(--text-muted)' }}>—</span>}
        </span>
      ),
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(
      row => row.project_name ? (row.project_version ? `${row.project_name} ${row.project_version}` : row.project_name) : '',
      {
        id: 'project',
        header: ({ column }) => <SortHeader label="Project" column={column} />,
        cell: ({ row: { original: t } }) => {
          const projectStr = t.project_name
            ? (t.project_version ? `${t.project_name} ${t.project_version}` : t.project_name)
            : '—';
          return (
            <span style={{ fontSize: 12 }}>
              {projectStr === '—' ? <span style={{ color: 'var(--text-muted)' }}>—</span> : projectStr}
            </span>
          );
        },
        sortingFn: 'alphanumeric',
      }
    ),
    columnHelper.display({
      id: 'actions',
      enableHiding: false,
      cell: ({ row: { original: t } }) => {
        const upgradeVariant = t.needs_update ? 'success' : 'secondary';
        return (
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <Button variant={upgradeVariant as 'success' | 'secondary'} size="sm" onClick={() => onCompile([t.target])}>Upgrade</Button>
            <Button variant="secondary" size="sm" onClick={() => onEdit(t.target)}>Edit</Button>
            <span
              className="action-menu-trigger"
              title="More actions"
              onClick={(e) => {
                if (menuTarget?.target === t.target) { setMenuTarget(null); setMenuPos(null); return; }
                const rect = e.currentTarget.getBoundingClientRect();
                setMenuPos({ top: rect.bottom + 4, left: rect.right });
                setMenuTarget(t);
              }}
            >&#8942;</span>
          </div>
        );
      },
    }),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [workers, onCompile, onCompileOnWorker, onEdit, onLogs, onToast]);

  const table = useReactTable({
    data: filteredTargets,
    columns,
    state: {
      sorting,
      columnVisibility,
      rowSelection,
    },
    onSortingChange: setSorting,
    onColumnVisibilityChange: (updater) => {
      setColumnVisibility(prev => {
        const next = typeof updater === 'function' ? updater(prev) : updater;
        saveColumnVisibility(next);
        return next;
      });
    },
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: row => row.target,
  });

  const selectedTargets = table.getSelectedRowModel().rows.map(r => r.original.target);

  function handleCompileSelected() {
    if (selectedTargets.length === 0) return;
    onCompile(selectedTargets);
  }

  // Column visibility for unmanaged rows — derive from TanStack state
  const isVisible = useCallback((col: OptionalColumnId) => columnVisibility[col] !== false, [columnVisibility]);

  // Count visible optional columns to compute colspan for empty row
  const visibleOptionalCount = OPTIONAL_COLUMNS.filter(c => isVisible(c.id)).length;
  // Total cols: select + device + optional + actions = 3 + visibleOptionalCount
  const totalColSpan = 3 + visibleOptionalCount;

  const hasResults = filteredTargets.length > 0 || filteredUnmanaged.length > 0;

  return (
    <div className="block" id="tab-devices">
      <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-sm">
        <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] bg-[var(--surface2)] px-4 py-3">
          <h2 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--text-muted)] mr-1">Devices</h2>
          <div className="relative max-w-[280px]">
            <input
              type="text"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="Search devices..."
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface2)] px-2.5 py-1 pr-7 text-[13px] text-[var(--text)] outline-none placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]"
            />
            {filter && (
              <button
                onClick={() => setFilter('')}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 border-none bg-transparent text-sm leading-none text-[var(--text-muted)] cursor-pointer px-0.5"
                title="Clear filter"
              >
                &times;
              </button>
            )}
          </div>
          <div className="actions">
            {/* Upgrade dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger className="inline-flex items-center gap-1 rounded-lg bg-[var(--accent)] px-2.5 py-1 text-xs font-medium text-white hover:bg-[var(--accent-hover)] cursor-pointer">
                Upgrade &#9662;
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-[180px]">
                <DropdownMenuGroup>
                  <DropdownMenuItem onClick={() => {
                    const all = targets.map(t => t.target);
                    if (all.length > 0) onCompile(all);
                  }}>
                    Upgrade All
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => {
                    const onlineTargets = targets.filter(t => t.online !== false).map(t => t.target);
                    if (onlineTargets.length > 0) onCompile(onlineTargets);
                  }}>
                    Upgrade All Online
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => onCompile('outdated')}
                    disabled={!targets.some(t => t.needs_update)}
                  >
                    Upgrade Outdated
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={handleCompileSelected}>
                    Upgrade Selected
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Column picker (gear icon) */}
            <DropdownMenu>
              <DropdownMenuTrigger className="inline-flex items-center rounded-lg border border-[var(--border)] bg-[var(--surface2)] px-2 py-1 text-base text-[var(--text)] hover:bg-[var(--border)] cursor-pointer" title="Toggle columns">
                &#9881;
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                  <DropdownMenuLabel>Columns</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {OPTIONAL_COLUMNS.map(col => (
                    <DropdownMenuCheckboxItem
                      key={col.id}
                      checked={isVisible(col.id)}
                      onCheckedChange={() => table.getColumn(col.id)?.toggleVisibility()}
                    >
                      {col.label}
                    </DropdownMenuCheckboxItem>
                  ))}
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
              {!hasResults ? (
                <tr className="empty-row">
                  <td colSpan={totalColSpan}>
                    {filter
                      ? 'No devices match your search'
                      : 'No devices found — ensure ESPHome configs are in /config/esphome/'}
                  </td>
                </tr>
              ) : (
                <>
                  {table.getRowModel().rows.map(row => (
                    <tr key={row.id}>
                      {row.getVisibleCells().map(cell => (
                        <td key={cell.id}>
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  ))}
                  {filteredUnmanaged.map(d => (
                    <UnmanagedRow key={d.name} device={d} isVisible={isVisible} />
                  ))}
                </>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {renameTarget && (
        <RenameModal
          currentName={renameTarget}
          onConfirm={newName => {
            const target = renameTarget;
            setRenameTarget(null);
            onRename(target, newName);
          }}
          onClose={() => setRenameTarget(null)}
        />
      )}

      {deleteTarget && (
        <DeleteModal
          target={deleteTarget}
          onConfirm={archive => {
            const target = deleteTarget;
            setDeleteTarget(null);
            onDelete(target, archive);
          }}
          onClose={() => setDeleteTarget(null)}
        />
      )}

      {menuTarget && menuPos && (
        <DeviceMenu
          target={menuTarget}
          workers={workers}
          position={menuPos}
          onToast={onToast}
          onDelete={(t) => { setMenuTarget(null); setMenuPos(null); setDeleteTarget(t); }}
          onRename={(t) => { setMenuTarget(null); setMenuPos(null); setRenameTarget(t); }}
          onLogs={(t) => { setMenuTarget(null); setMenuPos(null); onLogs(t); }}
          onCompileOnWorker={(t, w) => { setMenuTarget(null); setMenuPos(null); onCompileOnWorker(t, w); }}
          onClose={() => { setMenuTarget(null); setMenuPos(null); }}
        />
      )}
    </div>
  );
}

// Inline sort header used in column defs — renders ▲/▼ indicators
function SortHeader({ label, column }: { label: string; column: { getIsSorted: () => false | 'asc' | 'desc'; toggleSorting: (desc?: boolean) => void; getCanSort: () => boolean } }) {
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

function DeviceMenu({
  target: t,
  workers,
  position,
  onToast,
  onDelete,
  onRename,
  onLogs,
  onCompileOnWorker,
  onClose,
}: {
  target: Target;
  workers: Worker[];
  position: { top: number; left: number };
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
  onDelete: (target: string) => void;
  onRename: (target: string) => void;
  onLogs: (target: string) => void;
  onCompileOnWorker: (target: string, clientId: string) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  async function handleCopyApiKey() {
    try {
      const key = await getApiKey(t.target);
      await navigator.clipboard.writeText(key);
      onToast('API key copied!', 'success');
    } catch {
      onToast('No API key found', 'info');
    }
  }

  async function handleRestart() {
    try {
      await restartDevice(t.target);
      onToast(`Restarting ${stripYaml(t.target)}...`, 'success');
    } catch (err) {
      onToast('Restart failed: ' + (err as Error).message, 'error');
    }
  }

  const onlineWorkers = [...workers]
    .filter(w => w.online && !w.disabled && (w.max_parallel_jobs ?? 0) > 0)
    .sort((a, b) => a.hostname.localeCompare(b.hostname, undefined, { sensitivity: 'base' }));

  return (
    <>
      {/* Backdrop to close on outside click */}
      <div className="fixed inset-0 z-50" onClick={onClose} />
      <div
        className="fixed z-50 min-w-[160px] rounded-lg border border-[var(--border)] bg-[var(--popover)] p-1 text-[var(--popover-foreground)] shadow-md ring-1 ring-[var(--foreground)]/10"
        style={{ top: position.top, left: position.left, transform: 'translateX(-100%)' }}
      >
        <div className="px-1.5 py-1 text-xs font-medium text-[var(--text-muted)]">Device</div>
        <button className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-sm cursor-pointer hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]" onClick={() => onLogs(t.target)}>Live Logs</button>
        <button className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-sm cursor-pointer hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]" onClick={handleRestart}>Restart</button>
        <button className={`flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-sm ${t.has_api_key ? 'cursor-pointer hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]' : 'opacity-50 pointer-events-none'}`} onClick={handleCopyApiKey}>Copy API Key</button>

        <div className="-mx-1 my-1 h-px bg-[var(--border)]" />

        <div className="px-1.5 py-1 text-xs font-medium text-[var(--text-muted)]">Config</div>
        <button className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-sm cursor-pointer hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]" onClick={() => onRename(t.target)}>Rename</button>
        <button className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-sm cursor-pointer text-[var(--destructive)] hover:bg-[var(--destructive)]/10" onClick={() => onDelete(t.target)}>Delete</button>

        {onlineWorkers.length > 0 && (
          <>
            <div className="-mx-1 my-1 h-px bg-[var(--border)]" />
            <div className="group/sub relative">
              <div className="flex w-full items-center justify-between rounded-md px-1.5 py-1 text-sm cursor-default hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]">
                Upgrade on...
                <span className="ml-auto text-xs">&#9666;</span>
              </div>
              <div className="invisible group-hover/sub:visible absolute right-full top-0 mr-1 min-w-[140px] rounded-lg border border-[var(--border)] bg-[var(--popover)] p-1 text-[var(--popover-foreground)] shadow-md ring-1 ring-[var(--foreground)]/10">
                {onlineWorkers.map(w => (
                  <button key={w.client_id} className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-sm cursor-pointer hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]" onClick={() => onCompileOnWorker(t.target, w.client_id)}>{w.hostname}</button>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}

function UnmanagedRow({ device: d, isVisible }: { device: Device; isVisible: (col: OptionalColumnId) => boolean }) {
  const statusEl = d.online
    ? <StatusDot status="online" />
    : <StatusDot status="offline" />;

  const dash = <span style={{ color: 'var(--text-muted)' }}>—</span>;

  // Unmanaged devices (no config) don't have web_server info — never link their IP
  return (
    <tr>
      <td></td>
      <td>
        <span className="device-name" style={{ color: 'var(--text-muted)' }}>{stripYaml(d.name)}</span>
        <div className="device-filename" style={{ color: '#6b7280' }}>No config</div>
      </td>
      {isVisible('status') && <td>{statusEl}</td>}
      {isVisible('ha') && <td style={{ fontSize: 12 }}>{dash}</td>}
      {isVisible('ip') && (
        <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
          <span style={{ color: 'var(--text-muted)' }}>{d.ip_address || '—'}</span>
        </td>
      )}
      {isVisible('running') && <td style={{ fontSize: 12 }}>{d.running_version || '—'}</td>}
      {isVisible('area') && <td style={{ fontSize: 12 }}>{dash}</td>}
      {isVisible('comment') && <td style={{ fontSize: 12 }}>{dash}</td>}
      {isVisible('project') && <td style={{ fontSize: 12 }}>{dash}</td>}
      <td></td>
    </tr>
  );
}
