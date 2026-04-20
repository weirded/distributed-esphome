import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
  type SortingState,
} from '@tanstack/react-table';
import { ChevronDown, ChevronRight, History as HistoryIcon } from 'lucide-react';

import {
  getJobHistory,
  type JobHistoryEntry,
} from '@/api/client';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { SortHeader, getAriaSort } from '@/components/ui/sort-header';
import type { Target } from '@/types';
import { fmtDuration, fmtEpochAbsolute, fmtEpochRelative } from '@/utils/format';
import { getJobBadge } from '@/utils/jobState';
import { renderAnsi } from '@/utils/ansi';
import { TimeRangePicker, type TimeRange } from './TimeRangePicker';


// JH.7 / bugs #40, #42-54: fleet-wide compile history modal.
//
// Opened from the Queue tab toolbar. Reads from /ui/api/history;
// server-side filters + sorting; client-side text search; infinite
// scroll. Read-only — no Retry / Cancel / Clear / Download live here,
// those belong on the live Queue tab.


interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  targets: Target[];
  /**
   * Bug #41: click on a commit-hash cell opens the AV.6 History panel
   * preset to ``from = hash, to = Current``.
   */
  onOpenHistoryDiff?: (target: string, fromHash: string) => void;
}


const PAGE_SIZE = 100;

type StateFilter = '' | 'success' | 'failed' | 'timed_out' | 'cancelled';

type SortColumn =
  | 'finished_at' | 'started_at' | 'submitted_at' | 'duration_seconds'
  | 'target' | 'state' | 'esphome_version' | 'assigned_hostname' | 'triggered_by';

const SORTABLE: Record<string, SortColumn> = {
  target: 'target',
  state: 'state',
  esphome_version: 'esphome_version',
  duration_seconds: 'duration_seconds',
  // #93: the "Started" column now reads ``submitted_at`` (user
  // submission time). Server-side `_SORT_COLUMNS` already accepts
  // ``submitted_at`` as a whitelisted sort key.
  submitted_at: 'submitted_at',
  finished_at: 'finished_at',
  triggered_by: 'triggered_by',
  assigned_hostname: 'assigned_hostname',
};


// #65: Triggered column rendering is now shared with the Queue tab —
// same icons + same labels — via getTriggerBadge(). The inline
// ``triggeredLabel()`` helper this file carried before drifted from
// the Queue's renderer (plain text "HA" / "User" / "Scheduled·1x"
// vs Queue's rich icon+label badges); unifying them kills the drift.
import { getTriggerBadge, isScheduledCancelBeforeStart } from '@/utils/trigger';
import { useVersioningEnabled } from '@/hooks/useVersioning';
import { FirmwareDownloadMenu } from './FirmwareDownloadMenu';
import { formatSelectionReason } from '@/utils/selectionReason';

function friendlyFor(targets: Target[], filename: string): string {
  const t = targets.find((x) => x.target === filename);
  return t?.friendly_name || t?.device_name || filename;
}


export function QueueHistoryDialog({ open, onOpenChange, targets, onOpenHistoryDiff }: Props) {
  // Bug #49: single combined time-range picker (no separate preset pill
  // + datetime-local). Remembers which preset produced the current range
  // so the trigger button can label "Last 7 days" instead of a raw epoch
  // pair. Null label means "custom" or "all time".
  const [range, setRange] = useState<TimeRange>(() => {
    // Default to the common "Last 30 days".
    return { since: Math.floor(Date.now() / 1000) - 30 * 86_400, until: null };
  });
  const [presetLabel, setPresetLabel] = useState<string | null>('Last 30 days');
  // Bug #112: drop the Commit column entirely when versioning is off.
  const versioningEnabled = useVersioningEnabled();
  // Bug #1: per-row Download-menu open state, lifted to the dialog so
  // SWR doesn't tear it down on re-render. Keyed by job id; null = no
  // menu open.
  const [downloadMenuOpenId, setDownloadMenuOpenId] = useState<string | null>(null);

  const [stateFilter, setStateFilter] = useState<StateFilter>('');
  const [q, setQ] = useState('');

  // Bug #53: TanStack-style server-side sorting. Default: newest first.
  const [sorting, setSorting] = useState<SortingState>([{ id: 'finished_at', desc: true }]);

  // Bug #46: infinite-scroll accumulator.
  const [pages, setPages] = useState<JobHistoryEntry[][]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // When the filter or sort changes, wipe the accumulator so the next
  // fetch starts clean.
  const filtersKey = useMemo(
    () => `${range.since ?? ''}|${range.until ?? ''}|${stateFilter}|${JSON.stringify(sorting)}`,
    [range, stateFilter, sorting],
  );
  useEffect(() => {
    if (!open) return;
    setPages([]);
    setHasMore(true);
    setError(null);
    setExpandedId(null);
  }, [filtersKey, open]);

  useEffect(() => {
    if (!open) {
      setPages([]);
      setExpandedId(null);
    }
  }, [open]);

  const fetchNextPage = useCallback(async () => {
    if (loading || !hasMore || !open) return;
    setLoading(true);
    try {
      const offset = pages.length * PAGE_SIZE;
      const sortSpec = sorting[0];
      const rows = await getJobHistory({
        state: (stateFilter || undefined) as JobHistoryEntry['state'] | undefined,
        since: range.since ?? undefined,
        until: range.until ?? undefined,
        limit: PAGE_SIZE,
        offset,
        sort: (sortSpec && SORTABLE[sortSpec.id]) || 'finished_at',
        desc: sortSpec ? sortSpec.desc : true,
      });
      setPages((prev) => [...prev, rows]);
      if (rows.length < PAGE_SIZE) setHasMore(false);
    } catch (e) {
      setError(e as Error);
    } finally {
      setLoading(false);
    }
  }, [loading, hasMore, open, pages.length, sorting, stateFilter, range.since, range.until]);

  // First load on open / filter-change.
  useEffect(() => {
    if (!open) return;
    if (pages.length === 0 && hasMore && !loading) {
      void fetchNextPage();
    }
  }, [open, pages.length, hasMore, loading, fetchNextPage]);

  // Bug #40: client-side text search across all textual columns. Runs
  // on top of the server-filtered page set.
  const flatRows = useMemo(() => {
    const all = pages.flat();
    const needle = q.trim().toLowerCase();
    if (!needle) return all;
    return all.filter((r) => rowMatchesSearch(r, needle, targets));
  }, [pages, q, targets]);

  // Bug #46: IntersectionObserver sentinel for infinite scroll.
  const sentinelRef = useRef<HTMLTableRowElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) void fetchNextPage();
    }, { rootMargin: '200px' });
    obs.observe(el);
    return () => obs.disconnect();
  }, [open, pages, hasMore, loading, fetchNextPage]);

  // Bug #53: TanStack column defs — all sortable columns use SortHeader.
  // Columns marked sortable: target, state, ESPHome, duration, started,
  // finished, trigger, worker. Commit-hash column stays non-sortable
  // (it's a commit SHA, which has no meaningful sort order).
  const columns = useMemo(() => {
    const ch = createColumnHelper<JobHistoryEntry>();
    return [
      ch.display({
        id: 'expand',
        header: () => null,
        cell: ({ row: { original: r } }) => {
          const hasExcerpt = !!r.log_excerpt;
          if (!hasExcerpt) return null;
          return expandedId === r.id
            ? <ChevronDown className="size-3.5 text-[var(--text-muted)]" />
            : <ChevronRight className="size-3.5 text-[var(--text-muted)]" />;
        },
      }),
      ch.accessor((r) => friendlyFor(targets, r.target), {
        id: 'target',
        header: ({ column }) => <SortHeader label="Device" column={column} />,
        cell: ({ row: { original: r } }) => {
          const friendly = friendlyFor(targets, r.target);
          return (
            <span title={r.target}>
              {friendly}
              {friendly !== r.target && (
                <span className="ml-1 text-[10px] text-[var(--text-muted)]">{r.target}</span>
              )}
            </span>
          );
        },
      }),
      ch.accessor('state', {
        id: 'state',
        header: ({ column }) => <SortHeader label="State" column={column} />,
        cell: ({ row: { original: r } }) => {
          const badge = getJobBadge({
            state: r.state,
            ota_result: r.ota_result ?? undefined,
            validate_only: !!r.validate_only,
            download_only: !!r.download_only,
          });
          return <span className={badge.cls}>{badge.label}</span>;
        },
      }),
      ch.accessor((r) => r.esphome_version ?? '', {
        id: 'esphome_version',
        header: ({ column }) => <SortHeader label="ESPHome" column={column} />,
        cell: ({ row: { original: r } }) => r.esphome_version || '—',
      }),
      // Bug #112: Commit column only included when versioning is on —
      // otherwise every row would be a dash.
      ...(versioningEnabled ? [ch.display({
        id: 'commit',
        header: 'Commit',
        cell: ({ row: { original: r } }) => {
          if (!r.config_hash) return <span className="text-[var(--text-muted)]">—</span>;
          if (!onOpenHistoryDiff) {
            return <span title={r.config_hash}>{r.config_hash.slice(0, 7)}</span>;
          }
          return (
            <button
              type="button"
              className="underline-offset-2 hover:underline cursor-pointer text-[var(--text-muted)]"
              title={`Diff since this compile: ${r.config_hash}`}
              onClick={(e) => { e.stopPropagation(); onOpenHistoryDiff(r.target, r.config_hash!); }}
            >
              {r.config_hash.slice(0, 7)}
            </button>
          );
        },
      })] : []),
      ch.accessor((r) => r.duration_seconds ?? 0, {
        id: 'duration_seconds',
        header: ({ column }) => <SortHeader label="Duration" column={column} />,
        cell: ({ row: { original: r } }) => {
          // #83: scheduled+cancelled-before-start rows didn't exist
          // for any wall-clock duration worth reporting. Don't
          // pretend with a ``—`` — the trigger column already
          // carries the full story.
          if (isScheduledCancelBeforeStart(r)) {
            return <span className="text-[var(--text-muted)]">—</span>;
          }
          return (
            <span
              className="tabular-nums"
              title={
                r.started_at == null
                  ? 'Queue-time only (job never reached a worker)'
                  : undefined
              }
            >
              {fmtDuration(r.duration_seconds)}
            </span>
          );
        },
      }),
      // #93: "Started" now means "when the user / scheduler / API
      // submitted the job" (= submitted_at on the DB side, = job
      // created_at on the Job model). The previous wiring pointed at
      // ``assigned_at`` (worker pickup) which read as "not started"
      // for any row where a worker never claimed it — nonsensical on
      // a finished row. Worker-pickup time is still shown in the
      // tooltip for anyone who needs it.
      ch.accessor((r) => r.submitted_at ?? 0, {
        id: 'submitted_at',
        header: ({ column }) => <SortHeader label="Started" column={column} />,
        cell: ({ row: { original: r } }) => {
          const tooltip = r.started_at
            ? `Submitted: ${fmtEpochAbsolute(r.submitted_at)}\nWorker picked up: ${fmtEpochAbsolute(r.started_at)}`
            : `Submitted: ${fmtEpochAbsolute(r.submitted_at)}\n(No worker picked up this job — cancelled or rejected before start.)`;
          return (
            <span className="text-[var(--text-muted)] tabular-nums" title={tooltip}>
              {r.submitted_at ? fmtEpochRelative(r.submitted_at) : '—'}
            </span>
          );
        },
      }),
      ch.accessor((r) => r.finished_at ?? 0, {
        id: 'finished_at',
        header: ({ column }) => <SortHeader label="Finished" column={column} />,
        cell: ({ row: { original: r } }) => (
          <span className="text-[var(--text-muted)] tabular-nums" title={fmtEpochAbsolute(r.finished_at)}>
            {fmtEpochRelative(r.finished_at)}
          </span>
        ),
      }),
      ch.accessor((r) => getTriggerBadge(r).label, {
        id: 'triggered_by',
        // #65: header matches the Queue tab's "Triggered" (was "Trigger"
        // here, which was an inconsistency the user called out).
        header: ({ column }) => <SortHeader label="Triggered" column={column} />,
        cell: ({ row: { original: r } }) => {
          const b = getTriggerBadge(r);
          // #83: annotate scheduled-cancelled-before-start so the
          // row reads as an intentional outcome instead of a ghost.
          const cancelled = isScheduledCancelBeforeStart(r);
          return (
            <span className="inline-flex items-center gap-1 text-[12px]" title={cancelled ? 'Scheduler fired, but the job was cancelled before any worker picked it up.' : b.title}>
              {b.icon} {b.label}
              {cancelled && (
                <span className="text-[var(--text-muted)]"> — cancelled before start</span>
              )}
            </span>
          );
        },
      }),
      ch.accessor((r) => r.assigned_hostname ?? '', {
        id: 'assigned_hostname',
        header: ({ column }) => <SortHeader label="Worker" column={column} />,
        cell: ({ row: { original: r } }) => {
          // #83: no worker ever held this row — the absence is the
          // point. Drop the em-dash placeholder.
          if (isScheduledCancelBeforeStart(r)) {
            return <span className="text-[var(--text-muted)]" />;
          }
          return (
            <span className="text-[var(--text-muted)] truncate max-w-[140px]" title={r.assigned_hostname ?? undefined}>
              {r.assigned_hostname || '—'}
            </span>
          );
        },
      }),
      // Bug #8 (1.6.1): selection-reason column — explains why a row's
      // Worker was the one that picked up the compile. Sits next to
      // the Worker column on purpose; a reader scans left→right and
      // gets "worker X, because Y" in one glance.
      ch.accessor((r) => r.selection_reason ?? '', {
        id: 'selection_reason',
        header: ({ column }) => <SortHeader label="Why" column={column} />,
        cell: ({ row: { original: r } }) => {
          const display = formatSelectionReason(r.selection_reason);
          if (!display) return <span className="text-[var(--text-muted)]">—</span>;
          return (
            <span
              className="text-[11px] text-[var(--text-muted)] whitespace-nowrap"
              title={display.title}
            >
              {display.label}
            </span>
          );
        },
      }),
      // Bug #1 (1.6.1): firmware download dropdown on rows whose binary
      // is still on disk. Column is always present (no header text, just
      // a narrow icon-sized cell) so row heights stay consistent as
      // firmwares age out under the retention budget.
      ch.display({
        id: 'download',
        header: '',
        cell: ({ row: { original: r } }) => {
          const variants = r.firmware_variants ?? [];
          if (variants.length === 0) return null;
          return (
            <FirmwareDownloadMenu
              jobId={r.id}
              variants={variants}
              open={downloadMenuOpenId === r.id}
              onOpenChange={(o) => setDownloadMenuOpenId(o ? r.id : null)}
              size="icon"
              label="Download firmware"
            />
          );
        },
      }),
    ];
  }, [targets, onOpenHistoryDiff, expandedId, versioningEnabled, downloadMenuOpenId]);

  const table = useReactTable({
    data: flatRows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    manualSorting: true,  // Bug #53: sorting happens on the server.
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Bug #50: dialog-xl fills the viewport (calc(100vw - 6rem) ×
          calc(100dvh - 6rem)). Flex column so the sticky footer stays
          at the bottom even on short result sets (bug #45). */}
      <DialogContent className="dialog-xl" style={{ display: 'flex', flexDirection: 'column' }}>
        <DialogHeader>
          <DialogTitle>
            <span className="inline-flex items-center gap-2">
              <HistoryIcon className="size-4 text-[var(--text-muted)]" />
              Compile History
            </span>
          </DialogTitle>
        </DialogHeader>

        {/* Filter toolbar */}
        <div className="flex flex-wrap items-center gap-2 px-4 pt-2 pb-3 text-[12px] shrink-0">
          <label className="inline-flex items-center gap-1 text-[var(--text-muted)]">
            <span>State:</span>
            <select
              className="rounded-md border border-[var(--border)] bg-[var(--surface2)] px-2 py-0.5 text-[12px] text-[var(--text)] outline-none focus:border-[var(--accent)] cursor-pointer"
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value as StateFilter)}
            >
              <option value="">All states</option>
              <option value="success">Success</option>
              <option value="failed">Failed</option>
              <option value="timed_out">Timed out</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </label>

          <TimeRangePicker
            value={range}
            activePresetLabel={presetLabel}
            onChange={(r, label) => {
              setRange(r);
              setPresetLabel(label);
            }}
          />

          <div className="flex-1" />
          <Input
            type="search"
            placeholder="Search device, version, worker, hash, log…"
            className="h-7 w-[280px] text-[12px]"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-y-auto border-t border-[var(--border)]">
          {error && (
            <div className="m-3 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-400">
              Failed to load history: {error.message}
            </div>
          )}

          {flatRows.length === 0 && !loading && (
            <div className="p-6 text-center text-xs text-[var(--text-muted)]">
              No history matches the current filters.
            </div>
          )}

          {/* Bug #52: use the app's default (sans) font for table cells.
              Only commit-hash + ESPHome version get tabular-nums via
              column-level class; the table no longer force-applies
              ``font-mono`` globally. */}
          {flatRows.length > 0 && (
            <table className="w-full text-[13px]">
              <thead className="sticky top-0 bg-[var(--surface2)] text-[11px] text-[var(--text-muted)]">
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id}>
                    {hg.headers.map((h) => (
                      <th
                        key={h.id}
                        className="px-2 py-1.5 text-left font-normal"
                        aria-sort={h.column.getCanSort() ? getAriaSort(h.column) : undefined}
                      >
                        {h.isPlaceholder ? null : flexRender(h.column.columnDef.header, h.getContext())}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((row) => {
                  const r = row.original;
                  const hasExcerpt = !!r.log_excerpt;
                  const expanded = expandedId === r.id;
                  return (
                    <>
                      <tr
                        key={row.id}
                        className={`border-t border-[var(--border)] ${hasExcerpt ? 'cursor-pointer hover:bg-[var(--surface2)]' : ''}`}
                        onClick={hasExcerpt ? () => setExpandedId((p) => (p === r.id ? null : r.id)) : undefined}
                      >
                        {row.getVisibleCells().map((cell) => (
                          <td key={cell.id} className="px-2 py-1.5">
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        ))}
                      </tr>
                      {expanded && hasExcerpt && (
                        <tr className="bg-[var(--surface2)]">
                          <td />
                          <td colSpan={columns.length - 1} className="px-2 pb-3 pt-1">
                            {/* Bug #51: ANSI-aware log rendering with `\r`
                                progress-bar semantics (see utils/ansi.tsx). */}
                            <pre className="overflow-auto text-[11px] leading-snug font-mono text-[var(--text)] max-h-[360px] whitespace-pre-wrap break-words">
                              {renderAnsi(r.log_excerpt ?? '')}
                            </pre>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
                {hasMore && (
                  <tr ref={sentinelRef}>
                    <td colSpan={columns.length} className="px-2 py-3 text-center text-[11px] text-[var(--text-muted)]">
                      {loading ? 'Loading…' : ''}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        {/* Bug #45: sticky summary footer glued to the bottom edge. */}
        <div className="shrink-0 border-t border-[var(--border)] bg-[var(--surface)] px-4 py-2 text-[11px] text-[var(--text-muted)]">
          {flatRows.length === 0
            ? (loading ? 'Loading…' : 'No rows')
            : `Showing ${flatRows.length} row${flatRows.length === 1 ? '' : 's'}${hasMore ? '' : ' (end of history)'}`}
        </div>
      </DialogContent>
    </Dialog>
  );
}


// --------------------------------------------------------------------- //

function rowMatchesSearch(row: JobHistoryEntry, q: string, targets: Target[]): boolean {
  if (!q) return true;
  const needle = q.toLowerCase();
  const fields: (string | null | undefined)[] = [
    row.target,
    friendlyFor(targets, row.target),
    row.state,
    row.esphome_version,
    row.config_hash,
    row.assigned_hostname,
    row.assigned_client_id,
    row.triggered_by,
    row.trigger_detail,
    row.ota_result,
    row.log_excerpt,
  ];
  return fields.some((f) => typeof f === 'string' && f.toLowerCase().includes(needle));
}
