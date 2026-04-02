import { useCallback, useRef } from 'react';
import type { Device, Target } from '../types';
import { stripYaml } from '../utils';

interface Props {
  targets: Target[];
  devices: Device[];
  onCompile: (targets: string[] | 'all' | 'outdated') => void;
  onEdit: (target: string) => void;
}

function timeAgo(isoString: string): string {
  const ago = Math.round((Date.now() - new Date(isoString).getTime()) / 1000);
  if (ago < 60) return ago + 's ago';
  if (ago < 3600) return Math.floor(ago / 60) + 'm ago';
  return Math.floor(ago / 3600) + 'h ago';
}

export function DevicesTab({ targets, devices, onCompile, onEdit }: Props) {
  // Track checked state in a ref — we read DOM directly to avoid re-render loops
  const tbodyRef = useRef<HTMLTableSectionElement>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);

  const getChecked = useCallback((): string[] => {
    if (!tbodyRef.current) return [];
    return Array.from(tbodyRef.current.querySelectorAll<HTMLInputElement>('.target-cb:checked'))
      .map(cb => cb.value);
  }, []);

  function handleSelectAll(e: React.ChangeEvent<HTMLInputElement>) {
    tbodyRef.current?.querySelectorAll<HTMLInputElement>('.target-cb').forEach(cb => {
      cb.checked = e.target.checked;
    });
  }

  function handleCompileSelected() {
    const selected = getChecked();
    if (selected.length === 0) return;
    onCompile(selected);
  }

  const unmanaged = devices.filter(d => !d.compile_target);
  const sortedTargets = [...targets].sort((a, b) => a.target.localeCompare(b.target));
  const sortedUnmanaged = [...unmanaged].sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div className="tab-panel active" id="tab-devices">
      <div className="panel">
        <div className="panel-header">
          <h2>Devices</h2>
          <div className="actions">
            <button className="btn-primary btn-sm" onClick={() => onCompile('all')}>Upgrade All</button>
            <button className="btn-secondary btn-sm" onClick={handleCompileSelected}>Upgrade Selected</button>
            <button className="btn-warn btn-sm" onClick={() => onCompile('outdated')}>Upgrade Outdated</button>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th><input type="checkbox" ref={selectAllRef} onChange={handleSelectAll} /></th>
                <th>Device</th>
                <th>Status</th>
                <th>IP</th>
                <th>Running</th>
                <th></th>
              </tr>
            </thead>
            <tbody ref={tbodyRef}>
              {sortedTargets.length === 0 && sortedUnmanaged.length === 0 ? (
                <tr className="empty-row">
                  <td colSpan={6}>No devices found — ensure ESPHome configs are in /config/esphome/</td>
                </tr>
              ) : (
                <>
                  {sortedTargets.map(t => (
                    <TargetRow key={t.target} target={t} onCompile={onCompile} onEdit={onEdit} />
                  ))}
                  {sortedUnmanaged.map(d => (
                    <UnmanagedRow key={d.name} device={d} />
                  ))}
                </>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function TargetRow({
  target: t,
  onCompile,
  onEdit,
}: {
  target: Target;
  onCompile: (targets: string[]) => void;
  onEdit: (target: string) => void;
}) {
  let lastSeenEl: React.ReactNode = null;
  if (t.last_seen) {
    lastSeenEl = <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{timeAgo(t.last_seen)}</div>;
  }

  let statusEl: React.ReactNode;
  if (t.online == null) {
    statusEl = <><span className="dot dot-offline"></span><span style={{ color: 'var(--text-muted)' }}>Unknown</span></>;
  } else if (t.online) {
    statusEl = <><span className="dot dot-online"></span>Online{lastSeenEl}</>;
  } else {
    statusEl = <><span className="dot dot-offline"></span>Offline{lastSeenEl}</>;
  }

  const upgradeBtnCls = t.needs_update ? 'btn-success' : 'btn-secondary';
  const displayName = t.friendly_name || t.device_name || stripYaml(t.target);

  return (
    <tr>
      <td><input type="checkbox" className="target-cb" value={t.target} /></td>
      <td>
        <span className="device-name">{displayName}</span>
        <div className="device-filename">{stripYaml(t.target)}</div>
        {t.comment && <div className="device-comment">{t.comment}</div>}
      </td>
      <td>{statusEl}</td>
      <td style={{ color: 'var(--text-muted)', fontFamily: 'monospace', fontSize: 12 }}>
        {t.ip_address || '—'}
      </td>
      <td style={{ fontSize: 12 }}>
        {t.running_version || '—'}
        {t.config_modified && <div className="config-modified">config changed</div>}
      </td>
      <td>
        <div style={{ display: 'flex', gap: 4 }}>
          <button className={`${upgradeBtnCls} btn-sm`} onClick={() => onCompile([t.target])}>Upgrade</button>
          <button className="btn-secondary btn-sm" onClick={() => onEdit(t.target)}>Edit</button>
        </div>
      </td>
    </tr>
  );
}

function UnmanagedRow({ device: d }: { device: Device }) {
  const statusEl = d.online
    ? <><span className="dot dot-online"></span>Online</>
    : <><span className="dot dot-offline"></span>Offline</>;

  return (
    <tr>
      <td></td>
      <td>
        <span className="device-name" style={{ color: 'var(--text-muted)' }}>{stripYaml(d.name)}</span>
        <div className="device-filename" style={{ color: '#6b7280' }}>No config</div>
      </td>
      <td>{statusEl}</td>
      <td style={{ color: 'var(--text-muted)', fontFamily: 'monospace', fontSize: 12 }}>
        {d.ip_address || '—'}
      </td>
      <td style={{ fontSize: 12 }}>{d.running_version || '—'}</td>
      <td></td>
    </tr>
  );
}
