import { useState } from 'react';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
} from '../ui/dropdown-menu';
import { UpgradeModal } from '../UpgradeModal';
import { setTargetSchedule } from '../../api/client';
import type { Target, Worker } from '../../types';

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
  const hasSelection = selectedTargets.length > 0;

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
            <DropdownMenuItem onClick={handleScheduleSelected} disabled={!hasSelection}>
              Schedule Selected...
            </DropdownMenuItem>
            <DropdownMenuItem onClick={handleRemoveScheduleSelected} disabled={!hasSelection}>
              Remove Schedule from Selected
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>

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
