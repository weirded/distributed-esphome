import { useCallback, useEffect, useMemo, useState } from 'react';
import useSWR from 'swr';
import { Settings2 } from 'lucide-react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type SortingState,
  type VisibilityState,
  type RowSelectionState,
} from '@tanstack/react-table';
import {
  getArchivedConfigs,
  pinTargetVersion,
  unpinTargetVersion,
  type ArchivedConfig,
} from '../api/client';
import type { AddressSource, Device, Job, Target, Worker } from '../types';
import { stripYaml, haDeepLink, usePersistedState } from '../utils';
import { StatusDot } from './StatusDot';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { ArchivedDevicesList } from './ArchivedDevicesList';
import { getAriaSort } from './ui/sort-header';
import { DeleteModal, RenameModal } from './devices/DeviceTableModals';
import { useDeviceColumns } from './devices/useDeviceColumns';
import { DeviceTableActions } from './devices/DeviceTableActions';
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

/* ---- Column configuration ---- */
type OptionalColumnId = 'status' | 'ha' | 'ip' | 'mac' | 'running' | 'area' | 'comment' | 'tags' | 'project' | 'net' | 'ipconfig' | 'ap' | 'schedule' | 'last_compiled';

interface OptionalColumnDef {
  id: OptionalColumnId;
  label: string;
  defaultVisible: boolean;
}

// #69: entries are ordered to match the actual column render order in
// ``useDeviceColumns.tsx``. The picker renders checkboxes in this
// order, so keeping them aligned means toggling a column on/off
// matches the user's left-to-right reading of the table itself.
const OPTIONAL_COLUMNS: OptionalColumnDef[] = [
  { id: 'status', label: 'Status', defaultVisible: true },
  { id: 'ha', label: 'HA', defaultVisible: true },
  { id: 'ip', label: 'IP', defaultVisible: true },
  // Bug #12 (1.6.1): MAC column. Off by default — most users don't
  // need it, but it's useful when matching devices to ARP / DHCP
  // reservations or to HA's device registry entries.
  { id: 'mac', label: 'MAC', defaultVisible: false },
  { id: 'net', label: 'Net', defaultVisible: true },
  { id: 'ipconfig', label: 'IP Config', defaultVisible: false },
  { id: 'ap', label: 'AP', defaultVisible: false },
  { id: 'schedule', label: 'Schedule', defaultVisible: true },
  // JH.6: opt-in "Last compiled" column. Off by default so existing users
  // see no layout churn; power users toggle it on to spot stale devices.
  { id: 'last_compiled', label: 'Last compiled', defaultVisible: false },
  { id: 'running', label: 'ESPHome', defaultVisible: true },
  { id: 'area', label: 'Area', defaultVisible: false },
  { id: 'comment', label: 'Comment', defaultVisible: false },
  // TG.5: read-only chip-pill tag column. Default ON so a user adding
  // tags via YAML (or via TG.4's API) sees them without hunting through
  // the column-visibility menu first.
  { id: 'tags', label: 'Tags', defaultVisible: true },
  { id: 'project', label: 'Project', defaultVisible: false },
];

const STORAGE_KEY = 'device-columns';

/**
 * Bug #7 (1.6.1): columns added after a user's first save would get
 * stuck OFF because the old loader inferred visibility from presence in
 * a flat "visible ids" list — an absent id always meant off, even for a
 * brand-new column whose default is on. Record the full "known"
 * snapshot alongside the visible set so loadColumnVisibility can tell
 * "explicitly hidden by the user" apart from "didn't exist yet when
 * they saved". Legacy flat-array saves still load (treated as known =
 * that same list); new columns fall through to their ``defaultVisible``.
 */
interface StoredColumnVisibility {
  known: string[];
  visible: string[];
}

function loadColumnVisibility(): VisibilityState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      let known: Set<string>;
      let visible: Set<string>;
      if (Array.isArray(parsed)) {
        // Legacy flat-list format: what was saved is what they knew.
        known = new Set<string>(parsed as string[]);
        visible = known;
      } else if (parsed && typeof parsed === 'object' && Array.isArray((parsed as StoredColumnVisibility).known)) {
        known = new Set<string>((parsed as StoredColumnVisibility).known);
        visible = new Set<string>((parsed as StoredColumnVisibility).visible ?? []);
      } else {
        throw new Error('unrecognised stored shape');
      }
      return Object.fromEntries(OPTIONAL_COLUMNS.map(c =>
        [c.id, known.has(c.id) ? visible.has(c.id) : c.defaultVisible],
      ));
    }
  } catch { /* ignore */ }
  return Object.fromEntries(OPTIONAL_COLUMNS.map(c => [c.id, c.defaultVisible]));
}

function saveColumnVisibility(state: VisibilityState) {
  const stored: StoredColumnVisibility = {
    known: OPTIONAL_COLUMNS.map(c => c.id),
    visible: OPTIONAL_COLUMNS.filter(c => state[c.id] !== false).map(c => c.id),
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
}

interface Props {
  targets: Target[];
  devices: Device[];
  workers: Worker[];
  streamerMode: boolean;
  /**
   * Map of target filename → currently active (PENDING/WORKING) job for that
   * target, derived in App.tsx from the live queue. Used to render an
   * "Upgrading…" status and disable the Upgrade button while a compile is
   * in flight (#32).
   */
  activeJobsByTarget: Map<string, Job>;
  onCompile: (targets: string[] | 'all' | 'outdated') => void;
  /**
   * Per-row click handler for the Upgrade button (#16). Opens the
   * UpgradeModal which collects worker + ESPHome version preferences. The
   * onCompile prop is still used for the bulk Upgrade dropdown actions
   * (Upgrade All, Upgrade Outdated, etc.) — those don't go through the modal.
   */
  onUpgradeOne: (target: string) => void;
  onEdit: (target: string) => void;
  onLogs: (target: string) => void;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
  onDelete: (target: string, archive: boolean) => void;
  onRename: (oldTarget: string, newName: string) => void;
  onSchedule: (target: string) => void;
  /** CD.5: open the NewDeviceModal in "new" mode (called from toolbar button). */
  onNewDevice: () => void;
  /** CD.6: open the NewDeviceModal in "duplicate" mode, pre-filling the source. */
  onDuplicate: (sourceTarget: string) => void;
  /** AV.6: open the per-file History panel from the row hamburger menu. */
  onOpenHistory: (target: string) => void;
  /** JH.5: open the per-device Compile History panel. */
  onOpenCompileHistory: (target: string) => void;
  /** Bug #16: open the manual-commit dialog for a target. */
  onCommitChanges: (target: string) => void;
  /** Trigger an immediate SWR revalidation of the devices/targets data. */
  onRefresh: () => void;
}

function matchesFilter(filter: string, ...fields: (string | null | undefined)[]): boolean {
  if (!filter) return true;
  const q = filter.toLowerCase();
  return fields.some(f => f?.toLowerCase().includes(q));
}

/**
 * Render a short label describing how the device's IP was resolved.
 * Returns null when there's nothing useful to display (no source, or
 * the address is just the {name}.local fallback no one configured).
 */
/**
 * Render a short display label for the device's primary network type (#10).
 * Returns null when the YAML didn't declare any of wifi/ethernet/openthread —
 * the column shows a dash in that case.
 */
function formatAddressSource(source: AddressSource | null | undefined): string | null {
  switch (source) {
    case 'mdns': return 'via mDNS';
    case 'wifi_use_address': return 'wifi.use_address';
    case 'ethernet_use_address': return 'ethernet.use_address';
    case 'openthread_use_address': return 'openthread.use_address';
    case 'wifi_static_ip': return 'wifi static_ip';
    case 'ethernet_static_ip': return 'ethernet static_ip';
    case 'mdns_default': return null;
    case 'arp': return 'via ARP';
    default: return null;
  }
}

// QS.19: RenameModal + DeleteModal live in ./devices/DeviceTableModals.
// RenameModal is re-exported so App.tsx's existing import path still works.
export { RenameModal };

export function DevicesTab({ targets, devices, workers, streamerMode, activeJobsByTarget, onCompile, onUpgradeOne, onEdit, onLogs, onToast, onDelete, onRename, onSchedule, onNewDevice, onDuplicate, onOpenHistory, onOpenCompileHistory, onCommitChanges, onRefresh }: Props) {
  const [filter, setFilter] = useState('');
  // QS.27: persist sort across reloads via localStorage.
  const [sorting, setSorting] = usePersistedState<SortingState>('devices-sort', []);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(loadColumnVisibility);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [renameTarget, setRenameTarget] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  // #2: hamburger open state lives here so it survives row remounts
  // triggered by SWR polls. See useDeviceColumns / DeviceContextMenu.
  const [menuOpenTarget, setMenuOpenTarget] = useState<string | null>(null);
  const [showUnmanaged, setShowUnmanaged] = useState(() => localStorage.getItem('showUnmanaged') !== 'false');
  // #62: Devices-toolbar Archive button → shadcn Dialog wrapping the
  // shared ArchivedDevicesList component. State lives here rather
  // than in App.tsx because the button's local to this tab.
  const [archiveOpen, setArchiveOpen] = useState(false);
  // #70: "Duplicate existing device" picker state. Opened from the
  // "Add device ▾" dropdown. Shows a list of existing targets the
  // user can pick to duplicate; selection calls onDuplicate() which
  // routes back to the NewDeviceModal in duplicate mode.
  const [duplicatePickerOpen, setDuplicatePickerOpen] = useState(false);
  // #73: watch archive count so we can (a) gray out the "Restore from
  // archive" menu item when the archive is empty and (b) auto-close
  // the archive dialog once the user restores or permanently-deletes
  // its last item. Both this hook and ArchivedDevicesList subscribe to
  // the same SWR key, so SWR dedupes the request and a mutate() from
  // the list re-renders both. revalidateOnFocus stays off to match
  // the list's config.
  const { data: archivedConfigs } = useSWR<ArchivedConfig[]>(
    'archived-configs',
    getArchivedConfigs,
    { revalidateOnFocus: false },
  );
  const archiveEmpty = !archivedConfigs || archivedConfigs.length === 0;
  useEffect(() => {
    if (archiveOpen && archiveEmpty) setArchiveOpen(false);
  }, [archiveOpen, archiveEmpty]);

  // VP.4 / QS.20: pin/unpin version from the hamburger menu. Memoized so
  // useDeviceColumns' dep array can actually cache — the hook re-runs only
  // when `targets`/`onToast` change, not every render.
  const handlePin = useCallback(async (target: string) => {
    // Pin to the device's current running version (from the poller), or the
    // global server version if the device hasn't reported a version yet.
    const t = targets.find(x => x.target === target);
    const version = t?.running_version || t?.server_version;
    if (!version) {
      onToast('No version available to pin to', 'error');
      return;
    }
    try {
      await pinTargetVersion(target, version);
      onToast(`Pinned ${stripYaml(target)} to ${version}`, 'success');
    } catch (err) {
      onToast('Pin failed: ' + (err as Error).message, 'error');
    }
  }, [targets, onToast]);

  const handleUnpin = useCallback(async (target: string) => {
    try {
      await unpinTargetVersion(target);
      onToast(`Unpinned ${stripYaml(target)}`, 'success');
    } catch (err) {
      onToast('Unpin failed: ' + (err as Error).message, 'error');
    }
  }, [onToast]);

  // Persist column visibility and unmanaged toggle to localStorage
  useEffect(() => {
    saveColumnVisibility(columnVisibility);
  }, [columnVisibility]);
  useEffect(() => {
    localStorage.setItem('showUnmanaged', String(showUnmanaged));
  }, [showUnmanaged]);

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
        // TG.5: tags participate in the existing search box (substring,
        // case-insensitive) before the dedicated filter pills land.
        t.tags,
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

  const columns = useDeviceColumns({
    activeJobsByTarget,
    streamerMode,
    onUpgradeOne,
    onEdit,
    onLogs,
    onToast,
    onSchedule,
    onDuplicate,
    onRequestRename: setRenameTarget,
    onRequestDelete: setDeleteTarget,
    onPin: handlePin,
    onUnpin: handleUnpin,
    onOpenHistory,
    onOpenCompileHistory,
    onCommitChanges,
    menuOpenTarget,
    setMenuOpenTarget,
  });


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
  // QS.18: bulk schedule state + handlers + modal now live in DeviceTableActions.

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
            {/* #70: "Add device ▾" dropdown consolidates the three ways
                a device lands in the fleet — blank-slate new, duplicate
                from an existing YAML, or restore from the soft-delete
                archive. Replaces the separate "+ New Device" + "Archive…"
                buttons. */}
            <DropdownMenu>
              <DropdownMenuTrigger className="inline-flex items-center gap-1 rounded-lg border border-transparent bg-primary px-2.5 h-7 text-[0.8rem] font-medium text-primary-foreground hover:bg-primary/80 cursor-pointer">
                Add device <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="min-w-[220px]">
                <DropdownMenuGroup>
                  <DropdownMenuItem onClick={onNewDevice}>
                    New device…
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => setDuplicatePickerOpen(true)}
                    disabled={targets.length === 0}
                    title={targets.length === 0 ? "No existing devices to duplicate" : undefined}
                  >
                    Duplicate existing device…
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() => setArchiveOpen(true)}
                    disabled={archiveEmpty}
                    title={archiveEmpty ? "Archive is empty — delete a device to populate it" : undefined}
                  >
                    Restore from archive…
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
            {/* Upgrade dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger className="inline-flex items-center gap-1 rounded-lg border border-transparent bg-primary px-2.5 h-7 text-[0.8rem] font-medium text-primary-foreground hover:bg-primary/80 cursor-pointer">
                Upgrade <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
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

            {/* #8 / QS.18: Actions dropdown — non-compile bulk operations. */}
            <DeviceTableActions
              selectedTargets={selectedTargets}
              workers={workers}
              targets={targets}
              onToast={onToast}
              onRefresh={onRefresh}
            />


            {/* Column picker (gear icon) */}
            <DropdownMenu>
              <DropdownMenuTrigger
                className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2.5 h-7 text-[0.8rem] font-medium text-foreground hover:bg-muted cursor-pointer"
                aria-label="Toggle columns"
                title="Toggle columns"
              >
                <Settings2 className="size-3.5" />
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
                  <DropdownMenuSeparator />
                  <DropdownMenuCheckboxItem
                    checked={showUnmanaged}
                    onCheckedChange={() => setShowUnmanaged(v => !v)}
                  >
                    Show unmanaged devices
                  </DropdownMenuCheckboxItem>
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
                  {showUnmanaged && filteredUnmanaged.map(d => (
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

      {/* QS.18: bulk schedule UpgradeModal moved into DeviceTableActions. */}

      {/* #62: Archive modal — toolbar "Archive…" button opens a Dialog
          that wraps the shared ArchivedDevicesList. Same list the
          Settings drawer renders; only the entry point differs. */}
      <Dialog open={archiveOpen} onOpenChange={setArchiveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Archived devices</DialogTitle>
          </DialogHeader>
          <div className="px-4 pb-4 pt-2">
            <ArchivedDevicesList />
          </div>
        </DialogContent>
      </Dialog>

      {/* #70: "Duplicate existing device" picker — list every current
          target as a clickable row; picking one forwards to
          onDuplicate() which is wired to the NewDeviceModal in
          duplicate mode in App.tsx. */}
      <Dialog open={duplicatePickerOpen} onOpenChange={setDuplicatePickerOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Pick a device to duplicate</DialogTitle>
          </DialogHeader>
          <div className="px-4 pb-4 pt-2 flex flex-col gap-2 max-h-[50vh] overflow-y-auto">
            {targets.length === 0 ? (
              <p className="text-xs text-[var(--text-muted)]">
                No existing devices to duplicate.
              </p>
            ) : (
              targets
                .slice()
                .sort((a, b) => (a.friendly_name || a.target).localeCompare(b.friendly_name || b.target))
                .map((t) => (
                  <button
                    key={t.target}
                    type="button"
                    className="flex items-center justify-between rounded-md border border-[var(--border)] bg-[var(--surface2)] px-3 py-2 text-left hover:border-[var(--accent)] cursor-pointer"
                    onClick={() => {
                      setDuplicatePickerOpen(false);
                      onDuplicate(t.target);
                    }}
                  >
                    <span className="flex-1 text-[13px] text-[var(--text)]">
                      {t.friendly_name || t.device_name || t.target}
                    </span>
                    <span className="ml-2 text-[11px] font-mono text-[var(--text-muted)]">
                      {t.target}
                    </span>
                  </button>
                ))
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}


function UnmanagedRow({ device: d, isVisible }: { device: Device; isVisible: (col: OptionalColumnId) => boolean }) {
  const statusEl = d.online
    ? <StatusDot status="online" />
    : <StatusDot status="offline" />;

  const dash = <span className="text-[var(--text-muted)]">—</span>;
  const sourceLabel = formatAddressSource(d.address_source);

  // Unmanaged devices (no config) don't have web_server info — never link their IP.
  // The IP column still gets the "via mDNS" / "wifi.use_address" / etc. source
  // label plus an "in HA" marker when Home Assistant confirms the device exists
  // (MAC or entity match). That lets the user tell a real ESPHome device without
  // a YAML from a stray mDNS broadcast at a glance.
  return (
    <tr>
      <td></td>
      <td>
        <span className="device-name text-[var(--text-muted)]">{stripYaml(d.name)}</span>
        <div className="device-filename text-[#6b7280]">No config</div>
      </td>
      {isVisible('status') && <td>{statusEl}</td>}
      {isVisible('ha') && (
        <td className="text-[12px]">
          {d.ha_configured
            ? (d.ha_device_id
                ? (() => {
                    const href = haDeepLink(`/config/devices/device/${d.ha_device_id}`);
                    return href ? (
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener"
                        title="Open device in Home Assistant"
                        className="text-[var(--success)] no-underline hover:underline"
                      >
                        Yes ↗
                      </a>
                    ) : <span className="text-[var(--success)]">Yes</span>;
                  })()
                : <span className="text-[var(--success)]">Yes</span>)
            : dash}
        </td>
      )}
      {isVisible('ip') && (
        <td className="sensitive font-mono text-[12px]">
          <span className="text-[var(--text-muted)]">{d.ip_address || '—'}</span>
          {(sourceLabel || d.ha_configured) && (
            <div
              className="text-[10px] text-[var(--text-muted)] font-sans"
              title={
                d.ha_configured
                  ? `Address source: ${d.address_source ?? 'unknown'} · Home Assistant confirms this device exists`
                  : `Address source: ${d.address_source ?? 'unknown'}`
              }
            >
              {[sourceLabel, d.ha_configured ? 'in HA' : null].filter(Boolean).join(' · ')}
            </div>
          )}
        </td>
      )}
      {/* #10/#19 — Net/IP Config/AP columns. Unmanaged devices have no YAML
          so we can't know any of this; render dashes. The cell order MUST
          match the columns array order in the columns memo above:
            status → ha → ip → net → ipconfig → ap → running → area → comment → tags → project */}
      {isVisible('net') && <td className="text-[12px]">{dash}</td>}
      {isVisible('ipconfig') && <td className="text-[12px]">{dash}</td>}
      {isVisible('ap') && <td className="text-[12px]">{dash}</td>}
      {isVisible('schedule') && <td className="text-[12px]">{dash}</td>}
      {isVisible('running') && <td className="text-[12px]">{d.running_version || '—'}</td>}
      {isVisible('area') && <td className="text-[12px]">{dash}</td>}
      {isVisible('comment') && <td className="text-[12px]">{dash}</td>}
      {isVisible('tags') && <td className="text-[12px]"></td>}
      {isVisible('project') && <td className="text-[12px]">{dash}</td>}
      <td></td>
    </tr>
  );
}
