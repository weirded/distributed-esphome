import { useEffect, useMemo, useState } from 'react';
import useSWR from 'swr';
import { toast } from 'sonner';
import { DiffEditor } from '@monaco-editor/react';
import { History, RotateCcw, AlertTriangle } from 'lucide-react';

import {
  commitFile,
  getFileContentAt,
  getFileHistory,
  getFileStatus,
  rollbackFile,
  type FileHistoryEntry,
  type FileStatus,
} from '@/api/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';

// AV.6: per-file history + diff panel. Opens as a drawer from the
// Editor modal's toolbar or the Devices hamburger. Combines the history
// endpoint (AV.3), diff endpoint (AV.4), rollback (AV.5), manual
// commit (AV.11), and status probe into one coherent surface.

interface HistoryPanelProps {
  /** Fully-qualified filename, e.g. "bedroom.yaml". `null` = closed. */
  filename: string | null;
  onOpenChange: (open: boolean) => void;
  /**
   * Called after a successful rollback or manual commit, so the caller
   * (typically the Editor modal) can refresh its buffer to match the
   * new on-disk content.
   */
  onFileChanged?: () => void;
}

// Sentinel used in the From/To dropdowns to mean "current working tree".
const WORKING_TREE = '__WORKING_TREE__';

export function HistoryPanel({ filename, onOpenChange, onFileChanged }: HistoryPanelProps) {
  const open = filename !== null;

  // SWR: history + status are fetched while the drawer is open.
  const historyKey = open ? ['fileHistory', filename] : null;
  const statusKey = open ? ['fileStatus', filename] : null;

  const {
    data: entries,
    error: historyError,
    mutate: mutateHistory,
    isLoading: historyLoading,
  } = useSWR<FileHistoryEntry[]>(
    historyKey,
    () => getFileHistory(filename!),
    { revalidateOnFocus: false },
  );

  const {
    data: status,
    mutate: mutateStatus,
  } = useSWR<FileStatus>(
    statusKey,
    () => getFileStatus(filename!),
    { revalidateOnFocus: false },
  );

  // Compare selector — From/To hold commit hashes, or the WORKING_TREE sentinel.
  const [fromHash, setFromHash] = useState<string>('');
  const [toHash, setToHash] = useState<string>(WORKING_TREE);

  // Each time the history list shows up (or changes), pick a sensible
  // default: From = parent of HEAD (= entries[1]) or HEAD itself if
  // only one commit exists; To = working tree.
  useEffect(() => {
    if (!entries || entries.length === 0) {
      setFromHash('');
      setToHash(WORKING_TREE);
      return;
    }
    // Only reset when the user hasn't already made a non-default selection.
    setFromHash(prev => prev && entries.some(e => e.hash === prev) ? prev : entries[0].hash);
    setToHash(prev => (prev === WORKING_TREE || entries.some(e => e.hash === prev)) ? prev : WORKING_TREE);
  }, [entries]);

  // Bug #10: side-by-side diff. Fetch the file's content at both
  // hashes separately (or the working tree for WORKING_TREE / unset)
  // and feed them to Monaco's DiffEditor with renderSideBySide on.
  const fromKey = open && filename ? ['fileContentAt', filename, fromHash || null] : null;
  const toKey = open && filename ? ['fileContentAt', filename, toHash === WORKING_TREE ? null : toHash] : null;

  const { data: fromContent = '', isLoading: fromLoading } = useSWR<string>(
    fromKey,
    () => getFileContentAt(filename!, fromHash || null),
    { revalidateOnFocus: false },
  );
  const { data: toContent = '', isLoading: toLoading } = useSWR<string>(
    toKey,
    () => getFileContentAt(filename!, toHash === WORKING_TREE ? null : toHash),
    { revalidateOnFocus: false },
  );
  const diffLoading = fromLoading || toLoading;

  // --- Actions ---

  const [busy, setBusy] = useState(false);

  async function handleRollback(entry: FileHistoryEntry) {
    if (!filename) return;
    const msg = status?.has_uncommitted_changes
      ? `Restore ${entry.short_hash}? Your uncommitted changes to ${filename} will be overwritten.`
      : `Restore ${entry.short_hash}? This will create a new revert commit.`;
    if (!window.confirm(msg)) return;
    setBusy(true);
    try {
      const result = await rollbackFile(filename, entry.hash);
      toast.success(`Restored ${result.short_hash ?? entry.short_hash}`);
      await Promise.all([mutateHistory(), mutateStatus()]);
      onFileChanged?.();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // Manual commit prompt
  const [commitPromptOpen, setCommitPromptOpen] = useState(false);
  const [commitMsg, setCommitMsg] = useState('');

  async function handleManualCommit() {
    if (!filename) return;
    setBusy(true);
    try {
      const result = await commitFile(filename, commitMsg.trim() || undefined);
      if (!result.committed) {
        toast.info('Nothing to commit');
      } else {
        toast.success(`Committed ${result.short_hash}`);
      }
      setCommitPromptOpen(false);
      setCommitMsg('');
      await Promise.all([mutateHistory(), mutateStatus()]);
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const fromLabel = useMemo(() => labelForHash(fromHash, entries), [fromHash, entries]);
  const toLabel = useMemo(() => labelForHash(toHash, entries), [toHash, entries]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="!w-[min(920px,100vw)]">
        <SheetHeader>
          <div className="flex items-center gap-2">
            <History className="size-4 text-[var(--text-muted)]" />
            <SheetTitle>{filename ?? 'History'}</SheetTitle>
          </div>
        </SheetHeader>
        <SheetBody>
          {historyError && (
            <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-400 mb-3">
              Failed to load history: {historyError.message}
            </div>
          )}

          {status?.has_uncommitted_changes && (
            <div className="mb-3 rounded-md border border-yellow-500/40 bg-yellow-500/10 px-3 py-2 text-xs flex items-start gap-2">
              <AlertTriangle className="size-4 text-yellow-400 mt-0.5 shrink-0" />
              <div className="flex-1">
                <div className="text-yellow-200">You have uncommitted changes.</div>
                <div className="text-yellow-300/80 mt-0.5">
                  These won't show up in history until committed.
                </div>
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setCommitPromptOpen(v => !v)}
                disabled={busy}
              >
                {commitPromptOpen ? 'Cancel' : 'Commit…'}
              </Button>
            </div>
          )}

          {commitPromptOpen && (
            <div className="mb-3 flex gap-2 items-center">
              <Input
                type="text"
                placeholder={`save: ${filename} (manual)`}
                className="flex-1 font-mono text-xs"
                value={commitMsg}
                onChange={e => setCommitMsg(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') { e.preventDefault(); void handleManualCommit(); }
                }}
                autoFocus
              />
              <Button type="button" onClick={handleManualCommit} disabled={busy}>
                Commit
              </Button>
            </div>
          )}

          {/* Compare pills — side by side, each aligned above its DiffEditor pane (bug #10). */}
          <div className="grid grid-cols-2 gap-2 mb-2 text-xs">
            <HashPicker
              label="From (left pane)"
              value={fromHash}
              entries={entries ?? []}
              onChange={setFromHash}
              allowWorkingTree
            />
            <HashPicker
              label="To (right pane)"
              value={toHash}
              entries={entries ?? []}
              onChange={setToHash}
              allowWorkingTree
            />
          </div>
          <div className="text-xs text-[var(--text-muted)] mb-2">
            Comparing <code className="font-mono">{fromLabel}</code> → <code className="font-mono">{toLabel}</code>
          </div>

          {/* Diff viewer — Monaco DiffEditor in side-by-side mode (bug #10). */}
          <div className="h-[360px] border border-[var(--border)] rounded-md overflow-hidden mb-4">
            {diffLoading ? (
              <div className="p-3 text-xs text-[var(--text-muted)]">Loading diff…</div>
            ) : fromContent === toContent ? (
              <div className="p-3 text-xs text-[var(--text-muted)]">
                No differences between {fromLabel} and {toLabel}.
              </div>
            ) : (
              <DiffEditor
                original={fromContent}
                modified={toContent}
                language="yaml"
                theme="vs-dark"
                options={{
                  readOnly: true,
                  renderSideBySide: true,
                  // Bug #12: Monaco's default is to collapse to inline/unified
                  // view when the diff editor's width is below ~900px,
                  // regardless of `renderSideBySide`. The history drawer is
                  // ~870px of pane-width, so we have to opt out of the
                  // auto-inline fallback to actually see two panes.
                  useInlineViewWhenSpaceIsLimited: false,
                  renderOverviewRuler: false,
                  minimap: { enabled: false },
                  scrollBeyondLastLine: false,
                  fontSize: 12,
                  lineNumbers: 'on',
                  originalEditable: false,
                }}
              />
            )}
          </div>

          {/* Commit list */}
          <div className="flex flex-col gap-1">
            <div className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)] mb-1">
              Commits
            </div>
            {historyLoading && <div className="text-xs text-[var(--text-muted)]">Loading…</div>}
            {entries && entries.length === 0 && (
              <div className="text-xs text-[var(--text-muted)]">
                No saved versions yet — your first edit will show up here.
              </div>
            )}
            {entries?.map(entry => (
              <CommitRow
                key={entry.hash}
                entry={entry}
                isFrom={fromHash === entry.hash}
                isTo={toHash === entry.hash}
                onClick={(e) => {
                  if (e.shiftKey) {
                    setFromHash(entry.hash);
                  } else {
                    // Default: show what this commit changed — parent ↔ this.
                    const idx = entries.indexOf(entry);
                    const parent = entries[idx + 1]?.hash ?? '';
                    setFromHash(parent);
                    setToHash(entry.hash);
                  }
                }}
                onSetFrom={() => setFromHash(entry.hash)}
                onSetTo={() => setToHash(entry.hash)}
                onRestore={() => handleRollback(entry)}
                disabled={busy}
              />
            ))}
          </div>
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}

function labelForHash(hash: string, entries: FileHistoryEntry[] | undefined): string {
  if (hash === WORKING_TREE || hash === '') return 'Current';
  const e = entries?.find(x => x.hash === hash);
  return e ? e.short_hash : hash.slice(0, 7);
}

function HashPicker({
  label,
  value,
  entries,
  onChange,
  allowWorkingTree,
}: {
  label: string;
  value: string;
  entries: FileHistoryEntry[];
  onChange: (v: string) => void;
  allowWorkingTree: boolean;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-[var(--text-muted)]">{label}</span>
      <select
        className="w-full rounded border border-[var(--border)] bg-[var(--surface2)] px-2 py-1 font-mono text-xs text-[var(--text)] outline-none"
        value={value}
        onChange={e => onChange(e.target.value)}
      >
        {allowWorkingTree && <option value={WORKING_TREE}>Current (working tree)</option>}
        {entries.map(e => (
          <option key={e.hash} value={e.hash}>
            {e.short_hash} · {e.message}
          </option>
        ))}
      </select>
    </label>
  );
}

function CommitRow({
  entry,
  isFrom,
  isTo,
  onClick,
  onSetFrom,
  onSetTo,
  onRestore,
  disabled,
}: {
  entry: FileHistoryEntry;
  isFrom: boolean;
  isTo: boolean;
  onClick: (e: React.MouseEvent) => void;
  onSetFrom: () => void;
  onSetTo: () => void;
  onRestore: () => void;
  disabled: boolean;
}) {
  const when = formatRelativeTime(entry.date);
  const ringClass = isTo
    ? 'border-[var(--accent)]'
    : isFrom
    ? 'border-yellow-500/60'
    : 'border-[var(--border)]';

  return (
    <div
      className={`rounded-md border ${ringClass} bg-[var(--surface2)] px-2.5 py-1.5 flex items-center gap-2 text-xs cursor-pointer hover:bg-[var(--border)]`}
      onClick={onClick}
      role="button"
      tabIndex={0}
    >
      <code className="font-mono text-[var(--text-muted)] shrink-0">{entry.short_hash}</code>
      <span className="truncate flex-1">{entry.message}</span>
      <span className="text-[var(--text-muted)] whitespace-nowrap">{when}</span>
      <span className="text-[var(--text-muted)] whitespace-nowrap font-mono">
        <span className="text-green-400">+{entry.lines_added}</span>{' '}
        <span className="text-red-400">-{entry.lines_removed}</span>
      </span>
      <div className="flex gap-1 ml-1" onClick={e => e.stopPropagation()}>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-6 px-2 text-xs"
          onClick={onSetFrom}
          disabled={disabled}
          title="Set as From (compare side)"
        >
          From
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-6 px-2 text-xs"
          onClick={onSetTo}
          disabled={disabled}
          title="Set as To (compare side)"
        >
          To
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-6 px-2 text-xs gap-1"
          onClick={onRestore}
          disabled={disabled}
          title="Restore this version"
        >
          <RotateCcw className="size-3" />
          Restore
        </Button>
      </div>
    </div>
  );
}

function formatRelativeTime(epochSeconds: number): string {
  if (!epochSeconds) return '';
  const ms = Date.now() - epochSeconds * 1000;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}
