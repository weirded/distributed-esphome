import { useMemo } from 'react';
import type { Target, Worker } from '../types';
import { stripYaml, timeAgo } from '../utils';

/**
 * Compute the next cron fire time as a human-readable string.
 * Uses croniter on the server; here we just show "next run" from last_run + schedule.
 * For simplicity, we show the cron expression + last run time. A full next-fire
 * computation in JS would require a cron library; for now the server computes it.
 */
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
}

export function SchedulesTab({ targets, workers, onSchedule }: Props) {
  // Filter to only targets with any schedule (recurring or one-time).
  const scheduled = useMemo(
    () => targets.filter(t => t.schedule || t.schedule_once),
    [targets],
  );

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
      <table className="w-full text-left" style={{ borderCollapse: 'collapse' }}>
        <thead>
          <tr className="border-b border-[var(--border)] text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">
            <th className="px-3 py-2">Device</th>
            <th className="px-3 py-2">Schedule</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Next / Last Run</th>
            <th className="px-3 py-2">Version</th>
            <th className="px-3 py-2">Worker</th>
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {scheduled.map(t => {
            const humanSchedule = t.schedule || (t.schedule_once ? `Once: ${new Date(t.schedule_once).toLocaleString()}` : '—');
            const enabled = t.schedule_enabled !== false;
            const version = t.pinned_version || t.server_version || '—';
            // Find the preferred worker — for now show "any" since schedules
            // don't pin to a specific worker (they use the scheduler which
            // goes through normal queue dispatch).
            const workerLabel = 'Any';
            void workers; // available for future per-schedule worker pinning

            return (
              <tr
                key={t.target}
                className="border-b border-[var(--border)] hover:bg-[var(--surface2)] cursor-pointer"
                onClick={() => onSchedule(t.target)}
              >
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
                <td className="px-3 py-2 text-[12px]">{workerLabel}</td>
                <td className="px-3 py-2 text-[12px] text-[var(--accent)]">Edit</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
