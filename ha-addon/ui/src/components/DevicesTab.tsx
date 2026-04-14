import { useCallback, useEffect, useMemo, useState } from 'react';
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
import { getApiKey, restartDevice, pinTargetVersion, unpinTargetVersion, setTargetSchedule } from '../api/client';
import { UpgradeModal } from './UpgradeModal';
import type { Device, Job, Target, Worker } from '../types';
import { stripYaml, timeAgo, haDeepLink, formatCronHuman } from '../utils';
import { StatusDot } from './StatusDot';
import { Button } from './ui/button';
import { SortHeader, getAriaSort } from './ui/sort-header';
import { DeleteModal, RenameModal } from './devices/DeviceTableModals';
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
type OptionalColumnId = 'status' | 'ha' | 'ip' | 'running' | 'area' | 'comment' | 'project' | 'net' | 'ipconfig' | 'ap' | 'schedule';

interface OptionalColumnDef {
  id: OptionalColumnId;
  label: string;
  defaultVisible: boolean;
}

const OPTIONAL_COLUMNS: OptionalColumnDef[] = [
  { id: 'status', label: 'Status', defaultVisible: true },
  { id: 'ha', label: 'HA', defaultVisible: true },
  { id: 'ip', label: 'IP', defaultVisible: true },
  { id: 'net', label: 'Net', defaultVisible: true },
  { id: 'running', label: 'Version', defaultVisible: true },
  { id: 'ipconfig', label: 'IP Config', defaultVisible: false },
  { id: 'ap', label: 'AP', defaultVisible: false },
  { id: 'schedule', label: 'Schedule', defaultVisible: true },
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
/**
 * Convert a 5-field cron expression to a short human-readable string.
 * Covers common presets; falls back to the raw expression for complex ones.
 */
function formatNetworkType(t: 'wifi' | 'ethernet' | 'thread' | null | undefined): string | null {
  switch (t) {
    case 'wifi': return 'WiFi';
    case 'ethernet': return 'Eth';
    case 'thread': return 'Thread';
    default: return null;
  }
}

function formatAddressSource(source: string | null | undefined): string | null {
  switch (source) {
    case 'mdns': return 'via mDNS';
    case 'wifi_use_address': return 'wifi.use_address';
    case 'ethernet_use_address': return 'ethernet.use_address';
    case 'openthread_use_address': return 'openthread.use_address';
    case 'wifi_static_ip': return 'wifi static_ip';
    case 'ethernet_static_ip': return 'ethernet static_ip';
    case 'mdns_default': return null;
    default: return null;
  }
}

// QS.19: RenameModal + DeleteModal live in ./devices/DeviceTableModals.
// RenameModal is re-exported so App.tsx's existing import path still works.
export { RenameModal };

export function DevicesTab({ targets, devices, workers, streamerMode, activeJobsByTarget, onCompile, onUpgradeOne, onEdit, onLogs, onToast, onDelete, onRename, onSchedule, onNewDevice, onDuplicate, onRefresh }: Props) {
  const [filter, setFilter] = useState('');
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(loadColumnVisibility);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [menuTarget, setMenuTarget] = useState<Target | null>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null);
  const [renameTarget, setRenameTarget] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [showUnmanaged, setShowUnmanaged] = useState(() => localStorage.getItem('showUnmanaged') !== 'false');

  // VP.4: pin/unpin version from the hamburger menu.
  async function handlePin(target: string) {
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
  }

  async function handleUnpin(target: string) {
    try {
      await unpinTargetVersion(target);
      onToast(`Unpinned ${stripYaml(target)}`, 'success');
    } catch (err) {
      onToast('Unpin failed: ' + (err as Error).message, 'error');
    }
  }

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
            <span className="device-name">
              {t.friendly_name || t.device_name || stripYaml(t.target)}
              {t.schedule && t.schedule_enabled && (
                <span title={`Recurring schedule: ${t.schedule}`} style={{ marginLeft: 4, fontSize: 11, opacity: 0.7 }}>🕐</span>
              )}
              {t.schedule_once && (
                <span title={`One-time schedule: ${t.schedule_once}`} style={{ marginLeft: 4, fontSize: 11, opacity: 0.7 }}>📅</span>
              )}
            </span>
            <div className="device-filename">{stripYaml(t.target)}</div>
          </>
        ),
        sortingFn: 'alphanumeric',
      }
    ),
    columnHelper.accessor(
      row => {
        // Active job sorts first so a "currently upgrading" group sticks to
        // the top of an ascending sort.
        if (activeJobsByTarget.has(row.target)) return 'a-upgrading';
        if (row.online == null) return 'b-unknown';
        return row.online ? 'c-online' : 'd-offline';
      },
      {
        id: 'status',
        header: ({ column }) => <SortHeader label="Status" column={column} />,
        cell: ({ row: { original: t } }) => {
          const lastSeenEl = t.last_seen
            ? <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{timeAgo(t.last_seen)}</div>
            : null;
          // Active job takes priority over the device's online state — even
          // an offline device can have a job in flight (the worker compiles
          // first, OTA happens later).
          const activeJob = activeJobsByTarget.get(t.target);
          if (activeJob) {
            const statusText = activeJob.status_text || (activeJob.state === 'pending' ? 'Pending…' : 'Compiling…');
            return (
              <span title={statusText}>
                <StatusDot status="upgrading" label={statusText} />
              </span>
            );
          }
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
        cell: ({ row: { original: t } }) => {
          if (!t.ha_configured) {
            return <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>—</span>;
          }
          // #35: when we have a device_id (matched via MAC), make "Yes" a
          // clickable deep-link to the HA device page. If we don't have a
          // device_id (matched only via name), just show the text.
          if (t.ha_device_id) {
            const href = haDeepLink(`/config/devices/device/${t.ha_device_id}`);
            if (href) {
              return (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener"
                  title="Open device in Home Assistant"
                  style={{ fontSize: 12, color: 'var(--success)', textDecoration: 'none' }}
                  className="hover:underline"
                >
                  Yes ↗
                </a>
              );
            }
          }
          return <span style={{ fontSize: 12, color: 'var(--success)' }}>Yes</span>;
        },
        sortingFn: 'alphanumeric',
      }
    ),
    columnHelper.accessor(row => row.ip_address || '', {
      id: 'ip',
      header: ({ column }) => <SortHeader label="IP" column={column} />,
      cell: ({ row: { original: t } }) => {
        // In streamer mode: still blur via .sensitive CSS, but disable the
        // link so screenshots can't be click-through targets.
        const showIpLink = !streamerMode && t.has_web_server && t.online && t.ip_address;
        const sourceLabel = formatAddressSource(t.address_source);
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
            {sourceLabel && (
              <div
                style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'sans-serif' }}
                title={`Address source: ${t.address_source}`}
              >
                {sourceLabel}
              </div>
            )}
          </span>
        );
      },
      sortingFn: 'alphanumeric',
    }),
    // #10 — network type (default-visible). Sorts by primary network then
    // by ip mode (static before dhcp), so an ascending sort groups
    // "WiFi · Static" together followed by "WiFi · DHCP", then Ethernet,
    // then Thread. Tooltip shows all five facts in one line. The "·M"
    // suffix marks Matter devices (#13).
    columnHelper.accessor(
      row => `${row.network_type ?? 'zzz'}-${row.network_static_ip ? '0' : '1'}-${row.network_matter ? '0' : '1'}`,
      {
        id: 'net',
        header: ({ column }) => <SortHeader label="Net" column={column} />,
        cell: ({ row: { original: t } }) => {
          const label = formatNetworkType(t.network_type);
          if (!label) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
          const ipMode = t.network_static_ip ? 'Static' : 'DHCP';
          const facts: string[] = [label, ipMode];
          if (t.network_ipv6) facts.push('IPv6');
          if (t.network_ap_fallback) facts.push('AP fallback');
          if (t.network_matter) facts.push('Matter');
          const tooltip = facts.join(' · ');
          return (
            <span
              style={{
                fontSize: 11,
                color: 'var(--text)',
                whiteSpace: 'nowrap',
              }}
              title={tooltip}
            >
              {label}
              {t.network_static_ip && (
                <span style={{ color: 'var(--text-muted)', fontSize: 10, marginLeft: 3 }} title="Static IP">·S</span>
              )}
              {t.network_matter && (
                <span style={{ color: 'var(--accent)', fontSize: 10, marginLeft: 3 }} title="Matter">·M</span>
              )}
            </span>
          );
        },
        sortingFn: 'alphanumeric',
      },
    ),
    // #19: combined IP Mode + IPv6 column. Sorts by mode then by ipv6 so an
    // ascending sort groups all "Static + IPv6" together. Renders as e.g.
    // "Static · IPv6" or just "DHCP" or "—" for unmanaged-network targets.
    columnHelper.accessor(
      row => {
        if (!row.network_type) return '';
        const mode = row.network_static_ip ? 'static' : 'dhcp';
        return `${mode}-${row.network_ipv6 ? '6' : '4'}`;
      },
      {
        id: 'ipconfig',
        header: ({ column }) => <SortHeader label="IP Config" column={column} />,
        cell: ({ row: { original: t } }) => {
          if (!t.network_type) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
          const mode = t.network_static_ip ? 'Static' : 'DHCP';
          return (
            <span style={{ fontSize: 12 }} title={`${mode}${t.network_ipv6 ? ' · IPv6' : ''}`}>
              {mode}
              {t.network_ipv6 && (
                <span style={{ color: 'var(--success)', marginLeft: 4 }}>· IPv6</span>
              )}
            </span>
          );
        },
        sortingFn: 'alphanumeric',
      },
    ),
    columnHelper.accessor(row => row.network_ap_fallback ? 'yes' : '', {
      id: 'ap',
      header: ({ column }) => <SortHeader label="AP" column={column} />,
      cell: ({ row: { original: t } }) => (
        <span
          style={{ fontSize: 12 }}
          title={t.network_ap_fallback ? 'Fallback access point configured (wifi.ap)' : undefined}
        >
          {t.network_ap_fallback
            ? <span style={{ color: 'var(--success)' }}>Yes</span>
            : <span style={{ color: 'var(--text-muted)' }}>—</span>}
        </span>
      ),
      sortingFn: 'alphanumeric',
    }),
    // #5/#40/#92: human-readable schedule column. Renders BOTH the recurring
    // cron and any one-time schedule when both are set, stacked. Toggleable
    // (default off).
    columnHelper.accessor(row => row.schedule || row.schedule_once || '', {
      id: 'schedule',
      header: ({ column }) => <SortHeader label="Schedule" column={column} />,
      cell: ({ row: { original: t } }) => {
        // #72: schedule values are clickable → open upgrade modal in schedule mode
        const handleClick = () => onSchedule(t.target);
        if (!t.schedule && !t.schedule_once) {
          return <span style={{ color: 'var(--text-muted)' }}>—</span>;
        }
        const enabled = t.schedule_enabled !== false;
        const tzLabel = ` (${t.schedule_tz || 'UTC'})`;
        const cronHuman = t.schedule ? formatCronHuman(t.schedule) : null;
        const onceWhen = t.schedule_once ? new Date(t.schedule_once).toLocaleString() : null;
        const titleParts: string[] = [];
        if (t.schedule) titleParts.push(`${t.schedule}${tzLabel}${enabled ? '' : ' (paused)'}`);
        if (t.schedule_once) titleParts.push(`One-time: ${t.schedule_once}`);
        return (
          <span
            style={{ cursor: 'pointer', color: 'var(--accent)' }}
            title={`${titleParts.join(' • ')} — click to edit`}
            onClick={handleClick}
          >
            {cronHuman && (
              <span style={{ opacity: enabled ? 1 : 0.5 }}>
                🕐 {cronHuman}
                {!enabled && <span style={{ color: 'var(--text-muted)', marginLeft: 4 }}>(paused)</span>}
              </span>
            )}
            {cronHuman && onceWhen && <br />}
            {onceWhen && <span>📅 Once: {onceWhen}</span>}
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
          {t.pinned_version && (
            <span title={`Pinned to ${t.pinned_version}`} style={{ marginLeft: 4, fontSize: 10 }}>📌</span>
          )}
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
        // #23 revision: the Upgrade button stays enabled even while a job
        // is running for this target. Clicking it re-opens the UpgradeModal
        // and the server-side coalescing rules (#23) take care of the rest:
        // the second click creates a single "Queued" follow-up; a third
        // click updates that follow-up in place. This matches the
        // CLAUDE.md "Disable, don't fail" guideline's explicit Upgrade
        // exception — compiling for a target is always meaningful, even
        // if one is already running, because the latest YAML will be used.
        const inFlight = activeJobsByTarget.has(t.target);
        const upgradeTitle = inFlight
          ? `A build is already running. Click to queue the next compile (will use the latest YAML at the time it starts).`
          : undefined;
        return (
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <Button
              variant={upgradeVariant as 'success' | 'secondary'}
              size="sm"
              title={upgradeTitle}
              onClick={() => onUpgradeOne(t.target)}
            >
              Upgrade
            </Button>
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
  ], [workers, onCompile, onUpgradeOne, onEdit, onLogs, onToast, onSchedule]);

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

  // #2: "Schedule Selected" — open the schedule modal in multi-target mode.
  // We reuse the same ScheduleModal but apply the result to all selected targets.
  const [bulkScheduleOpen, setBulkScheduleOpen] = useState(false);
  function handleScheduleSelected() {
    if (selectedTargets.length === 0) return;
    setBulkScheduleOpen(true);
  }

  // #15: bulk remove schedule from selected devices.
  // #37: include devices with a one-time schedule, not just recurring.
  async function handleRemoveScheduleSelected() {
    const scheduled = selectedTargets.filter(t => {
      const target = targets.find(x => x.target === t);
      return target?.schedule || target?.schedule_once;
    });
    if (scheduled.length === 0) {
      onToast('No selected devices have a schedule', 'info');
      return;
    }
    try {
      const { deleteTargetSchedule } = await import('../api/client');
      await Promise.all(scheduled.map(t => deleteTargetSchedule(t)));
      onToast(`Removed schedule from ${scheduled.length} device(s)`, 'success');
      onRefresh();
    } catch (err) {
      onToast('Remove failed: ' + (err as Error).message, 'error');
    }
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
            {/* CD.5: "+ New Device" button. #46: use default variant (primary
                styling) so it reads as a real action button, matching the visual
                weight of the Upgrade/Actions dropdown triggers next to it. */}
            <Button size="sm" onClick={onNewDevice} title="Create a new device YAML">
              + New Device
            </Button>
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

            {/* #8: Actions dropdown — non-compile bulk operations */}
            <DropdownMenu>
              <DropdownMenuTrigger className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2.5 h-7 text-[0.8rem] font-medium text-foreground hover:bg-muted cursor-pointer">
                Actions <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                  <DropdownMenuItem onClick={handleScheduleSelected} disabled={Object.keys(rowSelection).length === 0}>
                    Schedule Selected...
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={handleRemoveScheduleSelected}
                    disabled={Object.keys(rowSelection).length === 0}
                  >
                    Remove Schedule from Selected
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Column picker (gear icon) */}
            <DropdownMenu>
              <DropdownMenuTrigger className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2.5 h-7 text-[0.8rem] font-medium text-foreground hover:bg-muted cursor-pointer" title="Toggle columns">
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

      {bulkScheduleOpen && (
        <UpgradeModal
          target="(multiple)"
          displayName={`${selectedTargets.length} device${selectedTargets.length > 1 ? 's' : ''}`}
          workers={workers}
          esphomeVersions={[]}
          defaultEsphomeVersion={null}
          scheduleOnly
          defaultMode="schedule"
          onUpgradeNow={() => {}}
          onSaveSchedule={async (cron, _version, tz) => {
            try {
              await Promise.all(selectedTargets.map(t => setTargetSchedule(t, cron, tz)));
              onToast(`Schedule set for ${selectedTargets.length} device(s)`, 'success');
              setBulkScheduleOpen(false);
              onRefresh();
            } catch (err) {
              onToast('Schedule failed: ' + (err as Error).message, 'error');
            }
          }}
          onSaveOnce={async (datetime, _version) => {
            try {
              const { setTargetScheduleOnce } = await import('../api/client');
              await Promise.all(selectedTargets.map(t => setTargetScheduleOnce(t, datetime)));
              onToast(`One-time upgrade scheduled for ${selectedTargets.length} device(s)`, 'success');
              setBulkScheduleOpen(false);
              onRefresh();
            } catch (err) {
              onToast('Schedule failed: ' + (err as Error).message, 'error');
            }
          }}
          onDeleteSchedule={() => setBulkScheduleOpen(false)}
          onClose={() => setBulkScheduleOpen(false)}
        />
      )}

      {menuTarget && menuPos && (
        <DeviceMenu
          target={menuTarget}
          position={menuPos}
          onToast={onToast}
          onDelete={(t) => { setMenuTarget(null); setMenuPos(null); setDeleteTarget(t); }}
          onRename={(t) => { setMenuTarget(null); setMenuPos(null); setRenameTarget(t); }}
          onDuplicate={(t) => { setMenuTarget(null); setMenuPos(null); onDuplicate(t.target); }}
          onLogs={(t) => { setMenuTarget(null); setMenuPos(null); onLogs(t); }}
          onPin={(t) => { setMenuTarget(null); setMenuPos(null); handlePin(t); }}
          onUnpin={(t) => { setMenuTarget(null); setMenuPos(null); handleUnpin(t); }}
          onClose={() => { setMenuTarget(null); setMenuPos(null); }}
        />
      )}
    </div>
  );
}

// Inline sort header used in column defs — renders ▲/▼ indicators

function DeviceMenu({
  target: t,
  position,
  onToast,
  onDelete,
  onRename,
  onDuplicate,
  onLogs,
  onPin,
  onUnpin,
  onClose,
}: {
  target: Target;
  position: { top: number; left: number };
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
  onDelete: (target: string) => void;
  onRename: (target: string) => void;
  onDuplicate: (target: Target) => void;
  onLogs: (target: string) => void;
  onPin: (target: string) => void;
  onUnpin: (target: string) => void;
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

  return (
    <>
      {/* Backdrop to close on outside click */}
      <div className="fixed inset-0 z-50" onClick={onClose} />
      <div
        className="fixed z-50 min-w-[200px] w-max max-w-[320px] rounded-lg border border-[var(--border)] bg-[var(--popover)] p-1 text-[var(--popover-foreground)] shadow-md ring-1 ring-[var(--foreground)]/10"
        ref={(el) => {
          if (!el) return;
          const rect = el.getBoundingClientRect();
          // If menu extends below viewport, flip it upward
          if (rect.bottom > window.innerHeight) {
            el.style.top = `${Math.max(4, position.top - rect.height - 4)}px`;
          }
          // If menu extends beyond left edge after translateX(-100%), nudge right
          if (rect.left < 0) {
            el.style.left = `${position.left}px`;
            el.style.transform = 'none';
          }
        }}
        style={{ top: position.top, left: position.left, transform: 'translateX(-100%)' }}
      >
        <div className="px-1.5 py-1 text-xs font-medium text-[var(--text-muted)]">Device</div>
        <button className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-sm cursor-pointer hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]" onClick={() => onLogs(t.target)}>Live Logs</button>
        {/* #14: gray out Restart when the YAML doesn't expose a restart button.
            We follow the same disabled-with-tooltip pattern as the API Key
            button below — disabled rather than hidden so the user knows the
            option exists and what they need to do (add `button: - platform:
            restart` to the YAML). */}
        <button
          className={`flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-sm ${t.has_restart_button ? 'cursor-pointer hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]' : 'opacity-50 pointer-events-none'}`}
          onClick={handleRestart}
          title={t.has_restart_button ? undefined : 'No restart button in this device\'s YAML — add `button: [{platform: restart}]` to enable.'}
        >
          Restart
        </button>
        <button className={`flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-sm ${t.has_api_key ? 'cursor-pointer hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]' : 'opacity-50 pointer-events-none'}`} onClick={handleCopyApiKey}>Copy API Key</button>

        <div className="-mx-1 my-1 h-px bg-[var(--border)]" />

        <div className="px-1.5 py-1 text-xs font-medium text-[var(--text-muted)]">Config</div>
        {/* #93: "Schedule Upgrade…" removed — accessible via the Upgrade
            button by switching to "Scheduled" mode. */}
        {t.pinned_version
          ? <button className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-sm cursor-pointer hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]" onClick={() => onUnpin(t.target)}>Unpin version ({t.pinned_version})</button>
          : <button className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-sm cursor-pointer hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]" onClick={() => onPin(t.target)}>Pin to current version</button>
        }
        <button className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-sm cursor-pointer hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]" onClick={() => onRename(t.target)}>Rename</button>
        {/* CD.6: duplicate this device into a new file */}
        <button className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-sm cursor-pointer hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]" onClick={() => onDuplicate(t)}>Duplicate…</button>
        <button className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-sm cursor-pointer text-[var(--destructive)] hover:bg-[var(--destructive)]/10" onClick={() => onDelete(t.target)}>Delete</button>

        {/*
          #16: the "Upgrade on..." submenu was removed from the per-row
          context menu. Worker selection now lives in the UpgradeModal that
          opens from the row's Upgrade button itself, which also lets the
          user pick the ESPHome version. The hover-bridge / width work from
          #31 was on this submenu — that fix lives on in the historical
          1.3.1 dev cycle but the affected element no longer exists.
        */}
      </div>
    </>
  );
}

function UnmanagedRow({ device: d, isVisible }: { device: Device; isVisible: (col: OptionalColumnId) => boolean }) {
  const statusEl = d.online
    ? <StatusDot status="online" />
    : <StatusDot status="offline" />;

  const dash = <span style={{ color: 'var(--text-muted)' }}>—</span>;
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
        <span className="device-name" style={{ color: 'var(--text-muted)' }}>{stripYaml(d.name)}</span>
        <div className="device-filename" style={{ color: '#6b7280' }}>No config</div>
      </td>
      {isVisible('status') && <td>{statusEl}</td>}
      {isVisible('ha') && (
        <td style={{ fontSize: 12 }}>
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
                        style={{ color: 'var(--success)', textDecoration: 'none' }}
                        className="hover:underline"
                      >
                        Yes ↗
                      </a>
                    ) : <span style={{ color: 'var(--success)' }}>Yes</span>;
                  })()
                : <span style={{ color: 'var(--success)' }}>Yes</span>)
            : dash}
        </td>
      )}
      {isVisible('ip') && (
        <td style={{ fontFamily: 'monospace', fontSize: 12 }} className="sensitive">
          <span style={{ color: 'var(--text-muted)' }}>{d.ip_address || '—'}</span>
          {(sourceLabel || d.ha_configured) && (
            <div
              style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'sans-serif' }}
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
            status → ha → ip → net → ipconfig → ap → running → area → comment → project */}
      {isVisible('net') && <td style={{ fontSize: 12 }}>{dash}</td>}
      {isVisible('ipconfig') && <td style={{ fontSize: 12 }}>{dash}</td>}
      {isVisible('ap') && <td style={{ fontSize: 12 }}>{dash}</td>}
      {isVisible('schedule') && <td style={{ fontSize: 12 }}>{dash}</td>}
      {isVisible('running') && <td style={{ fontSize: 12 }}>{d.running_version || '—'}</td>}
      {isVisible('area') && <td style={{ fontSize: 12 }}>{dash}</td>}
      {isVisible('comment') && <td style={{ fontSize: 12 }}>{dash}</td>}
      {isVisible('project') && <td style={{ fontSize: 12 }}>{dash}</td>}
      <td></td>
    </tr>
  );
}
