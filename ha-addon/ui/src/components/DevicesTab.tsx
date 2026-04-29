import { useCallback, useEffect, useMemo, useState } from 'react';
import { mutate as mutateGlobal } from 'swr';
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
  deleteArchivedConfig,
  pinTargetVersion,
  restoreArchivedConfig,
  unpinTargetVersion,
  updateTargetMeta,
} from '../api/client';
import { TagsEditDialog } from './TagsEditDialog';
import { TagFilterBar } from './TagFilterBar';
import type { AddressSource, Device, Job, Target, Worker } from '../types';
import { stripYaml, haDeepLink, usePersistedState } from '../utils';
import { StatusDot } from './StatusDot';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { getAriaSort } from './ui/sort-header';
import { DeleteModal, RenameModal } from './devices/DeviceTableModals';
import { useDeviceColumns } from './devices/useDeviceColumns';
import { DeviceTableActions } from './devices/DeviceTableActions';
import { hasDriftedConfig } from './devices/drift';
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
type OptionalColumnId = 'status' | 'ha' | 'ip' | 'mac' | 'running' | 'area' | 'comment' | 'tags' | 'project' | 'net' | 'ipconfig' | 'ap' | 'esp' | 'ble' | 'schedule' | 'last_compiled';

interface OptionalColumnDef {
  id: OptionalColumnId;
  label: string;
  defaultVisible: boolean;
}

// Bug #19: order MUST match the actual column render order in
// ``useDeviceColumns.tsx`` exactly — the picker renders checkboxes in
// this order, and a mismatch means toggling a column visually drifts
// from the user's left-to-right reading of the table. Enforced by
// ``OPTIONAL_COLUMNS_ORDER_MATCHES_TABLE`` invariant test in
// ``e2e/column-picker-order.spec.ts``.
//
// Current table order (from useDeviceColumns):
//   select, device, tags, status, ha, ip, mac, net, ipconfig, ap,
//   esp, ble, schedule, last_compiled, running, area, comment, project, actions
// Picker covers the optional / hideable subset (everything except
// select, device, actions which are always-visible).
const OPTIONAL_COLUMNS: OptionalColumnDef[] = [
  // TG.5: read-only chip-pill tag column. Default ON so a user adding
  // tags via YAML (or via TG.4's API) sees them without hunting through
  // the column-visibility menu first.
  { id: 'tags', label: 'Tags', defaultVisible: true },
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
  // Bug #23 + UD.5: chip family + PlatformIO board on a stacked
  // two-line cell, plus BLE proxy mode. Off by default — useful for
  // fleet-scale scanning ("which devices are ESP32-S3?", "which are
  // passive BLE proxies?") but adds two narrow columns most users
  // don't need on the default layout. Renamed "ESP" → "Platform" in
  // UD.5 to reflect that it now answers chip + board, not just chip.
  { id: 'esp', label: 'Platform', defaultVisible: false },
  { id: 'ble', label: 'BLE proxy', defaultVisible: false },
  { id: 'schedule', label: 'Schedule', defaultVisible: true },
  // JH.6: opt-in "Last compiled" column. Off by default so existing users
  // see no layout churn; power users toggle it on to spot stale devices.
  { id: 'last_compiled', label: 'Last compiled', defaultVisible: false },
  { id: 'running', label: 'ESPHome', defaultVisible: true },
  { id: 'area', label: 'Area', defaultVisible: false },
  { id: 'comment', label: 'Comment', defaultVisible: false },
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
  /**
   * Per-row click handler for the Upgrade button (#16). Opens the
   * UpgradeModal which collects worker + ESPHome version preferences.
   */
  onUpgradeOne: (target: string) => void;
  /**
   * Bug #107: bulk-upgrade entry point. The four Upgrade dropdown
   * items (All / Online / Outdated / Selected) materialise their target
   * lists here and open the UpgradeModal so the user can choose
   * worker/version/action just like the per-row flow. The chosen
   * options apply uniformly across the whole set.
   */
  onUpgradeMany: (targets: string[], displayName: string) => void;
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
  /** RC.1: open the read-only rendered-config viewer. */
  onViewRenderedConfig: (target: string) => void;
  /** DM.2: open the ICMP ping diagnostic modal. */
  onPing: (target: string) => void;
  /** DM.3: open the install-to-specific-address modal. */
  onInstallToAddress: (target: string) => void;
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

// UD.1: explanatory hover copy mirrored from useDeviceColumns.tsx for
// the unmanaged-row IP cell. Both surfaces should hover-explain the
// detection mechanism (especially ARP) instead of surfacing the raw
// enum.
function formatAddressSourceTooltip(source: AddressSource | null | undefined): string | null {
  switch (source) {
    case 'mdns': return 'Detected via mDNS — the device advertises itself on the local network with the hostname from the YAML.';
    case 'wifi_use_address': return 'From wifi.use_address in the device YAML — overrides hostname-based discovery.';
    case 'ethernet_use_address': return 'From ethernet.use_address in the device YAML — overrides hostname-based discovery.';
    case 'openthread_use_address': return 'From openthread.use_address in the device YAML — overrides hostname-based discovery.';
    case 'wifi_static_ip': return 'From wifi.manual_ip.static_ip in the device YAML — the OTA upload targets this fixed address.';
    case 'ethernet_static_ip': return 'From ethernet.manual_ip.static_ip in the device YAML — the OTA upload targets this fixed address.';
    case 'mdns_default': return null;
    case 'arp': return 'Detected via ARP scan of the local network — mDNS came up empty, so the add-on broadcast an ARP probe and matched the MAC against the device.';
    default: return null;
  }
}

// QS.19: RenameModal + DeleteModal live in ./devices/DeviceTableModals.
// RenameModal is re-exported so App.tsx's existing import path still works.
export { RenameModal };

export function DevicesTab({ targets, devices, workers, streamerMode, activeJobsByTarget, onUpgradeOne, onUpgradeMany, onEdit, onLogs, onToast, onDelete, onRename, onSchedule, onNewDevice, onDuplicate, onOpenHistory, onOpenCompileHistory, onCommitChanges, onViewRenderedConfig, onPing, onInstallToAddress, onRefresh }: Props) {
  const [filter, setFilter] = useState('');
  // TG.5 filter pills — selected tag set, persisted to localStorage so the
  // "show me kitchen OR bedroom" filter sticks across reloads.
  const [tagFilter, setTagFilter] = usePersistedState<string[]>('devices-tag-filter', []);
  // QS.27: persist sort across reloads via localStorage.
  const [sorting, setSorting] = usePersistedState<SortingState>('devices-sort', []);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(loadColumnVisibility);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [renameTarget, setRenameTarget] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  // #2: hamburger open state lives here so it survives row remounts
  // triggered by SWR polls. See useDeviceColumns / DeviceContextMenu.
  const [menuOpenTarget, setMenuOpenTarget] = useState<string | null>(null);
  // TG.5 inline edit — same lift-out-of-row pattern. ``null`` = closed.
  const [tagsEditTarget, setTagsEditTarget] = useState<string | null>(null);
  const [showUnmanaged, setShowUnmanaged] = useState(() => localStorage.getItem('showUnmanaged') !== 'false');
  // DM.1: in-tab archived toggle replaces the standalone
  // ArchivedDevicesList surface. Off by default so a fresh install
  // doesn't show archived rows; the column picker has a "Show archived
  // devices" entry that flips this. Persisted to localStorage so the
  // preference survives reloads (matching the showUnmanaged pattern).
  const [showArchived, setShowArchived] = useState(() => localStorage.getItem('devices-show-archived') === 'true');
  // #70: "Duplicate existing device" picker state. Opened from the
  // "Add device ▾" dropdown. Shows a list of existing targets the
  // user can pick to duplicate; selection calls onDuplicate() which
  // routes back to the NewDeviceModal in duplicate mode.
  const [duplicatePickerOpen, setDuplicatePickerOpen] = useState(false);
  // DM.1: per-row "permanently delete" two-step confirm. Mirrors the
  // existing DeleteModal flow but scoped to archived rows (the
  // restore-and-delete vocabulary is different, so the modal text is
  // tailored). ``null`` = closed; otherwise the archived filename
  // pending confirmation.
  const [permanentDeleteTarget, setPermanentDeleteTarget] = useState<string | null>(null);
  const [permanentDeleteBusy, setPermanentDeleteBusy] = useState(false);

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

  // DM.1: archived-row actions. Restore moves the YAML back under
  // /config/esphome/; permanent-delete opens the two-step confirm
  // dialog. The /ui/api/archive* endpoints stay in place for one
  // release as a soft-deprecate so external scripts don't break.
  const handleUnarchive = useCallback(async (target: string) => {
    try {
      await restoreArchivedConfig(target);
      onToast(`Restored ${stripYaml(target)}`, 'success');
      // The targets endpoint now drops the archived row + adds an
      // active one; the SWR poll will pick that up but a forced
      // refresh keeps the UI snappy. Plus invalidate the lingering
      // archived-configs SWR key (still used by the version banner).
      onRefresh();
      mutateGlobal('archived-configs');
    } catch (err) {
      onToast('Unarchive failed: ' + (err as Error).message, 'error');
    }
  }, [onToast, onRefresh]);

  const handlePermanentDeleteConfirm = useCallback(async () => {
    if (!permanentDeleteTarget) return;
    setPermanentDeleteBusy(true);
    try {
      await deleteArchivedConfig(permanentDeleteTarget);
      onToast(`Permanently deleted ${stripYaml(permanentDeleteTarget)}`, 'success');
      onRefresh();
      mutateGlobal('archived-configs');
      setPermanentDeleteTarget(null);
    } catch (err) {
      onToast('Delete failed: ' + (err as Error).message, 'error');
    } finally {
      setPermanentDeleteBusy(false);
    }
  }, [permanentDeleteTarget, onToast, onRefresh]);

  // Persist column visibility and unmanaged toggle to localStorage
  useEffect(() => {
    saveColumnVisibility(columnVisibility);
  }, [columnVisibility]);
  useEffect(() => {
    localStorage.setItem('showUnmanaged', String(showUnmanaged));
  }, [showUnmanaged]);
  useEffect(() => {
    localStorage.setItem('devices-show-archived', String(showArchived));
  }, [showArchived]);

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

  // TG.5 filter pills — fleet-wide tag pool with usage counts, sorted
  // alphabetically. The TagFilterBar component reads this directly.
  // #203: archived rows contribute their tags only when the user has
  // archived devices visible; otherwise the pill bar would offer tags
  // that filter no visible row (and bumping the count for an "Archived
  // only" tag would mislead — the count is over the visible set).
  const tagPool = useMemo(() => {
    const counts = new Map<string, number>();
    for (const t of targets) {
      if (t.archived && !showArchived) continue;
      if (t.tags) for (const tag of t.tags.split(',').map(s => s.trim()).filter(Boolean)) {
        counts.set(tag, (counts.get(tag) ?? 0) + 1);
      }
    }
    return Array.from(counts.entries())
      .map(([tag, count]) => ({ tag, count }))
      .sort((a, b) => a.tag.localeCompare(b.tag));
  }, [targets, showArchived]);

  // Filter targets before passing to TanStack (filter state owned here, not in TanStack)
  // DM.1: archived rows are included in the data set when the toggle is
  // on. They render in their own group below the active rows
  // (sorted-by-archived_at-desc), so their inclusion in the TanStack
  // data set is purely so the table can render them with the same
  // column flexRender pipeline.
  const filteredTargets = useMemo(() => {
    const visible = showArchived ? targets : targets.filter(t => !t.archived);
    const sorted = [...visible].sort((a, b) => a.target.localeCompare(b.target));
    // TG.5 filter pills: OR-logic across selected tags. A row matches
    // when it has *any* of the selected tags. Empty selection = no
    // filter (show everything). Applied before the search-box text
    // filter so a search with active pill filters narrows the
    // already-pill-filtered set.
    const tagFilterSet = new Set(tagFilter);
    const tagged = tagFilterSet.size === 0
      ? sorted
      : sorted.filter(t => {
          const ts = (t.tags || '').split(',').map(s => s.trim()).filter(Boolean);
          return ts.some(x => tagFilterSet.has(x));
        });
    if (!filter) return tagged;
    return tagged.filter(t =>
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
        // case-insensitive) on top of the pill filter.
        t.tags,
      )
    );
  }, [targets, filter, tagFilter, showArchived]);

  const filteredUnmanaged = useMemo(() => {
    // TG.5: an active pill filter means "show me devices with these
    // tags" — unmanaged devices have no tags, so hide them entirely
    // while a filter is active.
    if (tagFilter.length > 0) return [];
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
  }, [unmanaged, filter, tagFilter]);

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
    onViewRenderedConfig,
    onPing,
    onInstallToAddress,
    menuOpenTarget,
    setMenuOpenTarget,
    onEditTags: setTagsEditTarget,
    // Bug #3: Archive directly without opening the Delete confirmation
    // modal. The configs are restorable from the column-picker "Show
    // archived devices" toggle (DM.1 retired the separate dialog), so
    // a confirm step here just slows down a non-destructive action.
    onArchive: (target: string) => {
      onDelete(target, true);
      onToast(`Archived ${stripYaml(target)} — restore from the column picker → Show archived`, 'info');
    },
    // DM.1: archived-row actions.
    onUnarchive: handleUnarchive,
    onPermanentDelete: setPermanentDeleteTarget,
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

  // Bug #107: route every bulk-upgrade entry point through the
  // UpgradeModal so the user can pick worker/version/action up-front.
  function handleUpgradeSelected() {
    if (selectedTargets.length === 0) return;
    onUpgradeMany(selectedTargets, `${selectedTargets.length} selected device${selectedTargets.length === 1 ? '' : 's'}`);
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
            {/* DM.1: "Restore from archive…" entry retired. Archived
                devices are now visible in the table itself via the
                column picker → Show archived devices toggle, and
                Unarchive lives on each archived row's hamburger. */}
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
                  {/* Bug #107: every bulk-upgrade entry point opens the
                      shared UpgradeModal — same worker / version /
                      action picker as the per-row Upgrade button — and
                      applies the chosen options uniformly across the
                      affected set. */}
                  <DropdownMenuItem
                    onClick={() => {
                      const all = targets.map(t => t.target);
                      if (all.length > 0) onUpgradeMany(all, `all ${all.length} device${all.length === 1 ? '' : 's'}`);
                    }}
                    disabled={targets.length === 0}
                  >
                    Upgrade All
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => {
                      const onlineTargets = targets.filter(t => t.online !== false).map(t => t.target);
                      if (onlineTargets.length > 0) onUpgradeMany(onlineTargets, `${onlineTargets.length} online device${onlineTargets.length === 1 ? '' : 's'}`);
                    }}
                    disabled={!targets.some(t => t.online !== false)}
                  >
                    Upgrade All Online
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => {
                      const outdated = targets.filter(t => t.needs_update).map(t => t.target);
                      if (outdated.length > 0) onUpgradeMany(outdated, `${outdated.length} outdated device${outdated.length === 1 ? '' : 's'}`);
                    }}
                    disabled={!targets.some(t => t.needs_update)}
                  >
                    Upgrade Outdated
                  </DropdownMenuItem>
                  {/* 115: "Upgrade Changed" — devices whose YAML has
                      drifted from what's currently flashed. Shares the
                      `hasDriftedConfig` helper with the per-row drift
                      indicator so the menu picks the same set the user
                      already sees marked. Distinct from "Outdated" (the
                      latter is firmware-version mismatch; this is
                      configuration drift). */}
                  <DropdownMenuItem
                    onClick={() => {
                      const changed = targets.filter(hasDriftedConfig).map(t => t.target);
                      if (changed.length > 0) onUpgradeMany(changed, `${changed.length} changed device${changed.length === 1 ? '' : 's'}`);
                    }}
                    disabled={!targets.some(hasDriftedConfig)}
                  >
                    Upgrade Changed
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={handleUpgradeSelected}
                    disabled={selectedTargets.length === 0}
                  >
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
                  {/* DM.1: in-tab archived toggle — replaces the
                      separate ArchivedDevicesList surface. When on,
                      archived rows render below active rows at
                      opacity-50. */}
                  <DropdownMenuCheckboxItem
                    checked={showArchived}
                    onCheckedChange={() => setShowArchived(v => !v)}
                  >
                    Show archived devices
                  </DropdownMenuCheckboxItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
        {/* TG.5: filter pill bar — one pill per fleet tag with usage
            count, OR-logic across selections, persisted via
            usePersistedState above. Hidden when the fleet has no
            tags so a fresh install doesn't show an empty bar. */}
        <TagFilterBar tags={tagPool} selected={tagFilter} onChange={setTagFilter} />
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
                  {/* DM.1: split TanStack rows into two groups so
                      archived rows always sort below active rows
                      (regardless of which column the user clicked to
                      sort), and so each archived row carries
                      ``opacity-50`` + the ``data-archived`` hook the
                      e2e suite asserts on. The active group respects
                      whatever column sort TanStack produced; the
                      archived group is re-sorted by archived_at desc
                      so the most recently archived sits at the top. */}
                  {(() => {
                    const allRows = table.getRowModel().rows;
                    const activeRows = allRows.filter(r => !r.original.archived);
                    const archivedRows = allRows
                      .filter(r => r.original.archived)
                      .sort((a, b) => (b.original.archived_at ?? 0) - (a.original.archived_at ?? 0));
                    return (
                      <>
                        {activeRows.map(row => (
                          <tr key={row.id}>
                            {row.getVisibleCells().map(cell => (
                              <td key={cell.id}>
                                {flexRender(cell.column.columnDef.cell, cell.getContext())}
                              </td>
                            ))}
                          </tr>
                        ))}
                        {archivedRows.map(row => (
                          <tr
                            key={row.id}
                            data-archived="true"
                            className="opacity-50"
                          >
                            {row.getVisibleCells().map(cell => (
                              <td key={cell.id}>
                                {flexRender(cell.column.columnDef.cell, cell.getContext())}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </>
                    );
                  })()}
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

      {tagsEditTarget && (() => {
        const t = targets.find(x => x.target === tagsEditTarget);
        if (!t) return null;
        const initial = (t.tags || '')
          .split(',')
          .map(s => s.trim())
          .filter(Boolean);
        // Bug #11: fleet-wide tag pool for autocomplete. Union of every
        // device's tags + every worker's tags, sorted, deduped, scoped
        // to non-empty entries. Computed inline because it's tiny (a
        // handful of strings) and SWR already keeps both lists fresh.
        const pool = new Set<string>();
        for (const dt of targets) {
          if (dt.tags) for (const x of dt.tags.split(',').map(s => s.trim()).filter(Boolean)) pool.add(x);
        }
        for (const w of workers) {
          if (w.tags) for (const x of w.tags) pool.add(x);
        }
        const suggestions = Array.from(pool).sort();
        return (
          <TagsEditDialog
            open
            onOpenChange={(open) => { if (!open) setTagsEditTarget(null); }}
            subject={`Device ${stripYaml(t.target)}`}
            initial={initial}
            suggestions={suggestions}
            onSave={async (tags) => {
              // Existing /ui/api/targets/{filename}/meta endpoint stores
              // the comment block as one comma-joined string — re-use it
              // verbatim so tags round-trip through read_device_meta /
              // write_device_meta unchanged. Bug #9: send `null` (not "")
              // when the user clears every tag — `null` triggers the
              // server's `meta.pop(key)` path, and write_device_meta
              // strips the whole comment block once the dict is empty.
              const value: string | null = tags.length > 0 ? tags.join(',') : null;
              await updateTargetMeta(t.target, { tags: value });
              await onRefresh();
              onToast(`Saved tags for ${stripYaml(t.target)}`, 'success');
            }}
          />
        );
      })()}

      {/* QS.18: bulk schedule UpgradeModal moved into DeviceTableActions. */}

      {/* DM.1: per-row "permanently delete" confirm — destructive. Two
          steps because once the file leaves ``.archive/`` (and the
          tracked-history ``git rm``) there's no UI undo. Mirrors the
          exact copy the retired ArchivedDevicesList used to surface so
          the move from "separate panel" to "in-tab toggle" is
          UX-neutral. */}
      <Dialog
        open={permanentDeleteTarget !== null}
        onOpenChange={(o) => { if (!o && !permanentDeleteBusy) setPermanentDeleteTarget(null); }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Delete {permanentDeleteTarget} from the archive?
            </DialogTitle>
          </DialogHeader>
          <div className="px-4 py-3 text-sm text-[var(--text)]">
            <p>
              This removes the file from the archive directory. The device's prior contents
              stay in the config's git history — a git operator can recover them if needed.
            </p>
          </div>
          <div className="flex justify-end gap-2 px-4 pb-4">
            <button
              type="button"
              onClick={() => setPermanentDeleteTarget(null)}
              disabled={permanentDeleteBusy}
              className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface2)] px-2.5 h-7 text-[0.8rem] font-medium text-[var(--text)] hover:bg-[var(--surface3)] disabled:opacity-50 cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handlePermanentDeleteConfirm}
              disabled={permanentDeleteBusy}
              className="inline-flex items-center gap-1 rounded-lg border border-transparent bg-destructive px-2.5 h-7 text-[0.8rem] font-medium text-destructive-foreground hover:bg-destructive/80 disabled:opacity-50 cursor-pointer"
            >
              Delete
            </button>
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
      {/* Bug #16: tags column moved to position 2 in useDeviceColumns; mirror
          here. Unmanaged devices have no YAML so no tags — render empty. */}
      {isVisible('tags') && <td className="text-[12px]"></td>}
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
              title={(() => {
                const base = formatAddressSourceTooltip(d.address_source) ?? `Address source: ${d.address_source ?? 'unknown'}`;
                return d.ha_configured ? `${base} · Home Assistant confirms this device exists.` : base;
              })()}
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
      {isVisible('project') && <td className="text-[12px]">{dash}</td>}
      <td></td>
    </tr>
  );
}
