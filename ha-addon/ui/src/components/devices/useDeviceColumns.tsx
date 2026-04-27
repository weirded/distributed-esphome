import { useMemo } from 'react';
import { Calendar, Clock, ExternalLink, GitBranch, Pin } from 'lucide-react';
import { createColumnHelper } from '@tanstack/react-table';
import type { AddressSource, Job, Target } from '../../types';
import { stripYaml, timeAgo, haDeepLink, formatCronHuman, fmtEpochRelative, fmtEpochAbsolute } from '../../utils';
import { getJobBadge } from '../../utils/jobState';
import { StatusDot } from '../StatusDot';
import { SortHeader } from '../ui/sort-header';
import { ActionsCell } from './ActionsCell';
import { driftTooltip, hasDriftedConfig } from './drift';
import { TagChips } from '../ui/tag-chips';

/**
 * TG.5: parse the comma-separated ``tags`` string from the YAML metadata
 * comment block into a list. The wire shape stays a string today (one
 * source of truth, the YAML comment) — the array is purely for rendering
 * + autocomplete in the UI.
 */
function parseDeviceTags(s: string | null | undefined): string[] {
  if (!s) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of s.split(',')) {
    const t = raw.trim();
    if (!t || seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  return out;
}

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
  /** AV.6: open the per-file History panel from the row hamburger menu. */
  onOpenHistory: (target: string) => void;
  /** JH.5: open the per-device Compile History panel. */
  onOpenCompileHistory: (target: string) => void;
  /** Bug #16: open the manual-commit dialog for this target. */
  onCommitChanges: (target: string) => void;
  /**
   * #2 followup to QS.16: per-row hamburger open state is owned by
   * DevicesTab (not Radix's internal state) so it survives row re-mounts
   * triggered by SWR polls. Pass the currently open target's filename and
   * a setter that takes a target (or null to close).
   */
  menuOpenTarget: string | null;
  setMenuOpenTarget: (target: string | null) => void;
}

/**
 * Mirror of the `OptionalColumnId` type in DevicesTab. Exported here so the
 * two stay in sync when columns are added/removed.
 */
export type OptionalColumnId = 'status' | 'ha' | 'ip' | 'running' | 'area' | 'comment' | 'project' | 'net' | 'ipconfig' | 'ap' | 'schedule' | 'tags';

// --- Small per-cell formatters (kept private to this module) ---------------

function formatNetworkType(t: 'wifi' | 'ethernet' | 'thread' | null | undefined): string | null {
  switch (t) {
    case 'wifi': return 'WiFi';
    case 'ethernet': return 'Ethernet';
    case 'thread': return 'Thread';
    default: return null;
  }
}

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
    onOpenHistory,
    onOpenCompileHistory,
    onCommitChanges,
    menuOpenTarget,
    setMenuOpenTarget,
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
      // #72: sort by the YAML filename stem (the stable identifier) —
      // not the friendly name. Friendly names change with substitutions
      // and don't exist for every device; the YAML stem is what users
      // reason about in logs, file systems, and the Queue tab.
      row => stripYaml(row.target),
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
                <span title={`Recurring schedule: ${t.schedule}`} className="ml-1 inline-flex align-text-bottom opacity-70">
                  <Clock className="size-3" aria-label="Recurring schedule" />
                </span>
              )}
              {t.schedule_once && (
                <span title={`One-time schedule: ${t.schedule_once}`} className="ml-1 inline-flex align-text-bottom opacity-70">
                  <Calendar className="size-3" aria-label="One-time schedule" />
                </span>
              )}
              {/* Bug #16: uncommitted-changes indicator. Clicking the
                  pill opens the per-file History panel so the user
                  can review the diff and commit from there. */}
              {t.has_uncommitted_changes && (
                <button
                  type="button"
                  className="ml-1.5 inline-flex items-center gap-1 rounded-full border border-yellow-500/40 bg-yellow-500/15 px-1.5 py-0 text-[10px] text-yellow-300 hover:bg-yellow-500/25 cursor-pointer align-text-bottom"
                  onClick={(e) => { e.stopPropagation(); onOpenHistory(t.target); }}
                  title="This device's YAML has uncommitted changes. Click to open the history panel and commit them."
                  aria-label="Uncommitted changes"
                >
                  <GitBranch className="size-3" aria-hidden />
                  Uncommitted
                </button>
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
            ? <div className="text-[10px] text-[var(--text-muted)]">{timeAgo(t.last_seen)}</div>
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
            return <span className="text-[12px] text-[var(--text-muted)]">—</span>;
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
                  className="inline-flex items-center gap-0.5 text-[12px] text-[var(--success)] no-underline hover:underline"
                >
                  Yes <ExternalLink className="size-3" aria-hidden="true" />
                </a>
              );
            }
          }
          return <span className="text-[12px] text-[var(--success)]">Yes</span>;
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
          <span className="sensitive font-mono text-[12px]">
            {showIpLink
              ? (
                <a
                  href={`http://${t.ip_address}`}
                  target="_blank"
                  rel="noopener"
                  className="ip-link"
                >
                  {t.ip_address}<ExternalLink className="inline ml-0.5 size-3 align-text-bottom" aria-hidden="true" />
                </a>
              )
              : <span className="text-[var(--text-muted)]">{t.ip_address || '—'}</span>}
            {sourceLabel && (
              <div
                className="text-[10px] text-[var(--text-muted)] font-sans"
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
    // Bug #12 (1.6.1): MAC column. Off by default so the row width
    // doesn't blow up for users who don't care — toggle on via the
    // Columns picker. Sourced from ``dev.mac_address`` in the
    // device_poller, populated via mDNS TXT or native API poll.
    columnHelper.accessor(row => row.mac_address || '', {
      id: 'mac',
      header: ({ column }) => <SortHeader label="MAC" column={column} />,
      cell: ({ row: { original: t } }) => (
        <span className="sensitive font-mono text-[12px] text-[var(--text-muted)] whitespace-nowrap">
          {t.mac_address || '—'}
        </span>
      ),
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(
      row => `${row.network_type ?? 'zzz'}-${row.network_static_ip ? '0' : '1'}-${row.network_matter ? '0' : '1'}`,
      {
        id: 'net',
        header: ({ column }) => <SortHeader label="Net" column={column} />,
        cell: ({ row: { original: t } }) => {
          const label = formatNetworkType(t.network_type);
          if (!label) return <span className="text-[var(--text-muted)]">—</span>;
          const ipMode = t.network_static_ip ? 'Static' : 'DHCP';
          const facts: string[] = [label, ipMode];
          if (t.network_ipv6) facts.push('IPv6');
          if (t.network_ap_fallback) facts.push('AP fallback');
          if (t.network_matter) facts.push('Matter');
          const tooltip = facts.join(' · ');
          return (
            <span
              className="text-[11px] text-[var(--text)] whitespace-nowrap"
              title={tooltip}
            >
              {label}
              {t.network_static_ip && (
                <span className="ml-[3px] text-[10px] text-[var(--text-muted)]" title="Static IP">·S</span>
              )}
              {t.network_matter && (
                <span className="ml-[3px] text-[10px] text-[var(--accent)]" title="Matter">·M</span>
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
          if (!t.network_type) return <span className="text-[var(--text-muted)]">—</span>;
          const mode = t.network_static_ip ? 'Static' : 'DHCP';
          return (
            <span className="text-[12px]" title={`${mode}${t.network_ipv6 ? ' · IPv6' : ''}`}>
              {mode}
              {t.network_ipv6 && (
                <span className="ml-1 text-[var(--success)]">· IPv6</span>
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
          className="text-[12px]"
          title={t.network_ap_fallback ? 'Fallback access point configured (wifi.ap)' : undefined}
        >
          {t.network_ap_fallback
            ? <span className="text-[var(--success)]">Yes</span>
            : <span className="text-[var(--text-muted)]">—</span>}
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
          return <span className="text-[var(--text-muted)]">—</span>;
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
            className="cursor-pointer text-[var(--accent)]"
            title={`${titleParts.join(' • ')} — click to edit`}
            onClick={handleClick}
          >
            {cronHuman && (
              // opacity stays inline — runtime-conditional on `enabled`.
              <span className="inline-flex items-center gap-1" style={{ opacity: enabled ? 1 : 0.5 }}>
                <Clock className="size-3" aria-hidden="true" />
                {cronHuman}
                {!enabled && <span className="ml-1 text-[var(--text-muted)]">(paused)</span>}
              </span>
            )}
            {cronHuman && onceWhen && <br />}
            {onceWhen && (
              <span className="inline-flex items-center gap-1">
                <Calendar className="size-3" aria-hidden="true" />
                Once: {onceWhen}
              </span>
            )}
          </span>
        );
      },
      sortingFn: 'alphanumeric',
    }),
    // JH.6: optional "Last compiled" column. Sort key is the finished_at
    // epoch, so DESC puts most recently compiled devices first (what
    // power users want when scanning for stale hosts).
    columnHelper.accessor(row => row.last_compile?.at ?? 0, {
      id: 'last_compiled',
      header: ({ column }) => <SortHeader label="Last compiled" column={column} />,
      cell: ({ row: { original: t } }) => {
        const lc = t.last_compile;
        if (!lc) {
          // #68: consistent with other "unknown" cells across the table —
          // render a muted em-dash rather than asserting "never", which
          // overclaims given the history table might not have pre-dev.23
          // compiles.
          return <span className="text-[12px] text-[var(--text-muted)]">—</span>;
        }
        // #77 / UX_REVIEW §1.5: reuse ``getJobBadge`` so the Devices
        // column's chip matches the Queue tab and JH.5 history surfaces
        // exactly. Previously we hand-rolled a ✓/✗/· glyph that drifted
        // in shape + colour from the pill badges on the other two
        // surfaces.
        const badge = getJobBadge({
          state: lc.state,
          ota_result: lc.ota_result ?? undefined,
          validate_only: lc.validate_only,
          download_only: lc.download_only,
        });
        // PR #64 review: use shared fmtEpochRelative + fmtEpochAbsolute
        // so this cell respects the ``time_format`` Settings preference
        // (auto / 12h / 24h) via the module-local pref in utils/format.
        // Prior inline ``toLocaleString()`` call ignored that setting.
        const rel = fmtEpochRelative(lc.at);
        const iso = fmtEpochAbsolute(lc.at);
        return (
          <span
            className="text-[12px] tabular-nums inline-flex items-center gap-1.5"
            title={`${iso} · ${lc.state}${lc.ota_result ? ` / ota=${lc.ota_result}` : ''}`}
          >
            <span className="text-[var(--text-muted)]">{rel}</span>
            <span className={badge.cls}>{badge.label}</span>
          </span>
        );
      },
      // PR #64 review: epoch seconds are a number — ``alphanumeric``
      // sorts them lexically (100 < 9). ``basic`` compares with
      // ``<`` directly on the accessor value, which is what we want.
      sortingFn: 'basic',
    }),
    columnHelper.accessor(row => row.running_version || '', {
      id: 'running',
      // Bug #29: "Version" was ambiguous now that the config git history
      // also exposes a version concept. Labeled "ESPHome" so the
      // Devices / Schedules / Queue columns all agree on the domain.
      header: ({ column }) => <SortHeader label="ESPHome" column={column} />,
      cell: ({ row: { original: t } }) => (
        <span className="text-[12px]">
          {t.running_version || '—'}
          {t.pinned_version && (
            <span title={`Pinned ESPHome version: ${t.pinned_version}`} className="ml-1 inline-flex align-text-bottom">
              <Pin className="size-3" aria-label="Pinned ESPHome version" />
            </span>
          )}
          {hasDriftedConfig(t) && (
            <div className="config-modified" title={driftTooltip(t)}>config changed</div>
          )}
        </span>
      ),
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(row => row.area || '', {
      id: 'area',
      header: ({ column }) => <SortHeader label="Area" column={column} />,
      cell: ({ row: { original: t } }) => (
        <span className="text-[12px]">
          {t.area || <span className="text-[var(--text-muted)]">—</span>}
        </span>
      ),
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(row => row.comment || '', {
      id: 'comment',
      header: ({ column }) => <SortHeader label="Comment" column={column} />,
      cell: ({ row: { original: t } }) => (
        <span className="block max-w-[200px] overflow-hidden text-ellipsis whitespace-nowrap text-[12px]">
          {t.comment || <span className="text-[var(--text-muted)]">—</span>}
        </span>
      ),
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(row => row.tags || '', {
      id: 'tags',
      header: 'Tags',
      cell: ({ row: { original: t } }) => <TagChips tags={parseDeviceTags(t.tags)} />,
      enableSorting: false,
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
            <span className="text-[12px]">
              {projectStr === '—' ? <span className="text-[var(--text-muted)]">—</span> : projectStr}
            </span>
          );
        },
        sortingFn: 'alphanumeric',
      }
    ),
    columnHelper.display({
      id: 'actions',
      enableHiding: false,
      cell: ({ row: { original: t } }) => (
        <ActionsCell
          target={t}
          inFlight={activeJobsByTarget.has(t.target)}
          menuOpen={menuOpenTarget === t.target}
          onUpgradeOne={onUpgradeOne}
          onEdit={onEdit}
          onLogs={onLogs}
          onToast={onToast}
          onDuplicate={onDuplicate}
          onRequestRename={onRequestRename}
          onRequestDelete={onRequestDelete}
          onPin={onPin}
          onUnpin={onUnpin}
          onOpenHistory={onOpenHistory}
          onOpenCompileHistory={onOpenCompileHistory}
          onCommitChanges={onCommitChanges}
          onMenuOpenChange={(o) => setMenuOpenTarget(o ? t.target : null)}
        />
      ),
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
    onOpenHistory,
    onOpenCompileHistory,
    onCommitChanges,
    menuOpenTarget,
    setMenuOpenTarget,
  ]);
}
