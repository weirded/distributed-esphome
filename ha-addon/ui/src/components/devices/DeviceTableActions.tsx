import { useMemo, useState } from 'react';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
} from '../ui/dropdown-menu';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog';
import { Input } from '../ui/input';
import { Button } from '../ui/button';
import { UpgradeModal } from '../UpgradeModal';
import { BulkTagsEditDialog } from '../BulkTagsEditDialog';
import { commitFile, deleteTarget, restoreArchivedConfig, setTargetSchedule, updateTargetMeta } from '../../api/client';
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
  // Bug #106: prompt for a commit message before fanning out the bulk
  // commit. Open state + the entered message live here so the dialog
  // stays cancellable without losing the typed text mid-edit.
  const [commitAllOpen, setCommitAllOpen] = useState(false);
  const [commitAllMessage, setCommitAllMessage] = useState('');
  const hasSelection = selectedTargets.length > 0;
  const versioningEnabled = useVersioningEnabled();

  // Bug #201: archived devices can't be tag-edited (matches the per-row
  // hamburger which collapses to Unarchive + Permanently delete, and the
  // Tags-cell button which is read-only on archived rows). Filter the
  // bulk-tag selection so an "Edit Tags…" with mixed active+archived
  // selection only writes to the active rows; "Edit Tags…" disables when
  // every selected row is archived.
  const editableTagTargets = useMemo(() => {
    const archivedSet = new Set(targets.filter(t => t.archived).map(t => t.target));
    return selectedTargets.filter(name => !archivedSet.has(name));
  }, [selectedTargets, targets]);
  const archivedSelectedCount = selectedTargets.length - editableTagTargets.length;
  const tagEditDisabled = editableTagTargets.length === 0;
  let tagEditTitle: string | undefined;
  if (!hasSelection) tagEditTitle = 'Check one or more devices in the table first';
  else if (tagEditDisabled) tagEditTitle = 'Tags can’t be edited on archived devices';
  else if (archivedSelectedCount > 0) tagEditTitle = `${archivedSelectedCount} archived row${archivedSelectedCount === 1 ? '' : 's'} skipped — tags can’t be edited on archived devices`;

  // #208: bulk Archive / Unarchive selected. Only one of the two is
  // enabled at a time:
  //   - "Archive selected" is enabled when every checked row is active.
  //   - "Unarchive selected" is enabled when every checked row is archived.
  //   - Mixed selections (or empty selection) disable both — there's no
  //     single sensible action and the user shouldn't have to guess
  //     which subset would be touched.
  const selectedTargetObjs = useMemo(
    () => selectedTargets.map(name => targets.find(x => x.target === name)).filter((x): x is Target => !!x),
    [selectedTargets, targets],
  );
  const allSelectedActive = hasSelection && selectedTargetObjs.every(t => !t.archived);
  const allSelectedArchived = hasSelection && selectedTargetObjs.every(t => t.archived);
  const archiveSelectedTitle = !hasSelection
    ? 'Check one or more devices in the table first'
    : !allSelectedActive
      ? 'Mixed or all-archived selection — only active devices can be archived'
      : `Archive ${selectedTargets.length} device${selectedTargets.length === 1 ? '' : 's'}`;
  const unarchiveSelectedTitle = !hasSelection
    ? 'Check one or more devices in the table first'
    : !allSelectedArchived
      ? 'Mixed or all-active selection — only archived devices can be unarchived'
      : `Unarchive ${selectedTargets.length} device${selectedTargets.length === 1 ? '' : 's'}`;

  async function handleArchiveSelected() {
    if (!allSelectedActive) return;
    const names = [...selectedTargets];
    try {
      const results = await Promise.all(
        names.map(t =>
          deleteTarget(t, true)
            .then(() => ({ ok: true as const, target: t }))
            .catch(err => ({ ok: false as const, target: t, err: (err as Error).message })),
        ),
      );
      const ok = results.filter(r => r.ok).length;
      const failed = results.length - ok;
      if (failed === 0) {
        onToast(`Archived ${ok} device${ok === 1 ? '' : 's'}`, 'success');
      } else {
        onToast(`Archived ${ok}, ${failed} failed`, 'error');
      }
      onRefresh();
    } catch (err) {
      onToast('Archive failed: ' + (err as Error).message, 'error');
    }
  }

  async function handleUnarchiveSelected() {
    if (!allSelectedArchived) return;
    const names = [...selectedTargets];
    try {
      const results = await Promise.all(
        names.map(t =>
          restoreArchivedConfig(t)
            .then(() => ({ ok: true as const, target: t }))
            .catch(err => ({ ok: false as const, target: t, err: (err as Error).message })),
        ),
      );
      const ok = results.filter(r => r.ok).length;
      const failed = results.length - ok;
      if (failed === 0) {
        onToast(`Unarchived ${ok} device${ok === 1 ? '' : 's'}`, 'success');
      } else {
        onToast(`Unarchived ${ok}, ${failed} failed`, 'error');
      }
      onRefresh();
    } catch (err) {
      onToast('Unarchive failed: ' + (err as Error).message, 'error');
    }
  }

  // Bug #103: surface a fleet-wide "commit any uncommitted YAML" action
  // for the case where the user edited configs outside the addon (CLI,
  // file share, another editor) and ended up with a pile of dirty
  // working-tree files. The per-row hamburger only commits one target
  // at a time, which is tedious when there are dozens.
  const dirtyTargets = useMemo(
    () => targets.filter(t => t.has_uncommitted_changes).map(t => t.target),
    [targets],
  );

  function openCommitAll() {
    if (dirtyTargets.length === 0) return;
    setCommitAllMessage('');
    setCommitAllOpen(true);
  }

  async function handleCommitAll() {
    if (commitAllBusy || dirtyTargets.length === 0) return;
    setCommitAllBusy(true);
    // Bug #106: pass the user-entered message through to commitFile so
    // every file in the batch shares one author-supplied subject. Empty
    // input → undefined → server falls back to the default
    // "Manually committed from UI" marker (same as the per-row dialog).
    const message = commitAllMessage.trim() || undefined;
    try {
      // Mirrors SettingsDrawer's "turn on auto-commit" flow: one commit
      // per file, swallow individual failures so a single broken target
      // doesn't strand the whole batch.
      const results = await Promise.all(
        dirtyTargets.map(t =>
          commitFile(t, message)
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
      setCommitAllOpen(false);
      setCommitAllMessage('');
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
    // Bug #201: aggregate over editableTagTargets (active rows only) so
    // the dialog's "common" / "partial" reflect what we'll actually write.
    const selectedTags: string[][] = editableTagTargets.map(name => {
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
  }, [editableTagTargets, targets, workers]);

  async function applyBulkTagDiff(diff: { add: string[]; remove: string[] }) {
    // Per-target: existing - removeMatching + addNew. Bug #201: archived
    // rows are skipped (filtered into editableTagTargets above) so we
    // never write tag metadata into a YAML that lives in `.archive/`.
    await Promise.all(editableTagTargets.map(async (name) => {
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
    const n = editableTagTargets.length;
    const skippedSuffix = archivedSelectedCount > 0
      ? ` (${archivedSelectedCount} archived skipped)`
      : '';
    onToast(
      `Updated tags on ${n} device${n === 1 ? '' : 's'}${skippedSuffix}`,
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
              disabled={!hasSelection || tagEditDisabled}
              title={tagEditTitle}
            >
              Edit Tags…
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={handleArchiveSelected}
              disabled={!allSelectedActive}
              title={archiveSelectedTitle}
            >
              Archive Selected
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={handleUnarchiveSelected}
              disabled={!allSelectedArchived}
              title={unarchiveSelectedTitle}
            >
              Unarchive Selected
            </DropdownMenuItem>
            {versioningEnabled && (
              <DropdownMenuItem
                onClick={openCommitAll}
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
          // Bug #201: count reflects the editable (non-archived) subset
          // — that's what we'll actually write tags to.
          count={editableTagTargets.length}
          common={tagsAggregate.common}
          partial={tagsAggregate.partial}
          suggestions={tagsAggregate.suggestions}
          onSave={applyBulkTagDiff}
        />
      )}

      {/* Bug #106: commit-message prompt for the bulk "Commit all
          uncommitted" flow. Mirrors the per-row "Commit changes…"
          dialog in App.tsx so both surfaces feel the same. */}
      <Dialog
        open={commitAllOpen}
        onOpenChange={(open) => { if (!open && !commitAllBusy) setCommitAllOpen(false); }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Commit {dirtyTargets.length} uncommitted file{dirtyTargets.length === 1 ? '' : 's'}
            </DialogTitle>
          </DialogHeader>
          <div className="px-4 py-3 flex flex-col gap-2 text-sm text-[var(--text)]">
            <p className="text-xs text-[var(--text-muted)]">
              Optional commit message — applied to every file in the batch. Leave blank to use the default{' '}
              <code className="font-mono text-xs">Manually committed from UI</code>.
            </p>
            <Input
              type="text"
              className="font-mono text-xs"
              placeholder="Manually committed from UI"
              value={commitAllMessage}
              onChange={e => setCommitAllMessage(e.target.value)}
              autoFocus
            />
          </div>
          <DialogFooter>
            <DialogClose>
              <Button variant="secondary" size="sm" disabled={commitAllBusy}>Cancel</Button>
            </DialogClose>
            <Button
              size="sm"
              disabled={commitAllBusy || dirtyTargets.length === 0}
              onClick={handleCommitAll}
            >
              {commitAllBusy ? 'Committing…' : 'Commit'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
