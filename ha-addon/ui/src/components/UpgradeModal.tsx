import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Button } from './ui/button';
import { Select } from './ui/select';
import type { Worker } from '../types';

/**
 * Upgrade modal (#16).
 *
 * Replaces the inline Upgrade button click + hand-rolled "Upgrade on..."
 * submenu with a single modal that lets the user choose:
 *  - **Worker** — `<any>` (default; dispatches via the normal scheduler) or
 *    a specific online worker (sent as `pinned_client_id`).
 *  - **ESPHome version** — defaults to the global selected version, plus
 *    every other available version. Picking a non-default value enqueues
 *    the job with an `esphome_version` override.
 *
 * Confirm = "Upgrade" button. Cancel = the Dialog's built-in close.
 */

interface Props {
  /** The target YAML filename (e.g. "cyd-office-info.yaml"). */
  target: string;
  /** Display name shown in the title (friendly_name preferred, falls back to target). */
  displayName: string;
  /** All workers; we filter to online + non-paused inside the component. */
  workers: Worker[];
  /** All available ESPHome versions, newest first. */
  esphomeVersions: string[];
  /** The currently selected/default ESPHome version (radio default). */
  defaultEsphomeVersion: string | null;
  /**
   * Called when the user clicks Upgrade. Receives the selected worker
   * client_id (or null for `<any>`) and the selected ESPHome version
   * (or null when it equals the default — caller can omit the override).
   */
  onConfirm: (params: {
    pinnedClientId: string | null;
    esphomeVersion: string | null;
  }) => void;
  onClose: () => void;
}

export function UpgradeModal({
  target: _target,
  displayName,
  workers,
  esphomeVersions,
  defaultEsphomeVersion,
  onConfirm,
  onClose,
}: Props) {
  void _target;
  // Online + accepting jobs. Sorted by hostname for stable ordering.
  const eligibleWorkers = workers
    .filter(w => w.online && !w.disabled && (w.max_parallel_jobs ?? 0) > 0)
    .slice()
    .sort((a, b) => a.hostname.localeCompare(b.hostname, undefined, { sensitivity: 'base' }));

  const [selectedWorker, setSelectedWorker] = useState<string>('');  // '' = <any>
  const [selectedVersion, setSelectedVersion] = useState<string>(defaultEsphomeVersion ?? '');

  // Build the version dropdown list. Always include the default at the top
  // (even if it's not in the available list, e.g. when the global default
  // is a build version that PyPI hasn't seen). De-dup the rest.
  const versionList: string[] = [];
  if (defaultEsphomeVersion) versionList.push(defaultEsphomeVersion);
  for (const v of esphomeVersions) {
    if (v && !versionList.includes(v)) versionList.push(v);
  }

  function handleConfirm() {
    onConfirm({
      pinnedClientId: selectedWorker || null,
      // Only send the override when the user picked a non-default version.
      esphomeVersion: selectedVersion && selectedVersion !== defaultEsphomeVersion
        ? selectedVersion
        : null,
    });
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent style={{ maxWidth: 480 }}>
        <DialogHeader>
          <DialogTitle>Upgrade {displayName}</DialogTitle>
        </DialogHeader>
        <div className="p-[18px] flex flex-col gap-4">
          <div>
            <label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1">
              Worker
            </label>
            <Select
              value={selectedWorker}
              onChange={e => setSelectedWorker(e.target.value)}
            >
              <option value="">&lt;any&gt; — let the scheduler pick</option>
              {eligibleWorkers.map(w => (
                <option key={w.client_id} value={w.client_id}>
                  {w.hostname}
                </option>
              ))}
            </Select>
            {eligibleWorkers.length === 0 && (
              <div className="mt-1 text-[11px] text-[var(--text-muted)]">
                No workers are currently online; the job will queue and the next
                available worker will pick it up.
              </div>
            )}
          </div>

          <div>
            <label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1">
              ESPHome version
            </label>
            <Select
              value={selectedVersion}
              onChange={e => setSelectedVersion(e.target.value)}
            >
              {versionList.length === 0 && <option value="">(default)</option>}
              {versionList.map(v => (
                <option key={v} value={v}>
                  {v}{v === defaultEsphomeVersion ? ' (default)' : ''}
                </option>
              ))}
            </Select>
            <div className="mt-1 text-[11px] text-[var(--text-muted)]">
              Picking a non-default version stamps it on this job only — the
              global default isn't changed.
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={onClose}>Cancel</Button>
            <Button variant="success" onClick={handleConfirm}>Upgrade</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
