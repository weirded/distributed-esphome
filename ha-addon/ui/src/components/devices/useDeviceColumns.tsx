import { useMemo } from 'react';
import { createColumnHelper } from '@tanstack/react-table';
import type { Job, Target } from '../../types';
import { stripYaml, timeAgo, haDeepLink, formatCronHuman } from '../../utils';
import { StatusDot } from '../StatusDot';
import { Button } from '../ui/button';
import { SortHeader } from '../ui/sort-header';
import { DeviceContextMenu } from './DeviceContextMenu';

/**
 * TanStack column defs for the Devices tab (QS.17).
 *
 * Extracted from DevicesTab.tsx, which was carrying a 369-line inline
 * columns useMemo plus a `// eslint-disable-next-line react-hooks/
 * exhaustive-deps` because the reviewer couldn't hand-verify the 16
 * closure values it captured.
 *
 * By moving the block to its own hook with a typed `options` object we get:
 *   - A real, explicit dep list (removes the eslint-disable)
 *   - DevicesTab drops from ~1,000 lines to ~650
 *   - The columns can be tested / swapped independently if we later split
 *     the table into managed/unmanaged views
 *
 * Callers are expected to memoize unstable handlers with useCallback so the
 * hook's deps stay referentially stable between renders (QS.20 follow-up).
 */

type ToastFn = (msg: string, type?: 'info' | 'success' | 'error') => void;

interface Options {
  activeJobsByTarget: Map<string, Job>;
  streamerMode: boolean;
  onUpgradeOne: (target: string) => void;
  onEdit: (target: string) => void;
  onLogs: (target: string) => void;
  onToast: ToastFn;
  onSchedule: (target: string) => void;
  onDuplicate: (target: string) => void;
  onRequestRename: (target: string) => void;
  onRequestDelete: (target: string) => void;
  onPin: (target: string) => void;
  onUnpin: (target: string) => void;
}

/**
 * Mirror of the `OptionalColumnId` type in DevicesTab. Exported here so the
 * two stay in sync when columns are added/removed.
 */
export type OptionalColumnId = 'status' | 'ha' | 'ip' | 'running' | 'area' | 'comment' | 'project' | 'net' | 'ipconfig' | 'ap' | 'schedule';

// --- Small per-cell formatters (kept private to this module) ---------------

function formatNetworkType(t: 'wifi' | 'ethernet' | 'thread' | null | undefined): string | null {
  switch (t) {
    case 'wifi': return 'WiFi';
    case 'ethernet': return 'Ethernet';
    case 'thread': return 'Thread';
    default: return null;
  }
}

function formatAddressSource(source: string | null | undefined): string | null {
  switch (source) {
    case 'static': return 'static';
    case 'static_ip': return 'static_ip';
    case 'override_yaml': return 'override (yaml)';
    case 'override_static': return 'override (static)';
    case 'override_use_address': return 'override (use_address)';
    case 'ethernet_static_ip': return 'ethernet static_ip';
    case 'mdns_default': return null;
    default: return null;
  }
}

// --- The hook --------------------------------------------------------------

const columnHelper = createColumnHelper<Target>();

export function useDeviceColumns(options: Options) {
  const {
    activeJobsByTarget,
    streamerMode,
    onUpgradeOne,
    onEdit,
    onLogs,
    onToast,
    onSchedule,
    onDuplicate,
    onRequestRename,
    onRequestDelete,
    onPin,
    onUnpin,
  } = options;

  return useMemo(() => [
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
              style={{ fontSize: 11, color: 'var(--text)', whiteSpace: 'nowrap' }}
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
    columnHelper.accessor(row => row.schedule || row.schedule_once || '', {
      id: 'schedule',
      header: ({ column }) => <SortHeader label="Schedule" column={column} />,
      cell: ({ row: { original: t } }) => {
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
            <DeviceContextMenu
              target={t}
              onToast={onToast}
              onRename={onRequestRename}
              onDuplicate={(tg) => onDuplicate(tg.target)}
              onDelete={onRequestDelete}
              onLogs={onLogs}
              onPin={onPin}
              onUnpin={onUnpin}
            />
          </div>
        );
      },
    }),
  ], [
    activeJobsByTarget,
    streamerMode,
    onUpgradeOne,
    onEdit,
    onLogs,
    onToast,
    onSchedule,
    onDuplicate,
    onRequestRename,
    onRequestDelete,
    onPin,
    onUnpin,
  ]);
}
