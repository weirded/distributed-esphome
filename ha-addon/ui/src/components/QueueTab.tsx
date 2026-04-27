import { useMemo, useState } from 'react';
import { Calendar, Clock, History as HistoryIcon, Pin } from 'lucide-react';
import { classifyTrigger, getTriggerBadge } from '@/utils/trigger';
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
import { SortHeader, getAriaSort } from './ui/sort-header';
import { fmtDateTime, fmtDuration, fmtTimeOfDay, formatCronHuman, getJobBadge, stripYaml, timeAgo, isJobSuccessful, isJobInProgress, isJobFailed, isJobFinished, isJobRetryable, usePersistedState } from '../utils';
import { useVersioningEnabled } from '../hooks/useVersioning';
import { formatSelectionReason } from '../utils/selectionReason';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from './ui/dropdown-menu';
import { FirmwareDownloadMenu } from './FirmwareDownloadMenu';
import { QueueHistoryDialog } from './QueueHistoryDialog';
import { TagChips } from './ui/tag-chips';

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
  /** Bug 20: click on the Queue's Commit-column hash opens the History
   * panel preset to from=config_hash, to=Current. Same flow as the
   * Log modal's "Diff since compile" button. */
  onOpenHistoryDiff: (target: string, fromHash: string) => void;
  /** TG.9: BLOCKED-badge click opens the routing-rules editor with the
   *  offending rule pre-selected. The Queue passes
   *  ``job.blocked_reason.rule_id`` (empty string if the reason
   *  surfaces a synthetic combined-rules placeholder). */
  onOpenRoutingRule: (ruleId: string) => void;
}

const STATE_ORDER: Record<string, number> = {
  working: 0,
  pending: 1,
  // TG.9: BLOCKED sorts adjacent to pending — same "in-flight, not yet
  // claimed" position in the queue, but with a distinct red-orange
  // badge so the user notices the constraint.
  blocked: 1.5,
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
  onOpenHistoryDiff,
  onOpenRoutingRule,
}: Props) {
  // QS.27: persist sort across reloads via localStorage.
  const [sorting, setSorting] = usePersistedState<SortingState>(
    'queue-sort',
    [{ id: 'state', desc: false }],
  );
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [filter, setFilter] = useState('');
  // JH.7: fleet-wide history modal open state.
  const [historyOpen, setHistoryOpen] = useState(false);
  // #71: lift the Download dropdown's open state out of the row cell so
  // it survives the 1 Hz SWR poll. TanStack Table re-instantiates column
  // cells on data change, and any state kept inside the `<DropdownMenu>`
  // would be torn down mid-click. Keyed by job id so only one dropdown
  // is open at a time. Same pattern we used for the Devices-tab
  // hamburger in #2 (1.4.1-dev.3) — see Design Judgment in CLAUDE.md.
  const [downloadMenuOpenJobId, setDownloadMenuOpenJobId] = useState<string | null>(null);
  // Bug #112: hide the "Commit" column entirely when versioning is off.
  // The column renders short git hashes that are clickable links into the
  // History drawer — both are meaningless when there's no history to link
  // to, so drop the whole column rather than show a full column of dashes.
  const versioningEnabled = useVersioningEnabled();

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
        // TG.9: when the job is BLOCKED, render the badge as a button
        // that opens the routing-rules editor pre-selected to the rule
        // that fired. Tooltip surfaces the reason inline so a hover
        // tells the user *why* this isn't running yet.
        if (job.state === 'blocked' && job.blocked_reason) {
          const r = job.blocked_reason;
          const tooltip = `Blocked by rule '${r.rule_name}' — no online worker matches ${r.summary}. Click to edit the rule.`;
          return (
            <button
              type="button"
              className={`${badgeCls} cursor-pointer hover:brightness-125`}
              title={tooltip}
              aria-label={tooltip}
              onClick={() => onOpenRoutingRule(r.rule_id)}
            >
              {badgeLabel}
            </button>
          );
        }
        return (
          <span className="inline-flex items-center gap-1.5">
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
    // Bug #101: merged Worker + Routing column. Top line shows where the
    // job landed (assigned hostname, slot, scheduled/pinned icons); bottom
    // line shows the routing intent the user picked in the Upgrade modal
    // (any worker / pinned worker / tag expression). Two surfaces read as
    // one cell so a glance answers both "where did it go?" and "why?".
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
        // UX.6: render the slot as a second, muted line beneath the
        // hostname (never glued with `/N` — that reads like "version N"
        // or "retry N" to new users). `showSlot` stays guarded by
        // multi-slot workers only; single-slot workers get just the
        // hostname.
        const slotTotal = assignedClient?.max_parallel_jobs || 1;
        const showSlot = baseHostname && job.worker_id != null && slotTotal > 1;

        const pinnedHostname = pinnedClient?.hostname || job.assigned_hostname;
        const showPinnedHint =
          pinnedHostname && job.pinned_client_id && job.state === 'pending';

        // Routing intent line (was the standalone Routing column before
        // bug #101). Suppressed for the unconstrained case so the cell
        // doesn't grow a line for every row — "Any worker" is the
        // implicit default and the absence of a constraint reads cleaner
        // than an italic placeholder. Pin/tag constraints render below.
        const filter = job.worker_tag_filter;
        const hasTagFilter = !!filter && filter.tags.length > 0;
        let intentLine: React.ReactNode = null;
        if (job.pinned_client_id) {
          intentLine = (
            <span
              className="text-[10px] text-[var(--text-muted)]"
              title="Pinned to a specific worker via the Upgrade modal — only that worker can claim this job."
            >
              specific worker
            </span>
          );
        } else if (hasTagFilter) {
          const opLabel = filter!.op === 'all_of' ? 'all of' : filter!.op === 'any_of' ? 'any of' : 'none of';
          intentLine = (
            <span
              className="inline-flex items-center gap-1 text-[10px] text-[var(--text-muted)]"
              title={`Worker tag expression — only workers whose tags satisfy "${opLabel} ${filter!.tags.join(', ')}" can claim this job.`}
            >
              <span>{opLabel}</span>
              <TagChips tags={filter!.tags} />
            </span>
          );
        }

        // #17: pushpin icon when the user explicitly pinned the job to a
        // specific worker (UpgradeModal worker selector). Visible on every
        // pinned row regardless of state, so the user can audit history.
        return (
          <span className="text-[12px] inline-flex items-start gap-1">
            {job.scheduled && (
              <span
                title={job.schedule_kind === 'once' ? 'Triggered by one-time schedule' : 'Triggered by recurring schedule'}
                className="inline-flex text-[var(--accent)] mt-[2px]"
              >
                {job.schedule_kind === 'once'
                  ? <Calendar className="size-3" aria-label="one-time scheduled run" />
                  : <Clock className="size-3" aria-label="recurring scheduled run" />}
              </span>
            )}
            {job.pinned_client_id && (
              <span
                title={
                  pinnedHostname
                    ? `Pinned to ${pinnedHostname} via Upgrade modal`
                    : 'Pinned to a specific worker via Upgrade modal'
                }
                className="inline-flex text-[var(--accent)] mt-[2px]"
              >
                <Pin className="size-3" aria-label="pinned to specific worker" />
              </span>
            )}
            <span>
              {baseHostname || '—'}
              {showSlot && (
                <>
                  <br />
                  <span
                    className="text-[10px] text-[var(--text-muted)]"
                    title={`Build slot ${job.worker_id} of ${slotTotal} on this worker.`}
                  >
                    slot {job.worker_id}
                  </span>
                </>
              )}
              {showPinnedHint && !job.assigned_hostname && (
                <><br /><span className="text-[10px] text-[var(--text-muted)]">→ {pinnedHostname}</span></>
              )}
              {intentLine && <><br />{intentLine}</>}
            </span>
          </span>
        );
      },
      sortingFn: 'alphanumeric',
    }),
    // #17: ESPHome version column. Shows the version stamped on each job,
    // which may differ from the global default when the user picked a
    // non-default in the Upgrade modal. Bug #29: header is "ESPHome" so
    // Devices / Schedules / Queue all use the same disambiguating label.
    columnHelper.accessor(row => row.esphome_version || '', {
      id: 'esphome_version',
      header: ({ column }) => <SortHeader label="ESPHome" column={column} />,
      cell: ({ row: { original: job } }) => {
        const target = targets.find(t => t.target === job.target);
        const isPinned = target?.pinned_version && target.pinned_version === job.esphome_version;
        return (
          <span className="text-[12px]">
            {job.esphome_version || <span className="text-[var(--text-muted)]">—</span>}
            {isPinned && (
              <span title={`Pinned ESPHome version: ${target.pinned_version}`} className="ml-1 inline-flex align-text-bottom">
                <Pin className="size-3" aria-label="Pinned ESPHome version" />
              </span>
            )}
          </span>
        );
      },
      sortingFn: 'alphanumeric',
    }),
    // Bug #8 (1.6.1): surface the worker-selection reason so a user
    // can answer "why did THIS worker get the job" without reading
    // the server log. Short label with hover-explanation; dash for
    // jobs that predate the column.
    columnHelper.accessor(row => row.selection_reason || '', {
      id: 'selection_reason',
      header: ({ column }) => <SortHeader label="Worker selection" column={column} />,
      cell: ({ row: { original: job } }) => {
        const display = formatSelectionReason(job.selection_reason);
        if (!display) return <span className="text-[var(--text-muted)] text-[12px]">—</span>;
        return (
          <span
            className="text-[11px] text-[var(--text-muted)] whitespace-nowrap"
            title={display.title}
          >
            {display.label}
          </span>
        );
      },
      sortingFn: 'alphanumeric',
    }),
    // Bug 18: surface the git hash the config was at when this job
    // was enqueued (AV.7's config_hash). Short hash rendered in a
    // muted mono font; hover shows the full SHA. Dash for jobs
    // that predate AV.7 or were enqueued while /config/esphome/
    // wasn't a git repo.
    // Bug #112: omitted entirely when versioning is off.
    ...(versioningEnabled ? [columnHelper.accessor(row => row.config_hash || '', {
      id: 'config_hash',
      header: ({ column }) => <SortHeader label="Commit" column={column} />,
      cell: ({ row: { original: job } }) => {
        if (!job.config_hash) {
          return <span className="text-[var(--text-muted)] text-[12px]">—</span>;
        }
        // Bug 20: clickable hash opens the History panel preset to
        // diff-since-this-compile (from=config_hash, to=Current).
        return (
          <button
            type="button"
            className="font-mono text-[11px] text-[var(--text-muted)] underline-offset-2 hover:underline cursor-pointer"
            title={`Config git HEAD at compile time: ${job.config_hash}\nClick to see what's changed since this compile.`}
            onClick={() => onOpenHistoryDiff(job.target, job.config_hash as string)}
          >
            {job.config_hash.slice(0, 7)}
          </button>
        );
      },
      sortingFn: 'alphanumeric',
    })] : []),
    // #21/#92 + UX.5: triggered-by column — recurring schedule, one-time, or
    // manual. Recurring/once rows look up the parent target's cron / one-time
    // timestamp and render an inline "@ HH:MM" or "@ YYYY-MM-DD HH:MM" affix.
    // Hover reveals the full cron expression + tz so users can reconcile with
    // the Schedules tab.
    // #65: shared trigger-badge helper (utils/trigger.tsx) returns the
    // icon + label used on BOTH Queue and Compile-History surfaces —
    // used to drift ("HA action" here vs "HA" there). Queue still adds
    // the cron-string detail after the badge for scheduled jobs so the
    // operator can reconcile against the Schedules tab.
    columnHelper.accessor(
      row => classifyTrigger(row),
      {
      id: 'triggered_by',
      header: ({ column }) => <SortHeader label="Triggered" column={column} />,
      cell: ({ row: { original: job } }) => {
        const badge = getTriggerBadge(job);
        // Scheduled rows keep their cron/once detail as a secondary
        // muted suffix — "Once @ 2026-04-21 14:00" / "Recurring · every Sunday at 2am".
        if (job.scheduled && job.schedule_kind === 'once') {
          const target = targets.find(t => t.target === job.target);
          const when = target?.schedule_once;
          const pretty = when ? fmtDateTime(new Date(when), { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : null;
          return (
            <span
              className="inline-flex items-center gap-1 text-[12px]"
              title={when ? `Triggered by one-time schedule fired at ${when}` : badge.title}
            >
              {badge.icon}
              {pretty ? <>{badge.label} <span className="text-[var(--text-muted)]">@ {pretty}</span></> : badge.label}
            </span>
          );
        }
        if (job.scheduled) {
          const target = targets.find(t => t.target === job.target);
          const cron = target?.schedule;
          const tz = target?.schedule_tz;
          const human = formatCronHuman(cron);
          const tipParts: string[] = [badge.title];
          if (cron) tipParts.push(`cron: ${cron}`);
          if (tz) tipParts.push(`tz: ${tz}`);
          return (
            <span className="inline-flex items-center gap-1 text-[12px]" title={tipParts.join(' · ')}>
              {badge.icon}
              {human ? <>{badge.label} <span className="text-[var(--text-muted)]">· {human}</span></> : badge.label}
            </span>
          );
        }
        return (
          <span className="inline-flex items-center gap-1 text-[12px]" title={badge.title}>
            {badge.icon} {badge.label}
          </span>
        );
      },
      sortingFn: 'alphanumeric',
    }),
    columnHelper.accessor(row => new Date(row.created_at), {
      id: 'created_at',
      header: ({ column }) => <SortHeader label="Start Time" column={column} />,
      cell: ({ row: { original: job } }) => {
        const d = new Date(job.created_at);
        const time = fmtTimeOfDay(d);
        return (
          <span className="text-[12px]" title={fmtDateTime(d)}>
            {time}
            <div className="text-[10px] text-[var(--text-muted)]">{timeAgo(job.created_at)}</div>
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
          return <span className="text-[12px] text-[var(--text-muted)] italic">Elapsed {elapsed}</span>;
        }
        if (!job.finished_at) return <span className="text-[12px]">—</span>;
        const finished = new Date(job.finished_at);
        const time = fmtTimeOfDay(finished);
        // Duration = wall clock from enqueue to finish, not just worker compile time
        const wallSeconds = (finished.getTime() - new Date(job.created_at).getTime()) / 1000;
        const dur = wallSeconds >= 0 ? fmtDuration(wallSeconds) : null;
        return (
          <span className="text-[12px]" title={fmtDateTime(finished)}>
            {time}
            {dur && <div className="text-[10px] text-[var(--text-muted)]">Took {dur}</div>}
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
        // SP.2: log isn't carried in the queue list response anymore. Show the
        // Log button for any non-pending job — terminal jobs lazy-load the log
        // via /ui/api/jobs/{id}/log when the modal opens.
        const hasLog = job.state !== 'pending';
        const canRetry = isJobRetryable(job);
        const canCancel = inProgress;
        // FD.8 / #69: Download dropdown offers each stored firmware
        // variant (factory for ESP32 first-flash; ota for OTA / ESP8266)
        // plus a gzip toggle. Fallback to a single-item variants=["firmware"]
        // list for pre-#69 blobs still on disk after an upgrade.
        // Bug #9 (1.6.1): the worker now archives every successful
        // compile on the server, so the Download button is no longer
        // gated on ``download_only`` — any successful compile with a
        // stored binary can offer Download in the live Queue too.
        const canDownload = job.state === 'success' && !!job.has_firmware;
        const variants = (job.firmware_variants && job.firmware_variants.length > 0)
          ? job.firmware_variants
          : (canDownload ? ['firmware'] : []);
        return (
          <div className="flex gap-1">
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
            {canDownload && variants.length > 0 && (
              <FirmwareDownloadMenu
                jobId={job.id}
                variants={variants}
                open={downloadMenuOpenJobId === job.id}
                onOpenChange={(open) => setDownloadMenuOpenJobId(open ? job.id : null)}
              />
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
  ], [workers, onCancel, onRetry, onClear, onOpenLog, onEdit, onOpenHistoryDiff, onOpenRoutingRule, targetNameMap, downloadMenuOpenJobId, versioningEnabled]);

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

  function handleClearSelected() {
    if (selectedIds.length > 0) onClear(selectedIds);
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
            {/* Retry dropdown — UX.4: rerun-class actions use the green
                success colors (same as per-row Retry/Rerun buttons).
                Orange/amber is reserved for genuine warn states. */}
            <DropdownMenu>
              <DropdownMenuTrigger className="inline-flex items-center gap-1 rounded-lg border border-transparent bg-[#14532d] px-2.5 h-7 text-[0.8rem] font-medium text-[#4ade80] hover:bg-[#166534] cursor-pointer">
                Retry <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                  <DropdownMenuItem
                    onClick={onRetryAllFailed}
                    disabled={!hasFailedJobs}
                    title={!hasFailedJobs ? 'No failed jobs in the current queue' : undefined}
                  >
                    Retry All Failed
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={handleRetrySelected}
                    disabled={queue.length === 0}
                    title={queue.length === 0 ? 'Queue is empty' : undefined}
                  >
                    Retry Selected
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={handleCancelSelected}
                    disabled={queue.length === 0}
                    title={queue.length === 0 ? 'Queue is empty' : undefined}
                  >
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
                  <DropdownMenuItem
                    onClick={handleClearSelected}
                    disabled={selectedIds.length === 0}
                    title={selectedIds.length === 0 ? 'Select one or more rows to clear' : undefined}
                  >
                    Clear Selected
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={onClearSucceeded}
                    disabled={!hasSuccessfulJobs}
                    title={!hasSuccessfulJobs ? 'No succeeded jobs to clear' : undefined}
                  >
                    Clear Succeeded
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={onClearFinished}
                    disabled={!hasFinishedJobs}
                    title={!hasFinishedJobs ? 'No finished jobs to clear' : undefined}
                  >
                    Clear All Finished
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={onClearAll}
                    disabled={queue.length === 0}
                    title={queue.length === 0 ? 'Queue is empty' : undefined}
                  >
                    Clear Entire Queue
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>

            {/* #67: History button anchors to the far right of the
                toolbar with a visible outline. Look-back action, not a
                mutating one — ``outline`` variant picks up an actual
                ``border-border`` class (``secondary`` didn't) so the
                button reads as a tappable surface rather than a
                link-styled blob. */}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setHistoryOpen(true)}
              title="Browse persistent compile history for the whole fleet"
            >
              <HistoryIcon className="size-3.5" aria-hidden="true" />
              History
            </Button>
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

      {/* JH.7: fleet-wide history modal — mounted once; SWR gates on `open`. */}
      <QueueHistoryDialog
        open={historyOpen}
        onOpenChange={setHistoryOpen}
        targets={targets}
        onOpenHistoryDiff={onOpenHistoryDiff}
      />
    </div>
  );
}
