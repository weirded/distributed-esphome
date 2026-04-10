import { useEffect, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Select } from './ui/select';

const PRESETS: { label: string; cron: string }[] = [
  { label: 'Daily at 2:00 AM', cron: '0 2 * * *' },
  { label: 'Weekly Sunday 2:00 AM', cron: '0 2 * * 0' },
  { label: 'Monthly 1st at 2:00 AM', cron: '0 2 1 * *' },
  { label: 'Every 6 hours', cron: '0 */6 * * *' },
  { label: 'Every 12 hours', cron: '0 */12 * * *' },
];

interface Props {
  target: string;
  displayName: string;
  currentSchedule?: string | null;
  currentEnabled?: boolean;
  onSave: (cron: string) => void;
  onDelete: () => void;
  onToggle: () => void;
  onClose: () => void;
}

export function ScheduleModal({
  target: _target,
  displayName,
  currentSchedule,
  currentEnabled,
  onSave,
  onDelete,
  onToggle,
  onClose,
}: Props) {
  void _target;

  // Determine if the current schedule matches a preset.
  const matchingPreset = PRESETS.find(p => p.cron === currentSchedule);
  const initialMode = currentSchedule && !matchingPreset ? 'custom' : 'preset';

  const [mode, setMode] = useState<'preset' | 'custom'>(initialMode);
  const [selectedPreset, setSelectedPreset] = useState(matchingPreset?.cron ?? PRESETS[0].cron);
  const [customCron, setCustomCron] = useState(currentSchedule ?? '');

  // Keep customCron in sync when switching to custom mode.
  useEffect(() => {
    if (mode === 'custom' && !customCron && selectedPreset) {
      setCustomCron(selectedPreset);
    }
  }, [mode]); // eslint-disable-line react-hooks/exhaustive-deps

  const effectiveCron = mode === 'custom' ? customCron.trim() : selectedPreset;
  const hasSchedule = !!currentSchedule;

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent style={{ maxWidth: 480 }}>
        <DialogHeader>
          <DialogTitle>Schedule Upgrade — {displayName}</DialogTitle>
        </DialogHeader>
        <div className="p-[18px] flex flex-col gap-4">
          <div>
            <label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1">
              Frequency
            </label>
            <Select
              value={mode === 'custom' ? '__custom__' : selectedPreset}
              onChange={e => {
                if (e.target.value === '__custom__') {
                  setMode('custom');
                } else {
                  setMode('preset');
                  setSelectedPreset(e.target.value);
                }
              }}
            >
              {PRESETS.map(p => (
                <option key={p.cron} value={p.cron}>{p.label}</option>
              ))}
              <option value="__custom__">Custom (cron expression)</option>
            </Select>
          </div>

          {mode === 'custom' && (
            <div>
              <label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1">
                Cron Expression
              </label>
              <Input
                type="text"
                value={customCron}
                placeholder="0 2 * * *"
                onChange={e => setCustomCron(e.target.value)}
              />
              <div className="mt-1 text-[11px] text-[var(--text-muted)]">
                Standard 5-field cron: minute hour day-of-month month day-of-week
              </div>
            </div>
          )}

          {hasSchedule && (
            <div className="flex items-center gap-2">
              <label className="text-[12px] text-[var(--text)]">
                <input
                  type="checkbox"
                  checked={currentEnabled ?? false}
                  onChange={onToggle}
                  className="mr-2"
                />
                Schedule enabled
              </label>
            </div>
          )}

          <div className="flex justify-between items-center pt-2">
            <div>
              {hasSchedule && (
                <Button variant="destructive" size="sm" onClick={onDelete}>
                  Remove Schedule
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" onClick={onClose}>Cancel</Button>
              <Button
                size="sm"
                disabled={!effectiveCron}
                onClick={() => onSave(effectiveCron)}
              >
                {hasSchedule ? 'Update Schedule' : 'Set Schedule'}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
