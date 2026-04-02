import { useCallback, useRef } from 'react';
import type { Job, Worker } from '../types';
import { fmtDuration, getJobBadge, stripYaml, isJobSuccessful, isJobInProgress, isJobFailed, isJobFinished, isJobRetryable } from '../utils';

interface Props {
  queue: Job[];
  workers: Worker[];
  onCancel: (ids: string[]) => void;
  onRetry: (ids: string[]) => void;
  onRetryAllFailed: () => void;
  onClearSucceeded: () => void;
  onClearFinished: () => void;
  onOpenLog: (jobId: string) => void;
}

const STATE_ORDER: Record<string, number> = {
  working: 0,
  pending: 1,
  timed_out: 2,
  failed: 3,
  success: 4,
};

export function QueueTab({
  queue,
  workers,
  onCancel,
  onRetry,
  onRetryAllFailed,
  onClearSucceeded,
  onClearFinished,
  onOpenLog,
}: Props) {
  const tbodyRef = useRef<HTMLTableSectionElement>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);

  const getChecked = useCallback((): string[] => {
    if (!tbodyRef.current) return [];
    return Array.from(tbodyRef.current.querySelectorAll<HTMLInputElement>('.queue-cb:checked'))
      .map(cb => cb.value);
  }, []);

  function handleSelectAll(e: React.ChangeEvent<HTMLInputElement>) {
    tbodyRef.current?.querySelectorAll<HTMLInputElement>('.queue-cb').forEach(cb => {
      cb.checked = e.target.checked;
    });
  }

  function handleCancelSelected() {
    const selected = getChecked();
    if (selected.length > 0) onCancel(selected);
  }

  function handleRetrySelected() {
    const ids = getChecked().filter(id => {
      const job = queue.find(j => j.id === id);
      return job && isJobRetryable(job);
    });
    if (ids.length > 0) onRetry(ids);
  }

  // Button state: compute what's in the queue
  const hasFailedJobs = queue.some(j => isJobFailed(j));
  const hasSuccessfulJobs = queue.some(j => isJobSuccessful(j));
  const hasFinishedJobs = queue.some(j => isJobFinished(j));

  const sorted = [...queue].sort((a, b) => {
    const so = (STATE_ORDER[a.state] ?? 9) - (STATE_ORDER[b.state] ?? 9);
    if (so !== 0) return so;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });

  return (
    <div className="tab-panel active" id="tab-queue">
      <div className="panel">
        <div className="panel-header">
          <h2>Queue</h2>
          <div className="actions">
            <button className="btn-warn btn-sm" onClick={onRetryAllFailed} disabled={!hasFailedJobs}>Retry All Failed</button>
            <button className="btn-warn btn-sm" onClick={handleRetrySelected}>Retry Selected</button>
            <button className="btn-danger btn-sm" onClick={handleCancelSelected}>Cancel Selected</button>
            <button className="btn-success btn-sm" onClick={onClearSucceeded} disabled={!hasSuccessfulJobs}>Clear Succeeded</button>
            <button className="btn-secondary btn-sm" onClick={onClearFinished} disabled={!hasFinishedJobs}>Clear Finished</button>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th><input type="checkbox" ref={selectAllRef} onChange={handleSelectAll} /></th>
                <th>Device</th>
                <th>State</th>
                <th>Worker</th>
                <th>Duration</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody ref={tbodyRef}>
              {sorted.length === 0 ? (
                <tr className="empty-row"><td colSpan={6}>No jobs in queue</td></tr>
              ) : (
                sorted.map(job => (
                  <QueueRow
                    key={job.id}
                    job={job}
                    workers={workers}
                    onCancel={onCancel}
                    onRetry={onRetry}
                    onOpenLog={onOpenLog}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function QueueRow({
  job,
  workers,
  onCancel,
  onRetry,
  onOpenLog,
}: {
  job: Job;
  workers: Worker[];
  onCancel: (ids: string[]) => void;
  onRetry: (ids: string[]) => void;
  onOpenLog: (jobId: string) => void;
}) {
  const assignedClient = job.assigned_client_id
    ? workers.find(c => c.client_id === job.assigned_client_id)
    : null;
  const pinnedClient = job.pinned_client_id
    ? workers.find(c => c.client_id === job.pinned_client_id)
    : null;

  const baseHostname = job.assigned_hostname || assignedClient?.hostname || null;
  const showSlot =
    baseHostname &&
    job.worker_id != null &&
    (assignedClient?.max_parallel_jobs || 1) > 1;
  const clientName = baseHostname
    ? showSlot
      ? `${baseHostname}/${job.worker_id}`
      : baseHostname
    : '—';

  const pinnedHostname = pinnedClient?.hostname || job.assigned_hostname;
  const showPinned =
    pinnedHostname && job.pinned_client_id && job.state === 'pending';

  const inProgress = isJobInProgress(job);
  const dur =
    job.duration_seconds != null
      ? fmtDuration(job.duration_seconds)
      : inProgress && job.assigned_at
      ? fmtDuration((Date.now() - new Date(job.assigned_at).getTime()) / 1000)
      : '—';

  const { label: badgeLabel, cls: badgeCls } = getJobBadge(job);
  const hasLog = !!(job.log || inProgress);
  const canRetry = isJobRetryable(job);
  const canCancel = inProgress;

  return (
    <tr data-job={job.id}>
      <td><input type="checkbox" className="queue-cb" value={job.id} /></td>
      <td>
        <strong>{stripYaml(job.target)}</strong>
        <br />
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{job.id.slice(0, 8)}</span>
      </td>
      <td><span className={badgeCls}>{badgeLabel}</span></td>
      <td style={{ fontSize: 12 }}>
        {clientName}
        {showPinned && (
          <><br /><span style={{ fontSize: 10, color: 'var(--text-muted)' }}>→ {pinnedHostname}</span></>
        )}
      </td>
      <td style={{ fontSize: 12 }}>{dur}</td>
      <td>
        <div style={{ display: 'flex', gap: 4 }}>
          {canCancel && (
            <button className="btn-danger btn-sm" onClick={() => onCancel([job.id])}>Cancel</button>
          )}
          {canRetry && (
            <button className="btn-warn btn-sm" onClick={() => onRetry([job.id])}>Retry</button>
          )}
          {hasLog && (
            <button className="btn-secondary btn-sm" onClick={() => onOpenLog(job.id)}>Log</button>
          )}
        </div>
      </td>
    </tr>
  );
}
