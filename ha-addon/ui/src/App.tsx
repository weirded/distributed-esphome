import { useCallback, useEffect, useMemo, useState } from 'react';
import useSWR from 'swr';
import {
  cancelJobs,
  cleanWorkerCache,
  clearQueue,
  compile,
  deleteTarget,

  removeJobs,
  getDevices,
  getEsphomeVersions,
  getInitialAddonVersion,
  getQueue,
  getServerInfo,
  getTargets,
  getWorkers,
  removeWorker,
  renameTarget,
  setWorkerParallelJobs,
  retryAllFailed,
  retryJobs,
  setEsphomeVersion,
  setInitialAddonVersion,
  validateConfig,
  setTargetSchedule,
  deleteTargetSchedule,
  toggleTargetSchedule,
} from './api/client';
import { ConnectWorkerModal } from './components/ConnectWorkerModal';
import { DeviceLogModal } from './components/DeviceLogModal';
import { DevicesTab, RenameModal } from './components/DevicesTab';
import { UpgradeModal } from './components/UpgradeModal';
import { ScheduleModal } from './components/ScheduleModal';
import { EditorModal } from './components/EditorModal';
import { EsphomeVersionDropdown } from './components/EsphomeVersionDropdown';
import { LogModal } from './components/LogModal';
import { QueueTab } from './components/QueueTab';
import { toast } from 'sonner';
import { Toaster } from './components/ui/sonner';
import { WorkersTab } from './components/WorkersTab';
import type { Device, Job, Target, Worker } from './types';
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
    return '0';
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
  // Deep compare prevents re-renders when polled data hasn't changed structurally
  const deepCompare = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

  const { data: serverInfo = { token: '', port: 8765 } } = useSWR(
    'serverInfo',
    getServerInfo,
    { refreshInterval: 30_000, onError: () => {}, compare: deepCompare },
  );
  const { data: esphomeVersions = { selected: null, detected: null, available: [] }, mutate: mutateEsphomeVersions } = useSWR(
    'versions',
    getEsphomeVersions,
    { refreshInterval: 15 * 60_000, onError: () => {}, compare: deepCompare },
  );
  // Poll at 1 Hz for live-feeling updates. Workers + queue are pure in-memory
  // reads. Targets/devices does a readdir + per-target stat() for mtime cache
  // checks (metadata resolution is cached and only re-fires when a file
  // changes), which is cheap on Linux but not free — if this becomes a
  // concern on large config dirs, add a server-side snapshot cache.
  const { data: workers = [], mutate: mutateWorkers } = useSWR(
    'workers',
    getWorkers,
    { refreshInterval: 1_000, onError: () => {}, compare: deepCompare },
  );
  const { data: devicesAndTargets, mutate: mutateDevices } = useSWR(
    'devices',
    async () => { const [t, d] = await Promise.all([getTargets(), getDevices()]); return { targets: t, devices: d }; },
    { refreshInterval: 1_000, onError: () => {}, compare: deepCompare },
  );
  const targets = devicesAndTargets?.targets ?? [];
  const devices = devicesAndTargets?.devices ?? [];
  const { data: queue = [], mutate: mutateQueue } = useSWR(
    'queue',
    getQueue,
    { refreshInterval: 1_000, onError: () => {}, compare: deepCompare },
  );
  // Exclude validation-only jobs from display (they run server-side and auto-prune)
  const displayQueue = useMemo(() => queue.filter(j => !j.validate_only), [queue]);
  // Map of target filename → active (PENDING or WORKING) job, used by the
  // Devices tab to render an "Upgrading…" status on rows whose compile is
  // currently in flight (#32). The most recent active job wins if a target
  // somehow has more than one — the queue dedupes by target so this should
  // be at most one in practice.
  const activeJobsByTarget = useMemo(() => {
    const map = new Map<string, typeof displayQueue[number]>();
    for (const j of displayQueue) {
      if (j.state === 'pending' || j.state === 'working') {
        map.set(j.target, j);
      }
    }
    return map;
  }, [displayQueue]);

  const [theme, setTheme] = useState<'dark' | 'light'>(getInitialTheme);
  const [streamerMode, setStreamerMode] = useState(() => localStorage.getItem('streamerMode') === 'true');

  useEffect(() => {
    document.documentElement.classList.toggle('streamer', streamerMode);
    localStorage.setItem('streamerMode', String(streamerMode));
  }, [streamerMode]);

  const [logJobId, setLogJobId] = useState<string | null>(null);
  const [deviceLogTarget, setDeviceLogTarget] = useState<string | null>(null);
  const [editorTarget, setEditorTarget] = useState<string | null>(null);
  const [connectModalOpen, setConnectModalOpen] = useState(false);
  const [connectModalPreset, setConnectModalPreset] = useState<import('./types').WorkerPreset | null>(null);
  // #16: per-target Upgrade modal. Stores the target filename + display name.
  const [upgradeModalTarget, setUpgradeModalTarget] = useState<{ target: string; displayName: string } | null>(null);
  const [scheduleModalTarget, setScheduleModalTarget] = useState<string | null>(null);
  const [renameModalTarget, setRenameModalTarget] = useState<string | null>(null);

  // Apply theme to <html> element on mount and on change
  useEffect(() => {
    if (theme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem('theme', theme);
  }, [theme]);

  // Helper to match the old addToast(msg, type) pattern
  const addToast = useCallback((message: string, type: 'info' | 'success' | 'error' = 'info') => {
    if (type === 'success') toast.success(message);
    else if (type === 'error') toast.error(message);
    else toast.info(message);
  }, []);

  // ---- Version-change detection ----
  // Track addon version across SWR refreshes; reload the page when it changes.
  useEffect(() => {
    const version = serverInfo.addon_version;
    if (!version) return;
    const prev = getInitialAddonVersion();
    setInitialAddonVersion(version);
    if (prev !== null && version !== prev) {
      addToast('New version detected — reloading...', 'info');
      setTimeout(() => location.reload(), 1500);
    }
  }, [serverInfo.addon_version]); // eslint-disable-line react-hooks/exhaustive-deps

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
      // Mutate BOTH queue and devices: queue so the new job appears on the
      // queue tab immediately, devices so the orange "Upgrading" dot
      // appears on the source row immediately (#11). Without the devices
      // mutate the dot lags by up to one poll interval.
      mutateQueue();
      mutateDevices();
    } catch (err) {
      addToast('Error: ' + (err as Error).message, 'error');
    }
  }

  // #16: open the Upgrade modal for a single target. The modal collects
  // worker + ESPHome version preferences and calls handleUpgradeConfirm.
  function handleOpenUpgradeModal(target: string) {
    const t = targets.find(x => x.target === target);
    const displayName = t?.friendly_name || stripYaml(target);
    setUpgradeModalTarget({ target, displayName });
  }

  async function handleUpgradeConfirm(params: { pinnedClientId: string | null; esphomeVersion: string | null }) {
    const ctx = upgradeModalTarget;
    if (!ctx) return;
    setUpgradeModalTarget(null);
    try {
      await compile([ctx.target], params.pinnedClientId ?? undefined, params.esphomeVersion ?? undefined);
      const versionSuffix = params.esphomeVersion ? ` (ESPHome ${params.esphomeVersion})` : '';
      const workerSuffix = params.pinnedClientId
        ? ` on ${workers.find(w => w.client_id === params.pinnedClientId)?.hostname ?? params.pinnedClientId}`
        : '';
      addToast(`Queued ${ctx.displayName}${workerSuffix}${versionSuffix}`, 'success');
      switchTab('queue');
      mutateQueue();
      mutateDevices();
    } catch (err) {
      addToast('Error: ' + (err as Error).message, 'error');
    }
  }

  // #25/#26: validation result returned directly to the caller (the editor)
  // so it can show the output inline.
  async function handleValidate(target: string): Promise<{ success: boolean; output: string } | null> {
    try {
      return await validateConfig(target);
    } catch (err) {
      addToast('Validate failed: ' + (err as Error).message, 'error');
      return null;
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
      mutateQueue();
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
      mutateQueue();
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
      mutateQueue();
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
      mutateQueue();
    } catch {
      addToast('Clear failed', 'error');
    }
  }

  async function handleClearJobs(ids: string[]) {
    try {
      await removeJobs(ids);
      mutateQueue();
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
      mutateQueue();
    } catch {
      addToast('Clear failed', 'error');
    }
  }


  async function handleCleanWorkerCache(id: string) {
    try {
      await cleanWorkerCache(id);
      const workerName = workers.find(w => w.client_id === id)?.hostname || id;
      addToast(`Clean build cache requested for ${workerName}`, 'success');
      // #11: mutate so the worker's pending_clean flag shows in the UI
      // immediately rather than after the next 1Hz tick.
      mutateWorkers();
    } catch (err) {
      addToast('Error: ' + (err as Error).message, 'error');
    }
  }

  async function handleCleanAllCaches() {
    const onlineWorkers = workers.filter(w => w.online);
    if (!onlineWorkers.length) return;
    try {
      await Promise.all(onlineWorkers.map(w => cleanWorkerCache(w.client_id)));
      addToast(`Clean build cache requested for ${onlineWorkers.length} worker${onlineWorkers.length > 1 ? 's' : ''}`, 'success');
      mutateWorkers();
    } catch (err) {
      addToast('Error: ' + (err as Error).message, 'error');
    }
  }

  async function handleRemoveWorker(id: string) {
    try {
      await removeWorker(id);
      addToast('Worker removed', 'success');
      mutateWorkers();
    } catch (err) {
      addToast('Error: ' + (err as Error).message, 'error');
    }
  }

  async function handleSetParallelJobs(id: string, count: number) {
    try {
      await setWorkerParallelJobs(id, count);
      addToast(`Set to ${count} slot${count !== 1 ? 's' : ''} — worker will restart`, 'success');
      mutateWorkers();
    } catch (err) {
      addToast('Error: ' + (err as Error).message, 'error');
    }
  }

  async function handleDeleteDevice(target: string, archive: boolean) {
    try {
      await deleteTarget(target, archive);
      addToast(`${archive ? 'Archived' : 'Deleted'} ${stripYaml(target)}`, 'success');
      mutateDevices();
    } catch (err) {
      addToast('Delete failed: ' + (err as Error).message, 'error');
    }
  }

  async function handleRenameDevice(oldTarget: string, newName: string) {
    try {
      const result = await renameTarget(oldTarget, newName);
      addToast(`Renamed to ${stripYaml(result.new_filename)} — compiling new firmware...`, 'success');
      mutateDevices();
      mutateQueue();
      switchTab('queue');
    } catch (err) {
      addToast('Rename failed: ' + (err as Error).message, 'error');
    }
  }

  async function handleSelectEsphomeVersion(version: string) {
    try {
      await setEsphomeVersion(version);
      mutateEsphomeVersions({ ...esphomeVersions, selected: version }, false);
      addToast('ESPHome version set to ' + version, 'success');
    } catch (err) {
      addToast('Failed to set version: ' + (err as Error).message, 'error');
    }
  }

  // ---- Render ----

  const devicesCount = getTabCount('devices', targets, devices, displayQueue, workers);
  const queueCount = getTabCount('queue', targets, devices, displayQueue, workers);
  const workersCount = getTabCount('workers', targets, devices, displayQueue, workers);

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
        <span className="rounded-full border border-[var(--border)] bg-[var(--surface2)] px-2 py-0.5 text-[11px] text-[var(--text-muted)] whitespace-nowrap">
          {serverInfo.addon_version ? `v${serverInfo.addon_version}` : 'v?'}
        </span>
        <EsphomeVersionDropdown
          versions={esphomeVersions}
          onSelect={handleSelectEsphomeVersion}
          onRefresh={() => mutateEsphomeVersions()}
        />
        <span
          className="rounded-full border border-[var(--border)] bg-[var(--surface2)] px-2 py-0.5 text-[11px] text-[var(--text-muted)] whitespace-nowrap"
          style={{ cursor: 'pointer' }}
          onClick={() => setEditorTarget('secrets.yaml')}
          title="Edit secrets.yaml"
        >
          Secrets
        </span>
        <span
          className="inline-flex items-center justify-center w-7 h-7 rounded-full border border-[var(--border)] bg-[var(--surface2)] text-[13px] text-[var(--text-muted)] cursor-pointer hover:bg-[var(--border)]"
          onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {theme === 'dark' ? '☀' : '☾'}
        </span>
        <span
          className={`inline-flex items-center justify-center w-7 h-7 rounded-full border border-[var(--border)] bg-[var(--surface2)] text-[13px] cursor-pointer hover:bg-[var(--border)] ${streamerMode ? 'text-[var(--accent)]' : 'text-[var(--text-muted)]'}`}
          onClick={() => setStreamerMode(s => !s)}
          title={streamerMode ? 'Disable streamer mode' : 'Enable streamer mode (blur sensitive data)'}
        >
          {streamerMode ? '🔒' : '👁'}
        </span>
        <span className="spacer" />
        <span className="status-dot" title="Server online" />
      </header>

      <nav className="sticky top-[52px] z-40 flex overflow-x-auto border-b border-[var(--border)] bg-[var(--surface)] px-5">
        {(['devices', 'queue', 'workers'] as TabName[]).map(tab => (
          <button
            key={tab}
            className={`inline-flex items-center gap-1.5 px-4 h-11 bg-transparent border-none border-b-[3px] border-b-transparent text-[13px] font-medium cursor-pointer whitespace-nowrap transition-colors ${activeTab === tab ? 'text-[var(--text)] border-b-[var(--accent)]' : 'text-[var(--text-muted)] hover:text-[var(--text)]'}`}
            onClick={() => switchTab(tab)}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}{' '}
            <span className={`inline-block rounded-full px-1.5 py-px text-[11px] font-semibold ${activeTab === tab ? 'bg-[var(--accent)] text-white' : 'bg-[var(--surface2)] text-[var(--text-muted)]'}`}>
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
            workers={workers}
            streamerMode={streamerMode}
            activeJobsByTarget={activeJobsByTarget}
            onCompile={handleCompile}
            onUpgradeOne={handleOpenUpgradeModal}
            onEdit={setEditorTarget}
            onLogs={setDeviceLogTarget}
            onToast={addToast}
            onDelete={handleDeleteDevice}
            onRename={handleRenameDevice}
            onSchedule={setScheduleModalTarget}
          />
        )}
        {activeTab === 'queue' && (
          <QueueTab
            queue={displayQueue}
            targets={targets}
            workers={workers}
            onCancel={handleCancelJobs}
            onRetry={handleRetryJobs}
            onClear={handleClearJobs}
            onRetryAllFailed={handleRetryAllFailed}
            onClearSucceeded={handleClearSucceeded}
            onClearFinished={handleClearFinished}
            onOpenLog={setLogJobId}
            onEdit={(target) => setEditorTarget(target)}
          />
        )}
        {activeTab === 'workers' && (
          <WorkersTab
            workers={workers}
            queue={displayQueue}
            serverClientVersion={serverInfo.server_client_version}
            minImageVersion={serverInfo.min_image_version}
            onRemove={handleRemoveWorker}
            onSetParallelJobs={handleSetParallelJobs}
            onCleanCache={handleCleanWorkerCache}
            onCleanAllCaches={handleCleanAllCaches}
            onConnectWorker={(preset) => { setConnectModalPreset(preset ?? null); setConnectModalOpen(true); }}
          />
        )}
      </main>

      <Toaster />

      <LogModal
        jobId={logJobId}
        queue={queue}
        workers={workers}
        onClose={() => setLogJobId(null)}
        onRetry={handleRetryJobs}
        onEdit={(target) => { setLogJobId(null); setEditorTarget(target); }}
        stacked={!!editorTarget}
      />

      {deviceLogTarget && (
        <DeviceLogModal
          target={deviceLogTarget}
          onClose={() => setDeviceLogTarget(null)}
        />
      )}

      {editorTarget && (
        <EditorModal
          target={editorTarget}
          onClose={() => { setEditorTarget(null); mutateDevices(); }}
          onToast={addToast}
          onValidate={handleValidate}
          // #18: Save & Upgrade now goes through the same UpgradeModal as
          // the per-row Upgrade button, so the user can pick a worker and
          // ESPHome version before triggering the build. The editor still
          // saves first (in handleSaveAndUpgrade) — this just changes what
          // happens AFTER the save.
          onCompile={(target) => handleOpenUpgradeModal(target)}
          onRename={(target) => { setEditorTarget(null); setRenameModalTarget(target); }}
          monacoTheme={theme === 'light' ? 'vs' : 'vs-dark'}
          esphomeVersion={esphomeVersions.selected ?? esphomeVersions.detected ?? undefined}
        />
      )}

      {connectModalOpen && (
        <ConnectWorkerModal
          serverInfo={serverInfo}
          esphomeVersion={seedVersion}
          preset={connectModalPreset}
          onClose={() => { setConnectModalOpen(false); setConnectModalPreset(null); }}
        />
      )}

      {upgradeModalTarget && (() => {
        const t = targets.find(x => x.target === upgradeModalTarget.target);
        return (
          <UpgradeModal
            target={upgradeModalTarget.target}
            displayName={upgradeModalTarget.displayName}
            workers={workers}
            esphomeVersions={esphomeVersions.available}
            defaultEsphomeVersion={esphomeVersions.selected ?? esphomeVersions.detected ?? null}
            pinnedVersion={t?.pinned_version}
            onConfirm={handleUpgradeConfirm}
            onClose={() => setUpgradeModalTarget(null)}
          />
        );
      })()}

      {scheduleModalTarget && (() => {
        const t = targets.find(x => x.target === scheduleModalTarget);
        const displayName = t?.friendly_name || stripYaml(scheduleModalTarget);
        return (
          <ScheduleModal
            target={scheduleModalTarget}
            displayName={displayName}
            currentSchedule={t?.schedule}
            currentEnabled={t?.schedule_enabled}
            onSave={async (cron) => {
              try {
                await setTargetSchedule(scheduleModalTarget, cron);
                addToast(`Schedule set for ${displayName}`, 'success');
                setScheduleModalTarget(null);
                mutateDevices();
              } catch (err) {
                addToast('Schedule failed: ' + (err as Error).message, 'error');
              }
            }}
            onDelete={async () => {
              try {
                await deleteTargetSchedule(scheduleModalTarget);
                addToast(`Schedule removed for ${displayName}`, 'success');
                setScheduleModalTarget(null);
                mutateDevices();
              } catch (err) {
                addToast('Delete failed: ' + (err as Error).message, 'error');
              }
            }}
            onToggle={async () => {
              try {
                const result = await toggleTargetSchedule(scheduleModalTarget);
                addToast(
                  result.schedule_enabled ? `Schedule enabled for ${displayName}` : `Schedule paused for ${displayName}`,
                  'success',
                );
                mutateDevices();
              } catch (err) {
                addToast('Toggle failed: ' + (err as Error).message, 'error');
              }
            }}
            onClose={() => setScheduleModalTarget(null)}
          />
        );
      })()}

      {renameModalTarget && (
        <RenameModal
          currentName={renameModalTarget}
          onConfirm={newName => {
            const t = renameModalTarget;
            setRenameModalTarget(null);
            handleRenameDevice(t, newName);
          }}
          onClose={() => setRenameModalTarget(null)}
        />
      )}
    </>
  );
}
