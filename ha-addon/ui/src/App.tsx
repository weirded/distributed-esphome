import { useCallback, useEffect, useRef, useState } from 'react';
import {
  cancelJobs,
  clearQueue,
  compile,
  disableWorker,
  getDevices,
  getEsphomeVersions,
  getInitialAddonVersion,
  getQueue,
  getServerInfo,
  getTargets,
  getWorkers,
  removeWorker,
  renameTarget,
  retryAllFailed,
  retryJobs,
  setEsphomeVersion,
  setInitialAddonVersion,
  setToastFn,
  validateConfig,
} from './api/client';
import { ConnectWorkerModal } from './components/ConnectWorkerModal';
import { DevicesTab } from './components/DevicesTab';
import { EditorModal } from './components/EditorModal';
import { EsphomeVersionDropdown } from './components/EsphomeVersionDropdown';
import { LogModal } from './components/LogModal';
import { QueueTab } from './components/QueueTab';
import { ToastContainer, useToast } from './components/Toast';
import { WorkersTab } from './components/WorkersTab';
import type { Device, EsphomeVersions, Job, ServerInfo, Target, Worker } from './types';
import { stripYaml } from './utils';
import './theme.css';

type TabName = 'devices' | 'queue' | 'workers';

function getTabCount(
  tab: TabName,
  targets: Target[],
  devices: Device[],
  queue: Job[],
  workers: Worker[],
): string {
  if (tab === 'devices') {
    const unmanaged = devices.filter(d => !d.compile_target);
    const totalOnline = targets.filter(t => t.online).length + unmanaged.filter(d => d.online).length;
    const totalKnown = targets.filter(t => t.online != null).length + unmanaged.length;
    return totalKnown ? `${totalOnline}/${totalKnown}` : String(targets.length || '');
  }
  if (tab === 'queue') {
    const active = queue.filter(j => ['pending', 'working'].includes(j.state)).length;
    const failed = queue.filter(j => ['failed', 'timed_out'].includes(j.state)).length;
    if (active) return `${active} active`;
    if (failed) return `${failed} failed`;
    if (queue.length) return `${queue.length} done`;
    return '';
  }
  if (tab === 'workers') {
    const online = workers.filter(c => c.online).length;
    return `${online}/${workers.length}`;
  }
  return '';
}

function getInitialTheme(): 'dark' | 'light' {
  const stored = localStorage.getItem('theme');
  if (stored === 'light' || stored === 'dark') return stored;
  return 'dark';
}

export default function App() {
  const [activeTab, setActiveTab] = useState<TabName>(
    () => (sessionStorage.getItem('activeTab') as TabName) || 'devices',
  );
  const [serverInfo, setServerInfo] = useState<ServerInfo>({ token: '', port: 8765 });
  const [targets, setTargets] = useState<Target[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [queue, setQueue] = useState<Job[]>([]);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [esphomeVersions, setEsphomeVersions] = useState<EsphomeVersions>({
    selected: null,
    detected: null,
    available: [],
  });

  const [theme, setTheme] = useState<'dark' | 'light'>(getInitialTheme);

  const [versionDropdownOpen, setVersionDropdownOpen] = useState(false);
  const [logJobId, setLogJobId] = useState<string | null>(null);
  const [editorTarget, setEditorTarget] = useState<string | null>(null);
  const [connectModalOpen, setConnectModalOpen] = useState(false);

  // Apply theme to <html> element on mount and on change
  useEffect(() => {
    if (theme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem('theme', theme);
  }, [theme]);

  const { items: toastItems, addToast, removeToast } = useToast();

  // Wire toast function into API client for auto-reload toasts
  useEffect(() => {
    setToastFn(addToast);
  }, [addToast]);

  // ---- Data fetchers ----

  const fetchServerInfo = useCallback(async () => {
    try {
      const info = await getServerInfo();
      setServerInfo(info);
      if (info.addon_version) {
        const prev = getInitialAddonVersion();
        setInitialAddonVersion(info.addon_version);
        if (prev !== null && info.addon_version !== prev) {
          addToast('New version detected — reloading...', 'info');
          setTimeout(() => location.reload(), 1500);
        }
      }
    } catch { /* ignore */ }
  }, [addToast]);

  const fetchEsphomeVersions = useCallback(async () => {
    try {
      const data = await getEsphomeVersions();
      setEsphomeVersions(data);
    } catch { /* ignore */ }
  }, []);

  const fetchWorkers = useCallback(async () => {
    try {
      const data = await getWorkers();
      setWorkers(data);
    } catch { /* ignore */ }
  }, []);

  const fetchDevicesAndTargets = useCallback(async () => {
    try {
      const [tData, dData] = await Promise.all([getTargets(), getDevices()]);
      setTargets(tData);
      setDevices(dData);
    } catch { /* ignore */ }
  }, []);

  const fetchQueue = useCallback(async () => {
    try {
      const data = await getQueue();
      setQueue(data);
    } catch { /* ignore */ }
  }, []);

  // ---- Initial load + polling ----
  // Use refs so the effect runs exactly once (no re-creation of intervals)
  const fetchersRef = useRef({ fetchServerInfo, fetchEsphomeVersions, fetchWorkers, fetchDevicesAndTargets, fetchQueue });
  fetchersRef.current = { fetchServerInfo, fetchEsphomeVersions, fetchWorkers, fetchDevicesAndTargets, fetchQueue };

  useEffect(() => {
    const f = fetchersRef.current;
    f.fetchServerInfo();
    f.fetchEsphomeVersions();
    f.fetchWorkers();
    f.fetchDevicesAndTargets();
    f.fetchQueue();

    const intervals = [
      setInterval(() => fetchersRef.current.fetchServerInfo(), 30_000),
      setInterval(() => fetchersRef.current.fetchEsphomeVersions(), 15 * 60_000),
      setInterval(() => fetchersRef.current.fetchWorkers(), 5_000),
      setInterval(() => fetchersRef.current.fetchDevicesAndTargets(), 15_000),
      setInterval(() => fetchersRef.current.fetchQueue(), 3_000),
    ];
    return () => intervals.forEach(clearInterval);
  }, []);

  // Close version dropdown on outside click
  useEffect(() => {
    if (!versionDropdownOpen) return;
    function handler() { setVersionDropdownOpen(false); }
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [versionDropdownOpen]);

  // ---- Tab navigation ----

  function switchTab(name: TabName) {
    setActiveTab(name);
    sessionStorage.setItem('activeTab', name);
  }

  // ---- Actions ----

  async function handleCompile(targets_: string[] | 'all' | 'outdated') {
    try {
      const data = await compile(targets_);
      addToast(`Queued ${data.enqueued} device(s)`, 'success');
      switchTab('queue');
      await fetchQueue();
    } catch (err) {
      addToast('Error: ' + (err as Error).message, 'error');
    }
  }

  async function handleValidate(target: string) {
    try {
      const result = await validateConfig(target);
      const jobId = result.job_id;
      addToast(`Validating ${stripYaml(target)}...`, 'info');
      await fetchQueue();

      // Poll for validation result (completes in 2-5 seconds)
      if (jobId) {
        const pollForResult = async () => {
          for (let i = 0; i < 30; i++) { // up to 30 seconds
            await new Promise(r => setTimeout(r, 1000));
            const latestQueue = await getQueue();
            setQueue(latestQueue);
            const latestJob = latestQueue.find((j: Job) => j.id === jobId);
            if (!latestJob) break;
            if (latestJob.state === 'success' && latestJob.validate_only) {
              addToast(`${stripYaml(target)} is valid`, 'success');
              return;
            }
            if (latestJob.state === 'failed') {
              addToast(`Validation failed for ${stripYaml(target)} — check log for details`, 'error');
              setLogJobId(jobId);
              return;
            }
          }
        };
        pollForResult().catch(() => {});
      }
    } catch (err) {
      addToast('Validate failed: ' + (err as Error).message, 'error');
    }
  }

  async function handleCancelJobs(ids: string[]) {
    try {
      const data = await cancelJobs(ids);
      if (data.cancelled > 0) {
        const msg = data.cancelled === 1
          ? `Cancelled ${stripYaml(queue.find(j => j.id === ids[0])?.target ?? ids[0])}`
          : `Cancelled ${data.cancelled} jobs`;
        addToast(msg, 'success');
      }
      await fetchQueue();
    } catch (err) {
      addToast('Error: ' + (err as Error).message, 'error');
    }
  }

  async function handleRetryJobs(ids: string[]) {
    try {
      const data = await retryJobs(ids);
      if (data.retried > 0) {
        const msg = data.retried === 1
          ? `Retrying ${stripYaml(queue.find(j => j.id === ids[0])?.target ?? ids[0])}`
          : `Retrying ${data.retried} jobs`;
        addToast(msg, 'success');
      }
      await fetchQueue();
    } catch (err) {
      addToast('Error: ' + (err as Error).message, 'error');
    }
  }

  async function handleRetryAllFailed() {
    try {
      const data = await retryAllFailed();
      if (data.retried > 0) {
        const msg = data.retried === 1 ? 'Retrying 1 job' : `Retrying ${data.retried} failed jobs`;
        addToast(msg, 'success');
      }
      await fetchQueue();
    } catch (err) {
      addToast('Error: ' + (err as Error).message, 'error');
    }
  }

  async function handleClearSucceeded() {
    try {
      const data = await clearQueue(['success'], true);
      if (data.cleared > 0) {
        const msg = data.cleared === 1 ? 'Cleared 1 succeeded job' : `Cleared ${data.cleared} succeeded jobs`;
        addToast(msg, 'success');
      }
      await fetchQueue();
    } catch {
      addToast('Clear failed', 'error');
    }
  }

  async function handleClearFinished() {
    try {
      const data = await clearQueue(['success', 'failed', 'timed_out']);
      if (data.cleared > 0) {
        const msg = data.cleared === 1 ? 'Cleared 1 finished job' : `Cleared ${data.cleared} finished jobs`;
        addToast(msg, 'success');
      }
      await fetchQueue();
    } catch {
      addToast('Clear failed', 'error');
    }
  }

  async function handleDisableWorker(id: string, disabled: boolean) {
    try {
      await disableWorker(id, disabled);
      addToast(disabled ? 'Worker disabled' : 'Worker enabled', 'success');
      await fetchWorkers();
    } catch {
      addToast('Error toggling worker', 'error');
    }
  }

  async function handleRemoveWorker(id: string) {
    try {
      await removeWorker(id);
      addToast('Worker removed', 'success');
      await fetchWorkers();
    } catch (err) {
      addToast('Error: ' + (err as Error).message, 'error');
    }
  }

  async function handleDeleteDevice() {
    // The actual delete API call, confirmation dialog, and toast are handled
    // inside DeviceMenu so they execute close to the user's click. This
    // callback only needs to refresh the device list.
    await fetchDevicesAndTargets();
  }

  async function handleRenameDevice(target: string) {
    const newName = window.prompt('New device name:', stripYaml(target));
    if (!newName) return;
    try {
      const result = await renameTarget(target, newName);
      addToast(`Renamed to ${stripYaml(result.new_filename)}`, 'success');
      await fetchDevicesAndTargets();
    } catch (err) {
      addToast('Rename failed: ' + (err as Error).message, 'error');
    }
  }

  async function handleSelectEsphomeVersion(version: string) {
    setVersionDropdownOpen(false);
    try {
      await setEsphomeVersion(version);
      setEsphomeVersions(prev => ({ ...prev, selected: version }));
      addToast('ESPHome version set to ' + version, 'success');
    } catch (err) {
      addToast('Failed to set version: ' + (err as Error).message, 'error');
    }
  }

  function handleVersionDropdownToggle(e: React.MouseEvent) {
    e.stopPropagation();
    setVersionDropdownOpen(prev => !prev);
  }

  // ---- Render ----

  const devicesCount = getTabCount('devices', targets, devices, queue, workers);
  const queueCount = getTabCount('queue', targets, devices, queue, workers);
  const workersCount = getTabCount('workers', targets, devices, queue, workers);

  // Seed version for connect modal: prefer selected esphome version, fall back to server_version field
  const seedVersion = esphomeVersions.selected ||
    (targets.length > 0 ? (targets[0].server_version ?? null) : null);

  return (
    <>
      <header>
        <img
          src="https://media.esphome.io/logo/logo-text-on-dark.svg"
          alt="ESPHome"
          height={26}
          style={{ display: 'block', flexShrink: 0 }}
        />
        <span style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
          Distributed Build
        </span>
        <span className="version-badge">
          {serverInfo.addon_version ? `v${serverInfo.addon_version}` : 'v?'}
        </span>
        <EsphomeVersionDropdown
          versions={esphomeVersions}
          open={versionDropdownOpen}
          onToggle={handleVersionDropdownToggle}
          onSelect={handleSelectEsphomeVersion}
        />
        <span
          className="version-badge"
          style={{ cursor: 'pointer' }}
          onClick={() => setEditorTarget('secrets.yaml')}
          title="Edit secrets.yaml"
        >
          Secrets
        </span>
        <span
          className="version-badge"
          style={{ cursor: 'pointer', fontSize: 13 }}
          onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {theme === 'dark' ? '☀' : '☾'}
        </span>
        <span className="spacer" />
        <span className="status-dot" title="Server online" />
      </header>

      <nav className="tab-bar">
        {(['devices', 'queue', 'workers'] as TabName[]).map(tab => (
          <button
            key={tab}
            className={`tab${activeTab === tab ? ' active' : ''}`}
            onClick={() => switchTab(tab)}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}{' '}
            <span className="tab-count">
              {tab === 'devices' ? devicesCount : tab === 'queue' ? queueCount : workersCount}
            </span>
          </button>
        ))}
      </nav>

      <main>
        {activeTab === 'devices' && (
          <DevicesTab
            targets={targets}
            devices={devices}
            onCompile={handleCompile}
            onEdit={setEditorTarget}
            onToast={addToast}
            onDelete={handleDeleteDevice}
            onRename={handleRenameDevice}
          />
        )}
        {activeTab === 'queue' && (
          <QueueTab
            queue={queue}
            workers={workers}
            onCancel={handleCancelJobs}
            onRetry={handleRetryJobs}
            onRetryAllFailed={handleRetryAllFailed}
            onClearSucceeded={handleClearSucceeded}
            onClearFinished={handleClearFinished}
            onOpenLog={setLogJobId}
          />
        )}
        {activeTab === 'workers' && (
          <WorkersTab
            workers={workers}
            queue={queue}
            serverClientVersion={serverInfo.server_client_version}
            onDisable={handleDisableWorker}
            onRemove={handleRemoveWorker}
            onConnectWorker={() => setConnectModalOpen(true)}
          />
        )}
      </main>

      <ToastContainer items={toastItems} onRemove={removeToast} />

      <LogModal
        jobId={logJobId}
        queue={queue}
        workers={workers}
        onClose={() => setLogJobId(null)}
        onRetry={handleRetryJobs}
      />

      {editorTarget && (
        <EditorModal
          target={editorTarget}
          onClose={() => setEditorTarget(null)}
          onToast={addToast}
          onValidate={handleValidate}
          monacoTheme={theme === 'light' ? 'vs' : 'vs-dark'}
          esphomeVersion={esphomeVersions.selected ?? esphomeVersions.detected ?? undefined}
        />
      )}

      {connectModalOpen && (
        <ConnectWorkerModal
          serverInfo={serverInfo}
          esphomeVersion={seedVersion}
          onClose={() => setConnectModalOpen(false)}
        />
      )}
    </>
  );
}
