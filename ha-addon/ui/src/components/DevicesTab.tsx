import { useCallback, useRef, useState } from 'react';
import { getApiKey } from '../api/client';
import type { Device, Target } from '../types';
import { stripYaml } from '../utils';

interface Props {
  targets: Target[];
  devices: Device[];
  onCompile: (targets: string[] | 'all' | 'outdated') => void;
  onEdit: (target: string) => void;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
}

function timeAgo(isoString: string): string {
  const ago = Math.round((Date.now() - new Date(isoString).getTime()) / 1000);
  if (ago < 60) return ago + 's ago';
  if (ago < 3600) return Math.floor(ago / 60) + 'm ago';
  return Math.floor(ago / 3600) + 'h ago';
}

function matchesFilter(filter: string, ...fields: (string | null | undefined)[]): boolean {
  if (!filter) return true;
  const q = filter.toLowerCase();
  return fields.some(f => f?.toLowerCase().includes(q));
}

export function DevicesTab({ targets, devices, onCompile, onEdit, onToast }: Props) {
  const [filter, setFilter] = useState('');

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

  const filteredTargets = filter
    ? sortedTargets.filter(t =>
        matchesFilter(
          filter,
          t.friendly_name,
          t.device_name,
          stripYaml(t.target),
          t.target,
          t.online == null ? 'unknown' : t.online ? 'online' : 'offline',
          t.ip_address,
          t.running_version,
        )
      )
    : sortedTargets;

  const filteredUnmanaged = filter
    ? sortedUnmanaged.filter(d =>
        matchesFilter(
          filter,
          d.name,
          stripYaml(d.name),
          d.online ? 'online' : 'offline',
          d.ip_address,
          d.running_version,
        )
      )
    : sortedUnmanaged;

  const hasResults = filteredTargets.length > 0 || filteredUnmanaged.length > 0;

  return (
    <div className="tab-panel active" id="tab-devices">
      <div className="panel">
        <div className="panel-header">
          <h2>Devices</h2>
          <div className="actions">
            <button className="btn-primary btn-sm" onClick={() => onCompile('all')}>Upgrade All</button>
            <button className="btn-secondary btn-sm" onClick={handleCompileSelected}>Upgrade Selected</button>
            <button className="btn-success btn-sm" onClick={() => onCompile('outdated')} disabled={!targets.some(t => t.needs_update)}>Upgrade Outdated</button>
          </div>
        </div>
        <div style={{ padding: '8px 16px', borderBottom: '1px solid var(--border)', background: 'var(--surface2)' }}>
          <div style={{ position: 'relative', maxWidth: 320 }}>
            <input
              type="text"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="Search devices..."
              style={{
                width: '100%',
                background: 'var(--surface2)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius)',
                color: 'var(--text)',
                fontSize: 13,
                padding: '5px 28px 5px 10px',
                outline: 'none',
              }}
            />
            {filter && (
              <button
                onClick={() => setFilter('')}
                style={{
                  position: 'absolute',
                  right: 6,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  padding: '0 2px',
                  fontSize: 14,
                  lineHeight: 1,
                }}
                title="Clear filter"
              >
                ×
              </button>
            )}
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
              {!hasResults ? (
                <tr className="empty-row">
                  <td colSpan={6}>
                    {filter
                      ? 'No devices match your search'
                      : 'No devices found — ensure ESPHome configs are in /config/esphome/'}
                  </td>
                </tr>
              ) : (
                <>
                  {filteredTargets.map(t => (
                    <TargetRow key={t.target} target={t} onCompile={onCompile} onEdit={onEdit} onToast={onToast} />
                  ))}
                  {filteredUnmanaged.map(d => (
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
  onToast,
}: {
  target: Target;
  onCompile: (targets: string[]) => void;
  onEdit: (target: string) => void;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
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

  async function handleCopyApiKey() {
    try {
      const key = await getApiKey(t.target);
      await navigator.clipboard.writeText(key);
      onToast('API key copied!', 'success');
    } catch (err) {
      const msg = (err as Error).message;
      if (msg.includes('No API key') || msg === '404') {
        onToast('No API key', 'info');
      } else {
        onToast('No API key', 'info');
      }
    }
  }

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
        {t.online && t.ip_address
          ? <a href={`http://${t.ip_address}`} target="_blank" rel="noopener" style={{ color: 'inherit', textDecoration: 'none' }} className="ip-link">{t.ip_address}</a>
          : (t.ip_address || '—')}
      </td>
      <td style={{ fontSize: 12 }}>
        {t.running_version || '—'}
        {t.config_modified && <div className="config-modified">config changed</div>}
      </td>
      <td>
        <div style={{ display: 'flex', gap: 4 }}>
          <button className={`${upgradeBtnCls} btn-sm`} onClick={() => onCompile([t.target])}>Upgrade</button>
          <button className="btn-secondary btn-sm" onClick={() => onEdit(t.target)}>Edit</button>
          <button
            className="btn-secondary btn-sm"
            onClick={handleCopyApiKey}
            title="Copy API encryption key"
            style={{ padding: '4px 7px' }}
          >
            &#128273;
          </button>
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
        {d.online && d.ip_address
          ? <a href={`http://${d.ip_address}`} target="_blank" rel="noopener" style={{ color: 'inherit', textDecoration: 'none' }} className="ip-link">{d.ip_address}</a>
          : (d.ip_address || '—')}
      </td>
      <td style={{ fontSize: 12 }}>{d.running_version || '—'}</td>
      <td></td>
    </tr>
  );
}
