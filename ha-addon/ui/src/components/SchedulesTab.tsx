import { useMemo, useState } from 'react';
import type { Target, Worker } from '../types';
import { stripYaml, timeAgo } from '../utils';
import { Button } from './ui/button';
import { deleteTargetSchedule } from '../api/client';

function formatNextRun(schedule: string | null | undefined, lastRun: string | null | undefined, scheduleOnce: string | null | undefined): string {
  if (scheduleOnce) {
    const d = new Date(scheduleOnce);
    return `Once: ${d.toLocaleString()}`;
  }
  if (!schedule) return '—';
  if (!lastRun) return 'Pending (first run)';
  return `Last: ${timeAgo(lastRun)}`;
}

interface Props {
  targets: Target[];
  workers: Worker[];
  onSchedule: (target: string) => void;
  onRefresh: () => void;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
}

export function SchedulesTab({ targets, workers, onSchedule, onRefresh, onToast }: Props) {
  void workers;

  const scheduled = useMemo(
    () => targets.filter(t => t.schedule || t.schedule_once),
    [targets],
  );

  const [selected, setSelected] = useState<Set<string>>(new Set());

  function toggleOne(target: string) {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(target)) next.delete(target);
      else next.add(target);
      return next;
    });
  }

  function toggleAll() {
    if (selected.size === scheduled.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(scheduled.map(t => t.target)));
    }
  }

  async function handleRemoveSelected() {
    const toRemove = [...selected].filter(t => scheduled.some(s => s.target === t));
    if (toRemove.length === 0) return;
    try {
      await Promise.all(toRemove.map(t => deleteTargetSchedule(t)));
      onToast(`Removed schedule from ${toRemove.length} device(s)`, 'success');
      setSelected(new Set());
      onRefresh();
    } catch (err) {
      onToast('Remove failed: ' + (err as Error).message, 'error');
    }
  }

  if (scheduled.length === 0) {
    return (
      <div className="p-8 text-center text-[var(--text-muted)]">
        <p style={{ fontSize: 14 }}>No devices have a schedule configured.</p>
        <p style={{ fontSize: 12, marginTop: 8 }}>
          Open a device's hamburger menu and choose "Schedule Upgrade..." to set one up.
        </p>
      </div>
    );
  }

  return (
    <div className="p-4">
      {/* Toolbar */}
      <div className="flex items-center gap-3 mb-3">
        <span className="text-[12px] text-[var(--text-muted)]">
          {selected.size > 0 ? `${selected.size} selected` : `${scheduled.length} scheduled device${scheduled.length !== 1 ? 's' : ''}`}
        </span>
        {selected.size > 0 && (
          <Button variant="destructive" size="sm" onClick={handleRemoveSelected}>
            Remove Selected
          </Button>
        )}
      </div>

      <table className="w-full text-left" style={{ borderCollapse: 'collapse' }}>
        <thead>
          <tr className="border-b border-[var(--border)] text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">
            <th className="px-3 py-2 w-8">
              <input
                type="checkbox"
                checked={selected.size === scheduled.length && scheduled.length > 0}
                onChange={toggleAll}
              />
            </th>
            <th className="px-3 py-2">Device</th>
            <th className="px-3 py-2">Schedule</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Next / Last Run</th>
            <th className="px-3 py-2">Version</th>
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {scheduled.map(t => {
            const humanSchedule = t.schedule || (t.schedule_once ? `Once: ${new Date(t.schedule_once).toLocaleString()}` : '—');
            const enabled = t.schedule_enabled !== false;
            const version = t.pinned_version || t.server_version || '—';
            const isSelected = selected.has(t.target);

            return (
              <tr
                key={t.target}
                className={`border-b border-[var(--border)] hover:bg-[var(--surface2)] ${isSelected ? 'bg-[var(--accent)]/5' : ''}`}
              >
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleOne(t.target)}
                  />
                </td>
                <td className="px-3 py-2 text-[13px]">
                  {t.friendly_name || t.device_name || stripYaml(t.target)}
                  <div className="text-[11px] text-[var(--text-muted)]">{stripYaml(t.target)}</div>
                </td>
                <td className="px-3 py-2 text-[12px] font-mono" style={{ opacity: enabled ? 1 : 0.5 }}>
                  {humanSchedule}
                  {!enabled && t.schedule && <span className="text-[var(--text-muted)] ml-2">(paused)</span>}
                </td>
                <td className="px-3 py-2 text-[12px]">
                  {t.schedule_once
                    ? <span style={{ color: 'var(--accent)' }}>One-time</span>
                    : enabled
                      ? <span style={{ color: 'var(--success)' }}>Active</span>
                      : <span style={{ color: 'var(--text-muted)' }}>Paused</span>}
                </td>
                <td className="px-3 py-2 text-[12px]">
                  {formatNextRun(t.schedule, t.schedule_last_run, t.schedule_once)}
                </td>
                <td className="px-3 py-2 text-[12px] font-mono">
                  {version}
                  {t.pinned_version && <span style={{ marginLeft: 4 }}>📌</span>}
                </td>
                <td className="px-3 py-2">
                  <Button variant="secondary" size="xs" onClick={() => onSchedule(t.target)}>
                    Edit
                  </Button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
