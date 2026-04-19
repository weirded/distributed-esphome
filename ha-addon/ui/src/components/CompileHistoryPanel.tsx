import { useState } from 'react';
import useSWR from 'swr';
import { ChevronDown, ChevronRight, Clock, History as HistoryIcon } from 'lucide-react';

import {
  getJobHistory,
  getJobHistoryStats,
  type JobHistoryEntry,
  type JobHistoryStats,
} from '@/api/client';
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { getJobBadge } from '@/utils/jobState';
import { renderAnsi } from '@/utils/ansi';
import { fmtDuration, fmtEpochAbsolute, fmtEpochRelative } from '@/utils/format';
import { isScheduledCancelBeforeStart } from '@/utils/trigger';

// JH.5: per-device "Compile history" panel.
//
// Opens from the Devices-row hamburger menu. Backed by the persistent
// /ui/api/history table (JH.4) so the view survives queue coalescing +
// clears. Read-only — no Retry / Cancel here; those live in the live
// Queue tab where they apply to running state.
//
// Shape follows HistoryPanel's Sheet template so the two drawers feel
// like siblings: narrow sticky header, body scrolls. Rows are a compact
// table; click-to-expand reveals the stored log_excerpt (last ~2 KB,
// see ha-addon/server/job_history.py::LOG_EXCERPT_BYTES).

interface Props {
  /** Fully-qualified filename (e.g. "bedroom.yaml"). ``null`` = closed. */
  target: string | null;
  onOpenChange: (open: boolean) => void;
  /**
   * Bug #41: click on a commit-hash cell opens the AV.6 History panel
   * preset to ``from = hash, to = Current``. Lets the user jump from
   * "this compile ran at X" to "what's changed since then" with one
   * click, matching the Queue tab's Commit-column button.
   */
  onOpenHistoryDiff?: (target: string, fromHash: string) => void;
}

const PAGE_SIZE = 50;


// Bug #48: all formatting helpers live in utils/format.ts so this panel
// and QueueHistoryDialog agree on duration / relative-time rendering.
// No local copies here — removed to prevent drift.

function triggeredLabel(row: JobHistoryEntry): string {
  // #83: scheduled + cancelled-before-start deserves a clearer label
  // than "Scheduled (once)" — the whole row otherwise looks like
  // nothing happened.
  if (isScheduledCancelBeforeStart(row)) {
    return row.trigger_detail === 'once'
      ? 'Scheduled (once) — cancelled before start'
      : 'Scheduled — cancelled before start';
  }
  if (row.triggered_by === 'ha_action') return 'HA action';
  if (row.triggered_by === 'schedule') {
    return row.trigger_detail === 'once' ? 'Scheduled (once)' : 'Scheduled';
  }
  return 'User';
}

export function CompileHistoryPanel({ target, onOpenChange, onOpenHistoryDiff }: Props) {
  const open = target !== null;
  // Page offset for "Load more" — resets when the target changes.
  const [offset, setOffset] = useState(0);

  const historyKey = open ? ['jobHistory', target, offset] : null;
  const { data: rows, error, isLoading } = useSWR<JobHistoryEntry[]>(
    historyKey,
    () => getJobHistory({ target: target!, limit: PAGE_SIZE, offset }),
    { revalidateOnFocus: false },
  );

  // Separate stats fetch — cheap, single row, worth doing in parallel
  // so the header badges render without waiting for the full list.
  const statsKey = open ? ['jobHistoryStats', target] : null;
  const { data: stats } = useSWR<JobHistoryStats>(
    statsKey,
    () => getJobHistoryStats({ target: target!, window_days: 30 }),
    { revalidateOnFocus: false },
  );

  // Track which row's log excerpt is expanded (at most one at a time).
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Reset pagination + expanded state when the panel closes/reopens on
  // a different target. onOpenChange of false triggers this flow via
  // the parent setting `target` to null, remounting effectively.

  return (
    <Sheet
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          setOffset(0);
          setExpandedId(null);
        }
        onOpenChange(o);
      }}
    >
      <SheetContent className="!w-[min(760px,100vw)]">
        <SheetHeader>
          <div className="flex items-center gap-2">
            <HistoryIcon className="size-4 text-[var(--text-muted)]" />
            <SheetTitle>{target ?? 'Compile history'}</SheetTitle>
          </div>
        </SheetHeader>
        <SheetBody>
          {/* Stats pills — quick "what's this target's story" summary. */}
          {stats && stats.total > 0 && (
            <div className="mb-3 flex flex-wrap gap-2 text-[11px]">
              <StatPill label={`${stats.total} total`} />
              <StatPill label={`${stats.success} ok`} tone="success" />
              {stats.failed > 0 && <StatPill label={`${stats.failed} failed`} tone="error" />}
              {stats.timed_out > 0 && <StatPill label={`${stats.timed_out} timed out`} tone="warn" />}
              {stats.cancelled > 0 && <StatPill label={`${stats.cancelled} cancelled`} />}
              {stats.avg_duration_seconds != null && (
                <StatPill label={`avg ${fmtDuration(stats.avg_duration_seconds)}`} />
              )}
              <StatPill label={`last ${stats.window_days}d`} muted />
            </div>
          )}

          {error && (
            <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-400 mb-3">
              Failed to load history: {(error as Error).message}
            </div>
          )}

          {isLoading && !rows && (
            <div className="text-xs text-[var(--text-muted)]">Loading…</div>
          )}

          {rows && rows.length === 0 && offset === 0 && (
            <div className="text-xs text-[var(--text-muted)] py-6 text-center">
              No compile history yet — the first compile will appear here.
            </div>
          )}

          {rows && rows.length > 0 && (
            <div className="flex flex-col divide-y divide-[var(--border)] rounded-md border border-[var(--border)]">
              {rows.map((row) => (
                <HistoryRow
                  key={row.id}
                  row={row}
                  expanded={expandedId === row.id}
                  onToggle={() =>
                    setExpandedId((prev) => (prev === row.id ? null : row.id))
                  }
                  onOpenHistoryDiff={onOpenHistoryDiff}
                />
              ))}
            </div>
          )}

          {/* Paginate only when the last page was full. */}
          {rows && rows.length === PAGE_SIZE && (
            <div className="mt-3 text-center">
              <button
                type="button"
                className="text-xs text-[var(--text-muted)] underline-offset-2 hover:underline cursor-pointer"
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
              >
                Load more
              </button>
            </div>
          )}
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}

// --------------------------------------------------------------------- //

function StatPill({
  label,
  tone,
  muted,
}: {
  label: string;
  tone?: 'success' | 'error' | 'warn';
  muted?: boolean;
}) {
  const cls =
    tone === 'success'
      ? 'bg-[#14532d] text-[#4ade80]'
      : tone === 'error'
        ? 'bg-[#450a0a] text-[#f87171]'
        : tone === 'warn'
          ? 'bg-[#431407] text-[#fb923c]'
          : muted
            ? 'bg-[var(--surface2)] text-[var(--text-muted)]'
            : 'bg-[var(--surface2)] text-[var(--text)]';
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 ${cls}`}>
      {label}
    </span>
  );
}

function HistoryRow({
  row,
  expanded,
  onToggle,
  onOpenHistoryDiff,
}: {
  row: JobHistoryEntry;
  expanded: boolean;
  onToggle: () => void;
  onOpenHistoryDiff?: (target: string, fromHash: string) => void;
}) {
  const badge = getJobBadge({
    state: row.state,
    ota_result: row.ota_result ?? undefined,
    validate_only: !!row.validate_only,
    download_only: !!row.download_only,
  });
  const hasExcerpt = !!row.log_excerpt;
  return (
    <div className="flex flex-col">
      <div
        role={hasExcerpt ? 'button' : undefined}
        tabIndex={hasExcerpt ? 0 : undefined}
        className={`flex items-center gap-2 px-3 py-2 text-left ${hasExcerpt ? 'hover:bg-[var(--surface2)] cursor-pointer' : ''}`}
        onClick={hasExcerpt ? onToggle : undefined}
        onKeyDown={hasExcerpt ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(); } } : undefined}
        title={hasExcerpt ? 'Click to see log excerpt' : undefined}
      >
        <span className="shrink-0">
          {hasExcerpt ? (
            expanded ? (
              <ChevronDown className="size-3.5 text-[var(--text-muted)]" />
            ) : (
              <ChevronRight className="size-3.5 text-[var(--text-muted)]" />
            )
          ) : (
            <span className="inline-block size-3.5" />
          )}
        </span>
        <span className={`shrink-0 ${badge.cls}`}>{badge.label}</span>
        {/* Bug #39: show when the compile actually *started* (claimed by
            worker) alongside the "finished" relative time. Hover reveals
            both absolute timestamps. */}
        <span
          className="text-[12px] text-[var(--text-muted)] tabular-nums"
          title={
            row.started_at
              ? `Started: ${fmtEpochAbsolute(row.started_at)}\nFinished: ${fmtEpochAbsolute(row.finished_at)}`
              : fmtEpochAbsolute(row.finished_at)
          }
        >
          <Clock className="inline-block size-3 mr-1 -mt-0.5" aria-hidden="true" />
          {fmtEpochRelative(row.finished_at)}
        </span>
        {/* #83: suppress the duration dash on scheduled-cancel-before-start
            rows — the triggeredLabel already carries the full story. */}
        {!isScheduledCancelBeforeStart(row) && (
          <span className="text-[12px] text-[var(--text-muted)] tabular-nums">
            {fmtDuration(row.duration_seconds)}
          </span>
        )}
        <span className="text-[12px] text-[var(--text-muted)] truncate">
          {triggeredLabel(row)}
          {row.assigned_hostname && (
            <span> · {row.assigned_hostname}</span>
          )}
        </span>
        <span className="ml-auto text-[11px] text-[var(--text-muted)] font-mono">
          {row.esphome_version || '—'}
          {row.config_hash && (
            <>
              {' '}·{' '}
              {/* Bug #41: commit hash is clickable — opens the History panel
                  preset to `from = hash, to = Current`. Stop propagation so
                  we don't toggle the row expansion at the same time. */}
              {onOpenHistoryDiff ? (
                <button
                  type="button"
                  className="underline-offset-2 hover:underline cursor-pointer"
                  title={`Diff since this compile: ${row.config_hash}`}
                  onClick={(e) => { e.stopPropagation(); onOpenHistoryDiff(row.target, row.config_hash!); }}
                >
                  {row.config_hash.slice(0, 7)}
                </button>
              ) : (
                <span title={row.config_hash}>{row.config_hash.slice(0, 7)}</span>
              )}
            </>
          )}
        </span>
      </div>
      {expanded && hasExcerpt && (
        <pre className="px-3 pb-3 pt-1 overflow-auto text-[11px] leading-snug font-mono bg-[var(--surface2)] border-t border-[var(--border)] text-[var(--text)] max-h-[320px] whitespace-pre-wrap break-words">
          {/* Bug #36: render ANSI SGR codes instead of showing them as
              literal ``\x1b[31m…`` noise. */}
          {renderAnsi(row.log_excerpt ?? '')}
        </pre>
      )}
    </div>
  );
}
