import { useCallback, useEffect, useRef, useState } from 'react';
import { getApiKey, restartDevice } from '../api/client';
import type { Device, Target } from '../types';
import { stripYaml } from '../utils';
import { useSortable } from '../hooks/useSortable';
import { SortableHeader } from './SortableHeader';

interface Props {
  targets: Target[];
  devices: Device[];
  onCompile: (targets: string[] | 'all' | 'outdated') => void;
  onEdit: (target: string) => void;
  onLogs: (target: string) => void;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
  onDelete: (target: string, archive: boolean) => void;
  onRename: (oldTarget: string, newName: string) => void;
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

export function RenameModal({ currentName, onConfirm, onClose }: {
  currentName: string;
  onConfirm: (newName: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(stripYaml(currentName));
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.select(); }, []);

  return (
    <div className="modal-overlay open" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 480, height: 'auto' }}>
        <div className="modal-header">
          <div className="modal-header-left"><h3>Rename Device</h3></div>
          <button className="modal-close" onClick={onClose}>&#x2715;</button>
        </div>
        <div className="modal-body" style={{ padding: 18 }}>
          <label style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6, display: 'block' }}>
            New device name
          </label>
          <input
            ref={inputRef}
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && name.trim() && name.trim() !== stripYaml(currentName) && onConfirm(name.trim())}
            style={{ width: '100%', padding: '8px 12px', background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', color: 'var(--text)', fontSize: 14 }}
          />
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>
            This will update the config file, rename it, and compile + upgrade the device with the new name via OTA.
          </p>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
            <button className="btn-secondary btn-sm" onClick={onClose}>Cancel</button>
            <button
              className="btn-primary btn-sm"
              disabled={!name.trim() || name.trim() === stripYaml(currentName)}
              onClick={() => onConfirm(name.trim())}
            >
              Rename &amp; Upgrade
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function DeleteModal({ target, onConfirm, onClose }: {
  target: string;
  onConfirm: (archive: boolean) => void;
  onClose: () => void;
}) {
  return (
    <div className="modal-overlay open" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 480, height: 'auto' }}>
        <div className="modal-header">
          <div className="modal-header-left"><h3>Delete Device</h3></div>
          <button className="modal-close" onClick={onClose}>&#x2715;</button>
        </div>
        <div className="modal-body" style={{ padding: 18 }}>
          <p>Are you sure you want to delete <strong>{stripYaml(target)}</strong>?</p>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
            <button className="btn-secondary btn-sm" onClick={onClose}>Cancel</button>
            <button className="btn-warn btn-sm" onClick={() => onConfirm(true)}>
              Archive
            </button>
            <button className="btn-danger btn-sm" onClick={() => onConfirm(false)}>
              Delete Permanently
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function DevicesTab({ targets, devices, onCompile, onEdit, onLogs, onToast, onDelete, onRename }: Props) {
  const [filter, setFilter] = useState('');
  const { sort, handleSort, sortedItems } = useSortable();
  const [renameTarget, setRenameTarget] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

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

  // Build a set of device names that are already shown as managed targets
  // to prevent duplicates when compile_target mapping has a race condition
  const managedDeviceNames = new Set<string>();
  for (const t of targets) {
    // The device_name from the target's resolved config (title-cased)
    if (t.device_name) managedDeviceNames.add(t.device_name.toLowerCase().replace(/ /g, '-').replace(/ /g, '_'));
    // The filename stem
    managedDeviceNames.add(stripYaml(t.target).toLowerCase());
  }
  const managedIPs = new Set(targets.map(t => t.ip_address).filter(Boolean) as string[]);
  const unmanaged = devices.filter(d =>
    !d.compile_target &&
    !managedDeviceNames.has(d.name.toLowerCase()) &&
    !(d.ip_address && managedIPs.has(d.ip_address))
  );
  const defaultSortedTargets = [...targets].sort((a, b) => a.target.localeCompare(b.target));
  const defaultSortedUnmanaged = [...unmanaged].sort((a, b) => a.name.localeCompare(b.name));

  const baseFilteredTargets = filter
    ? defaultSortedTargets.filter(t =>
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
    : defaultSortedTargets;

  const baseFilteredUnmanaged = filter
    ? defaultSortedUnmanaged.filter(d =>
        matchesFilter(
          filter,
          d.name,
          stripYaml(d.name),
          d.online ? 'online' : 'offline',
          d.ip_address,
          d.running_version,
        )
      )
    : defaultSortedUnmanaged;

  // Apply column sort on top of filter
  const getTargetValue = (t: Target): string => {
    if (sort.col === 'device') return t.friendly_name || t.device_name || stripYaml(t.target);
    if (sort.col === 'status') return t.online == null ? 'unknown' : t.online ? 'online' : 'offline';
    if (sort.col === 'ha') return t.ha_configured ? 'yes' : '';
    if (sort.col === 'ip') return t.ip_address || '';
    if (sort.col === 'running') return t.running_version || '';
    return '';
  };
  const getUnmanagedValue = (d: Device): string => {
    if (sort.col === 'device') return d.name;
    if (sort.col === 'status') return d.online ? 'online' : 'offline';
    if (sort.col === 'ha') return '';
    if (sort.col === 'ip') return d.ip_address || '';
    if (sort.col === 'running') return d.running_version || '';
    return '';
  };

  const filteredTargets = sort.dir
    ? sortedItems(baseFilteredTargets, getTargetValue)
    : baseFilteredTargets;
  const filteredUnmanaged = sort.dir
    ? sortedItems(baseFilteredUnmanaged, getUnmanagedValue)
    : baseFilteredUnmanaged;

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
                &times;
              </button>
            )}
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th><input type="checkbox" ref={selectAllRef} onChange={handleSelectAll} /></th>
                <SortableHeader label="Device" col="device" sort={sort} onSort={handleSort} />
                <SortableHeader label="Status" col="status" sort={sort} onSort={handleSort} />
                <SortableHeader label="HA" col="ha" sort={sort} onSort={handleSort} />
                <SortableHeader label="IP" col="ip" sort={sort} onSort={handleSort} />
                <SortableHeader label="Running" col="running" sort={sort} onSort={handleSort} />
                <th></th>
              </tr>
            </thead>
            <tbody ref={tbodyRef}>
              {!hasResults ? (
                <tr className="empty-row">
                  <td colSpan={7}>
                    {filter
                      ? 'No devices match your search'
                      : 'No devices found — ensure ESPHome configs are in /config/esphome/'}
                  </td>
                </tr>
              ) : (
                <>
                  {filteredTargets.map(t => (
                    <TargetRow
                      key={t.target}
                      target={t}
                      onCompile={onCompile}
                      onEdit={onEdit}
                      onLogs={onLogs}
                      onToast={onToast}
                      onDelete={setDeleteTarget}
                      onRename={setRenameTarget}
                    />
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

      {renameTarget && (
        <RenameModal
          currentName={renameTarget}
          onConfirm={newName => {
            const target = renameTarget;
            setRenameTarget(null);
            onRename(target, newName);
          }}
          onClose={() => setRenameTarget(null)}
        />
      )}

      {deleteTarget && (
        <DeleteModal
          target={deleteTarget}
          onConfirm={archive => {
            const target = deleteTarget;
            setDeleteTarget(null);
            onDelete(target, archive);
          }}
          onClose={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}

function DeviceMenu({
  target: t,
  onToast,
  onDelete,
  onRename,
  onLogs,
}: {
  target: Target;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
  onDelete: (target: string) => void;
  onRename: (target: string) => void;
  onLogs: (target: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Close on click outside
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  async function handleCopyApiKey() {
    setOpen(false);
    try {
      const key = await getApiKey(t.target);
      await navigator.clipboard.writeText(key);
      onToast('API key copied!', 'success');
    } catch {
      onToast('No API key found', 'info');
    }
  }

  async function handleRestart() {
    setOpen(false);
    try {
      await restartDevice(t.target);
      onToast(`Restarting ${stripYaml(t.target)}...`, 'success');
    } catch (err) {
      onToast('Restart failed: ' + (err as Error).message, 'error');
    }
  }

  function handleLogs() {
    setOpen(false);
    onLogs(t.target);
  }

  function handleRename() {
    setOpen(false);
    onRename(t.target);
  }

  function handleDelete() {
    setOpen(false);
    onDelete(t.target);
  }

  return (
    <div className="action-menu-wrap" ref={wrapRef}>
      <span
        className="action-menu-trigger"
        onClick={() => setOpen(o => !o)}
        title="More actions"
      >
        &#8942;
      </span>
      <div className={`action-menu-dropdown${open ? ' open' : ''}`}>
        <button
          className="action-menu-item"
          onClick={handleLogs}
          title="Stream live device logs"
        >
          Live Logs
        </button>
        <button
          className="action-menu-item"
          onClick={handleRestart}
          title="Restart this device"
        >
          Restart Device
        </button>
        <button
          className="action-menu-item"
          onClick={handleCopyApiKey}
          disabled={!t.has_api_key}
          title={t.has_api_key ? 'Copy API encryption key' : 'No API key configured'}
        >
          Copy API Key
        </button>
        <button
          className="action-menu-item"
          onClick={handleRename}
          title="Rename this device config"
        >
          Rename
        </button>
        <button
          className="action-menu-item"
          onClick={handleDelete}
          title="Delete this device config"
          style={{ color: 'var(--danger, #ef4444)' }}
        >
          Delete
        </button>
      </div>
    </div>
  );
}

function TargetRow({
  target: t,
  onCompile,
  onEdit,
  onLogs,
  onToast,
  onDelete,
  onRename,
}: {
  target: Target;
  onCompile: (targets: string[]) => void;
  onEdit: (target: string) => void;
  onLogs: (target: string) => void;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
  onDelete: (target: string) => void;
  onRename: (target: string) => void;
}) {
  let lastSeenEl: React.ReactNode = null;
  if (t.last_seen) {
    lastSeenEl = <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{timeAgo(t.last_seen)}</div>;
  }

  let statusEl: React.ReactNode;
  if (t.online == null) {
    statusEl = <><span className="dot dot-checking"></span><span style={{ color: 'var(--text-muted)' }}>Checking...</span></>;
  } else if (t.online) {
    statusEl = <><span className="dot dot-online"></span>Online{lastSeenEl}</>;
  } else {
    statusEl = <><span className="dot dot-offline"></span>Offline{lastSeenEl}</>;
  }

  const upgradeBtnCls = t.needs_update ? 'btn-success' : 'btn-secondary';
  const displayName = t.friendly_name || t.device_name || stripYaml(t.target);
  const showIpLink = t.has_web_server && t.online && t.ip_address;

  const haCell: React.ReactNode = t.ha_configured
    ? <span style={{ color: 'var(--success)' }}>Yes</span>
    : <span style={{ color: 'var(--text-muted)' }}>—</span>;

  return (
    <tr>
      <td><input type="checkbox" className="target-cb" value={t.target} /></td>
      <td>
        <span className="device-name">{displayName}</span>
        <div className="device-filename">{stripYaml(t.target)}</div>
        {t.comment && <div className="device-comment">{t.comment}</div>}
      </td>
      <td>{statusEl}</td>
      <td style={{ fontSize: 12 }}>{haCell}</td>
      <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
        {showIpLink
          ? (
            <a
              href={`http://${t.ip_address}`}
              target="_blank"
              rel="noopener"
              className="ip-link"
            >
              {t.ip_address}<span style={{ fontSize: 10 }}>&#8599;</span>
            </a>
          )
          : <span style={{ color: 'var(--text-muted)' }}>{t.ip_address || '—'}</span>}
      </td>
      <td style={{ fontSize: 12 }}>
        {t.running_version || '—'}
        {t.config_modified && <div className="config-modified">config changed</div>}
      </td>
      <td>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <button className={`${upgradeBtnCls} btn-sm`} onClick={() => onCompile([t.target])}>Upgrade</button>
          <button className="btn-secondary btn-sm" onClick={() => onEdit(t.target)}>Edit</button>
          <DeviceMenu target={t} onToast={onToast} onDelete={onDelete} onRename={onRename} onLogs={onLogs} />
        </div>
      </td>
    </tr>
  );
}

function UnmanagedRow({ device: d }: { device: Device }) {
  const statusEl = d.online
    ? <><span className="dot dot-online"></span>Online</>
    : <><span className="dot dot-offline"></span>Offline</>;

  // Unmanaged devices (no config) don't have web_server info — never link their IP
  return (
    <tr>
      <td></td>
      <td>
        <span className="device-name" style={{ color: 'var(--text-muted)' }}>{stripYaml(d.name)}</span>
        <div className="device-filename" style={{ color: '#6b7280' }}>No config</div>
      </td>
      <td>{statusEl}</td>
      <td style={{ fontSize: 12 }}><span style={{ color: 'var(--text-muted)' }}>—</span></td>
      <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
        <span style={{ color: 'var(--text-muted)' }}>{d.ip_address || '—'}</span>
      </td>
      <td style={{ fontSize: 12 }}>{d.running_version || '—'}</td>
      <td></td>
    </tr>
  );
}
