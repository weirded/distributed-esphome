import { useMemo, useState } from 'react';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
} from '../ui/dropdown-menu';
import { UpgradeModal } from '../UpgradeModal';
import { BulkTagsEditDialog } from '../BulkTagsEditDialog';
import { commitFile, setTargetSchedule, updateTargetMeta } from '../../api/client';
import { useVersioningEnabled } from '../../hooks/useVersioning';
import type { Target, Worker } from '../../types';

function parseTags(s: string | null | undefined): string[] {
  if (!s) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of s.split(',')) {
    const t = part.trim();
    if (!t || seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  return out;
}

/**
 * Bulk "Actions" dropdown for the Devices tab (QS.18).
 *
 * Owns:
 *   - the `bulkScheduleOpen` state that drives the multi-target UpgradeModal,
 *   - the three per-selection handlers: Schedule Selected, Remove Schedule
 *     from Selected, and the save/delete callbacks the modal invokes,
 *   - the rendered dropdown + modal.
 *
 * Lifting these out of DevicesTab eliminates ~60 lines of state + JSX and
 * keeps the toolbar readable. The parent component only needs to pass in the
 * current selection and workers; everything else is self-contained here.
 */

type ToastFn = (msg: string, type?: 'info' | 'success' | 'error') => void;

interface Props {
  selectedTargets: string[];
  workers: Worker[];
  /** Full target list — used to filter "has a schedule" when bulk-removing. */
  targets: Target[];
  onToast: ToastFn;
  onRefresh: () => void;
}

export function DeviceTableActions({ selectedTargets, workers, targets, onToast, onRefresh }: Props) {
  const [bulkScheduleOpen, setBulkScheduleOpen] = useState(false);
  const [bulkTagsOpen, setBulkTagsOpen] = useState(false);
  const [commitAllBusy, setCommitAllBusy] = useState(false);
  const hasSelection = selectedTargets.length > 0;
  const versioningEnabled = useVersioningEnabled();

  // Bug #103: surface a fleet-wide "commit any uncommitted YAML" action
  // for the case where the user edited configs outside the addon (CLI,
  // file share, another editor) and ended up with a pile of dirty
  // working-tree files. The per-row hamburger only commits one target
  // at a time, which is tedious when there are dozens.
  const dirtyTargets = useMemo(
    () => targets.filter(t => t.has_uncommitted_changes).map(t => t.target),
    [targets],
  );

  async function handleCommitAll() {
    if (commitAllBusy || dirtyTargets.length === 0) return;
    setCommitAllBusy(true);
    try {
      // Mirrors SettingsDrawer's "turn on auto-commit" flow: one commit
      // per file, swallow individual failures so a single broken target
      // doesn't strand the whole batch.
      const results = await Promise.all(
        dirtyTargets.map(t =>
          commitFile(t)
            .then(r => ({ ok: true as const, target: t, committed: r.committed }))
            .catch(err => ({ ok: false as const, target: t, err: (err as Error).message })),
        ),
      );
      const committed = results.filter(r => r.ok && r.committed).length;
      const failed = results.filter(r => !r.ok).length;
      if (failed === 0 && committed === dirtyTargets.length) {
        onToast(`Committed ${committed} file${committed === 1 ? '' : 's'}`, 'success');
      } else if (committed > 0) {
        onToast(`Committed ${committed}, ${failed} failed`, failed > 0 ? 'error' : 'info');
      } else {
        onToast('No files committed', 'error');
      }
      onRefresh();
    } finally {
      setCommitAllBusy(false);
    }
  }

  // Bug #8: pre-compute the per-target tag lists, the intersection
  // (tags shared by all selected — bulk-removable), the partial set
  // (tags on some-but-not-all — read-only context), and the fleet-wide
  // suggestion pool (all device + worker tags). Memoized on the inputs
  // so the 1Hz SWR poll on the parent doesn't recompute on every render.
  const tagsAggregate = useMemo(() => {
    const selectedTags: string[][] = selectedTargets.map(name => {
      const t = targets.find(x => x.target === name);
      return parseTags(t?.tags);
    });
    let common: string[] = [];
    if (selectedTags.length > 0) {
      const first = new Set(selectedTags[0]);
      for (const list of selectedTags.slice(1)) {
        const seen = new Set(list);
        for (const t of Array.from(first)) {
          if (!seen.has(t)) first.delete(t);
        }
      }
      common = Array.from(first).sort();
    }
    const union = new Set<string>();
    for (const list of selectedTags) for (const t of list) union.add(t);
    const partial = Array.from(union).filter(t => !common.includes(t)).sort();
    const pool = new Set<string>();
    for (const tg of targets) for (const t of parseTags(tg.tags)) pool.add(t);
    for (const w of workers) if (w.tags) for (const t of w.tags) pool.add(t);
    return { common, partial, suggestions: Array.from(pool).sort() };
  }, [selectedTargets, targets, workers]);

  async function applyBulkTagDiff(diff: { add: string[]; remove: string[] }) {
    // Per-target: existing - removeMatching + addNew
    await Promise.all(selectedTargets.map(async (name) => {
      const t = targets.find(x => x.target === name);
      const existing = parseTags(t?.tags);
      const removeSet = new Set(diff.remove);
      const next = [
        ...existing.filter(x => !removeSet.has(x)),
        ...diff.add.filter(x => !existing.includes(x)),
      ];
      // Bug #9: drop the tags key entirely when the resulting list is empty.
      const value: string | null = next.length > 0 ? next.join(',') : null;
      await updateTargetMeta(name, { tags: value });
    }));
    onToast(
      `Updated tags on ${selectedTargets.length} device${selectedTargets.length === 1 ? '' : 's'}`,
      'success',
    );
    onRefresh();
  }

  function handleScheduleSelected() {
    if (!hasSelection) return;
    setBulkScheduleOpen(true);
  }

  // #15/#37: remove recurring AND one-time schedules on selected devices.
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
      const { deleteTargetSchedule } = await import('../../api/client');
      await Promise.all(scheduled.map(t => deleteTargetSchedule(t)));
      onToast(`Removed schedule from ${scheduled.length} device(s)`, 'success');
      onRefresh();
    } catch (err) {
      onToast('Remove failed: ' + (err as Error).message, 'error');
    }
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2.5 h-7 text-[0.8rem] font-medium text-foreground hover:bg-muted cursor-pointer">
          Actions <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuGroup>
            <DropdownMenuItem
              onClick={handleScheduleSelected}
              disabled={!hasSelection}
              title={!hasSelection ? 'Check one or more devices in the table first' : undefined}
            >
              Schedule Selected...
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={handleRemoveScheduleSelected}
              disabled={!hasSelection}
              title={!hasSelection ? 'Check one or more devices in the table first' : undefined}
            >
              Remove Schedule from Selected
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => setBulkTagsOpen(true)}
              disabled={!hasSelection}
              title={!hasSelection ? 'Check one or more devices in the table first' : undefined}
            >
              Edit Tags…
            </DropdownMenuItem>
            {versioningEnabled && (
              <DropdownMenuItem
                onClick={handleCommitAll}
                disabled={commitAllBusy || dirtyTargets.length === 0}
                title={
                  dirtyTargets.length === 0
                    ? 'No uncommitted YAML changes in the config directory'
                    : `Commit ${dirtyTargets.length} uncommitted YAML file${dirtyTargets.length === 1 ? '' : 's'} to the config-history git repo`
                }
              >
                Commit all uncommitted{dirtyTargets.length > 0 ? ` (${dirtyTargets.length})` : ''}
              </DropdownMenuItem>
            )}
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>

      {bulkTagsOpen && (
        <BulkTagsEditDialog
          open={bulkTagsOpen}
          onOpenChange={setBulkTagsOpen}
          count={selectedTargets.length}
          common={tagsAggregate.common}
          partial={tagsAggregate.partial}
          suggestions={tagsAggregate.suggestions}
          onSave={applyBulkTagDiff}
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
              const { setTargetScheduleOnce } = await import('../../api/client');
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
    </>
  );
}
