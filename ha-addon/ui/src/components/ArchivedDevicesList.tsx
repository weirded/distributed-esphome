/**
 * Shared archived-devices list component (CF.2 + #62).
 *
 * Originally lived inline in ``SettingsDrawer.tsx`` under the
 * "Archived devices" section. Extracted when #62 added a parallel
 * entry point from the Devices tab toolbar — the same list + restore +
 * permanent-delete mechanics should power both surfaces, so pulling
 * the component out avoids a copy-paste drift risk.
 */

import { useState } from 'react';
import useSWR from 'swr';
import { toast } from 'sonner';

import {
  deleteArchivedConfig,
  getArchivedConfigs,
  restoreArchivedConfig,
  type ArchivedConfig,
} from '@/api/client';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { fmtEpochRelative } from '@/utils/format';


export function ArchivedDevicesList() {
  const { data, error, isLoading, mutate } = useSWR<ArchivedConfig[]>(
    'archived-configs',
    getArchivedConfigs,
    { revalidateOnFocus: false },
  );
  const [busy, setBusy] = useState<string | null>(null);
  // Two-step delete confirmation — matches the live device-delete flow:
  // the Permanently-delete action is destructive and should not be
  // one-click from the list.
  const [deleteCandidate, setDeleteCandidate] = useState<ArchivedConfig | null>(null);

  async function handleRestore(filename: string) {
    setBusy(filename);
    try {
      await restoreArchivedConfig(filename);
      toast.success(`Restored ${filename}`);
      await mutate();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function handleConfirmDelete(filename: string) {
    setBusy(filename);
    try {
      await deleteArchivedConfig(filename);
      toast.success(`Deleted ${filename} from archive`);
      await mutate();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(null);
      setDeleteCandidate(null);
    }
  }

  if (error) {
    return (
      <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-400">
        Failed to load archive: {error.message}
      </div>
    );
  }
  if (isLoading && !data) {
    return <div className="text-xs text-[var(--text-muted)]">Loading…</div>;
  }
  if (!data || data.length === 0) {
    return (
      <p className="text-xs text-[var(--text-muted)]">
        No archived devices. Deleted devices land here unless you pass{' '}
        <code className="rounded bg-[var(--surface2)] px-1 py-0.5">archive=false</code>.
      </p>
    );
  }

  return (
    <>
      <p className="text-xs text-[var(--text-muted)]">
        Devices you delete land here so you can restore them later. Restore moves the YAML
        back under <code className="rounded bg-[var(--surface2)] px-1 py-0.5">/config/esphome/</code>.
        Delete removes the file from the working tree (the prior contents stay in the config's
        git history).
      </p>
      <ul className="flex flex-col gap-2 text-xs">
        {data.map((a) => {
          // 1.6.1 bug #2: use the shared ``fmtEpochRelative`` so this
          // column can't drift from Queue / History / Last-compiled.
          // The helper owns the pluralisation + rounding + negative-
          // delta handling; the inline math below did three of those.
          const when = fmtEpochRelative(a.archived_at);
          const kb = (a.size / 1024).toFixed(1);
          return (
            <li key={a.filename} className="flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface2)] px-2 py-1.5">
              <div className="flex-1 min-w-0">
                <div className="truncate font-mono text-[12px] text-[var(--text)]" title={a.filename}>
                  {a.filename}
                </div>
                <div className="text-[10px] text-[var(--text-muted)]">
                  {when} · {kb} KB
                </div>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => handleRestore(a.filename)}
                disabled={busy !== null}
              >
                Restore
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => setDeleteCandidate(a)}
                disabled={busy !== null}
                title="Remove from the archive (prior contents remain in git history)"
              >
                Delete
              </Button>
            </li>
          );
        })}
      </ul>

      {/* Two-step delete confirmation — destructive action. */}
      <Dialog
        open={deleteCandidate !== null}
        onOpenChange={(o) => { if (!o && busy === null) setDeleteCandidate(null); }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {deleteCandidate?.filename} from the archive?</DialogTitle>
          </DialogHeader>
          <div className="px-4 py-3 text-sm text-[var(--text)]">
            <p>
              This removes the file from the archive directory. The device's prior contents stay
              in the config's git history — a git operator can recover them if needed.
            </p>
          </div>
          <DialogFooter>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setDeleteCandidate(null)}
              disabled={busy !== null}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => deleteCandidate && handleConfirmDelete(deleteCandidate.filename)}
              disabled={busy !== null}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
