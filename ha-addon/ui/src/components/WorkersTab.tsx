import type { Job, SystemInfo, Worker } from '../types';
import { stripYaml } from '../utils';

interface Props {
  workers: Worker[];
  queue: Job[];
  serverClientVersion?: string;
  onDisable: (id: string, disabled: boolean) => void;
  onRemove: (id: string) => void;
  onConnectWorker: () => void;
}

function workerPlatformHtml(si: SystemInfo): React.ReactNode {
  const lines: React.ReactNode[] = [];
  if (si.os_version) {
    lines.push(<span key="os" style={{ fontSize: 10, color: 'var(--text-muted)' }}>{si.os_version}</span>);
  }
  if (si.cpu_model) {
    lines.push(<span key="cpu" style={{ fontSize: 10, color: 'var(--text-muted)' }}>{si.cpu_model}</span>);
  }
  const hwParts: string[] = [];
  if (si.cpu_arch) hwParts.push(si.cpu_arch);
  if (si.cpu_cores) hwParts.push(si.cpu_cores + ' cores');
  if (si.total_memory) hwParts.push(si.total_memory);
  if (hwParts.length) {
    lines.push(<span key="hw" style={{ fontSize: 10, color: 'var(--text-muted)' }}>{hwParts.join(' · ')}</span>);
  }
  const metrics: string[] = [];
  if (si.perf_score != null) metrics.push(`Score: ${si.perf_score}`);
  if (si.cpu_usage != null) metrics.push(`CPU: ${si.cpu_usage}%`);
  if (metrics.length) {
    lines.push(
      <span key="metrics" style={{ fontSize: 10, color: 'var(--text-muted)' }} title="Perf score (SHA256 benchmark) · CPU utilization">
        {metrics.join(' · ')}
      </span>
    );
  }
  return lines.length === 0 ? null : (
    <>{lines.map((l, i) => <>{i > 0 && <br />}{l}</>)}</>
  );
}

function ClientVersionCell({ ver, scv }: { ver?: string; scv?: string }) {
  if (!ver) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  if (!scv || ver === scv) {
    return <code style={{ fontSize: 11, color: 'var(--text-muted)' }}>{ver}</code>;
  }
  return (
    <code style={{ fontSize: 11, color: 'var(--warn)' }} title={`Outdated — server: ${scv}`}>
      {ver} ↑
    </code>
  );
}

export function WorkersTab({ workers, queue, serverClientVersion, onDisable, onRemove, onConnectWorker }: Props) {
  const online = workers.filter(c => c.online).length;
  const countText = online + '/' + workers.length + ' online';

  const rows: React.ReactNode[] = [];

  for (const c of workers) {
    const slots = c.max_parallel_jobs || 1;
    const statusEl = c.disabled
      ? <><span className="dot dot-offline"></span><span style={{ color: 'var(--text-muted)' }}>Disabled</span></>
      : c.online
        ? <><span className="dot dot-online"></span>Online</>
        : <><span className="dot dot-offline"></span>Offline</>;

    const disableBtnCls = c.disabled ? 'btn-success btn-sm' : 'btn-warn btn-sm';
    const disableBtnLabel = c.disabled ? 'Enable' : 'Disable';
    const rowStyle = c.disabled ? { opacity: 0.6 } : undefined;

    for (let slot = 1; slot <= slots; slot++) {
      const slotJob = queue.find(
        j =>
          j.assigned_client_id === c.client_id &&
          (j.worker_id === slot || (slot === 1 && j.worker_id == null)) &&
          j.state === 'working',
      );

      const slotNameEl = slots > 1
        ? <>{c.hostname}<span style={{ color: 'var(--text-muted)', fontSize: 11 }}>/{slot}</span></>
        : <>{c.hostname}</>;

      const jobEl = slotJob
        ? <>
            <code style={{ fontSize: 12 }}>{stripYaml(slotJob.target)}</code>
            {slotJob.status_text && (
              <><br /><span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{slotJob.status_text}</span></>
            )}
          </>
        : <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>Idle</span>;

      const uptimeEl = c.system_info?.uptime
        ? <><br /><span style={{ fontSize: 10, color: 'var(--text-muted)' }} title="Worker process uptime">up {c.system_info.uptime}</span></>
        : null;

      if (slot === 1) {
        rows.push(
          <tr key={`${c.client_id}-1`} style={rowStyle}>
            <td>{slotNameEl}</td>
            <td>{c.system_info ? workerPlatformHtml(c.system_info) : null}</td>
            <td>{statusEl}{uptimeEl}</td>
            <td>{jobEl}</td>
            <td><ClientVersionCell ver={c.client_version} scv={serverClientVersion} /></td>
            <td>
              <div style={{ display: 'flex', gap: 4 }}>
                <button className={disableBtnCls} onClick={() => onDisable(c.client_id, !c.disabled)}>
                  {disableBtnLabel}
                </button>
                {!c.online && (
                  <button className="btn-danger btn-sm" onClick={() => onRemove(c.client_id)}>Remove</button>
                )}
              </div>
            </td>
          </tr>
        );
      } else {
        rows.push(
          <tr key={`${c.client_id}-${slot}`} style={rowStyle}>
            <td>{slotNameEl}</td>
            <td></td>
            <td></td>
            <td>{jobEl}</td>
            <td></td>
            <td></td>
          </tr>
        );
      }
    }
  }

  return (
    <div className="tab-panel active" id="tab-workers">
      <div className="panel">
        <div className="panel-header">
          <h2>Build Workers</h2>
          <div className="actions">
            <span id="workers-count" style={{ fontSize: 12, color: 'var(--text-muted)' }}>{countText}</span>
            <button className="btn-primary btn-sm" onClick={onConnectWorker}>+ Connect Worker</button>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Hostname</th>
                <th>Platform</th>
                <th>Status</th>
                <th>Current Job</th>
                <th>Version</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {workers.length === 0 ? (
                <tr className="empty-row">
                  <td colSpan={6}>No workers registered — click &quot;+ Connect Worker&quot; to add one</td>
                </tr>
              ) : rows}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
