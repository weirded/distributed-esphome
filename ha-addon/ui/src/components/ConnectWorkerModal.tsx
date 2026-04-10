import { useEffect, useRef, useState } from 'react';
import type { ServerInfo, WorkerPreset } from '../types';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Select } from './ui/select';

interface Props {
  serverInfo: ServerInfo;
  esphomeVersion: string | null;
  onClose: () => void;
  /** Pre-populate fields when reconnecting an existing worker (bug #7). */
  preset?: WorkerPreset | null;
}

type Shell = 'bash' | 'powershell';

function buildDockerCmd(params: {
  serverUrl: string;
  token: string;
  containerName: string;
  hostname: string;
  maxJobs: number;
  seedVersion: string;
  hostPlatform: string;
  restartPolicy: string;
  clientTag: string;
  shell: Shell;
}): string {
  const {
    serverUrl, token, containerName, hostname, maxJobs,
    seedVersion, hostPlatform, restartPolicy, clientTag, shell,
  } = params;

  const cont = shell === 'powershell' ? '`' : '\\';
  const hostnameVar = shell === 'powershell' ? '$env:COMPUTERNAME' : '$(hostname)';

  const lines = [`docker run -d ${cont}`];
  lines.push(`  --name ${containerName} ${cont}`);
  if (restartPolicy !== 'no') {
    lines.push(`  --restart ${restartPolicy} ${cont}`);
  }
  lines.push(`  --hostname ${hostname || hostnameVar} ${cont}`);
  lines.push(`  -e SERVER_URL=${serverUrl} ${cont}`);
  lines.push(`  -e SERVER_TOKEN=${token} ${cont}`);
  lines.push(`  -e MAX_PARALLEL_JOBS=${maxJobs} ${cont}`);
  if (seedVersion) {
    lines.push(`  -e ESPHOME_SEED_VERSION=${seedVersion} ${cont}`);
  }
  if (hostPlatform) {
    lines.push(`  -e HOST_PLATFORM=${JSON.stringify(hostPlatform)} ${cont}`);
  }
  lines.push(`  -v esphome-versions:/esphome-versions ${cont}`);
  lines.push(`  ghcr.io/weirded/esphome-dist-client:${clientTag}`);

  return lines.join('\n');
}

export function ConnectWorkerModal({ serverInfo, esphomeVersion, onClose, preset }: Props) {
  const port = serverInfo.port || 8765;
  const addrs = serverInfo.server_addresses?.length
    ? serverInfo.server_addresses
    : [serverInfo.server_ip || window.location.hostname];
  const urlOptions = addrs.map(addr => `http://${addr}:${port}`);

  const [serverUrl, setServerUrl] = useState(urlOptions[0] || '');
  const [containerName, setContainerName] = useState('distributed-esphome-worker');
  // preset fields pre-populate when reconnecting an existing worker (bug #7).
  // We read them once at mount and don't sync later — the modal is short-lived
  // and a mid-edit prop change would be surprising.
  const [hostname, setHostname] = useState(preset?.hostname ?? '');
  const [maxJobs, setMaxJobs] = useState(preset?.max_parallel_jobs ?? 2);
  const [seedVersion, setSeedVersion] = useState(esphomeVersion || '');
  const seedUserEdited = useRef(false);
  const [hostPlatform, setHostPlatform] = useState(preset?.host_platform ?? '');
  const [restartPolicy, setRestartPolicy] = useState('unless-stopped');
  const [shell, setShell] = useState<Shell>('bash');
  const [copied, setCopied] = useState(false);

  // Sync seed version from props unless user manually edited it
  useEffect(() => {
    if (!seedUserEdited.current && esphomeVersion) {
      setSeedVersion(esphomeVersion);
    }
  }, [esphomeVersion]);

  // Keep server URL dropdown in sync when addresses change
  useEffect(() => {
    if (!urlOptions.includes(serverUrl)) {
      setServerUrl(urlOptions[0] || '');
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverInfo.server_addresses, serverInfo.server_ip, serverInfo.port]);

  const clientTag = serverInfo.addon_version || 'latest';
  const dockerCmd = buildDockerCmd({
    serverUrl,
    token: serverInfo.token || '',
    containerName,
    hostname,
    maxJobs,
    seedVersion,
    hostPlatform,
    restartPolicy,
    clientTag,
    shell,
  });

  function handleCopy() {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(dockerCmd).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      });
    } else {
      const ta = document.createElement('textarea');
      ta.value = dockerCmd;
      ta.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent style={{ maxWidth: 720 }}>
        <DialogHeader>
          <DialogTitle>Connect a Build Worker</DialogTitle>
        </DialogHeader>
        <div className="p-[18px]">
          <div className="connect-form">
            <div>
              <label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1">Server URL</label>
              <Select value={serverUrl} onChange={e => setServerUrl(e.target.value)}>
                {urlOptions.map(u => <option key={u} value={u}>{u}</option>)}
              </Select>
            </div>
            <div>
              <label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1">Server Token</label>
              <Input
                className="sensitive text-[var(--text-muted)] cursor-default"
                type="text"
                value={serverInfo.token || ''}
                readOnly
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1">Container Name</label>
              <Input
                type="text"
                value={containerName}
                onChange={e => setContainerName(e.target.value)}
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1">Hostname</label>
              <Input
                type="text"
                value={hostname}
                placeholder="$(hostname)"
                onChange={e => setHostname(e.target.value)}
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1">Max Parallel Jobs</label>
              <Input
                type="number"
                value={maxJobs}
                min={1}
                max={8}
                onChange={e => setMaxJobs(parseInt(e.target.value, 10) || 2)}
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1">ESPHome Seed Version</label>
              <Input
                type="text"
                value={seedVersion}
                onChange={e => { seedUserEdited.current = true; setSeedVersion(e.target.value); }}
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1">
                Host Platform{' '}
                <span className="text-[var(--text-muted)] font-normal normal-case">(optional)</span>
              </label>
              <Input
                type="text"
                value={hostPlatform}
                placeholder="e.g. macOS 15.3 (Apple M1 Pro)"
                onChange={e => setHostPlatform(e.target.value)}
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1">Restart Policy</label>
              <Select value={restartPolicy} onChange={e => setRestartPolicy(e.target.value)}>
                <option value="unless-stopped">unless-stopped</option>
                <option value="always">always</option>
                <option value="no">no</option>
              </Select>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.03em' }}>Shell</span>
            <div style={{ display: 'flex', gap: 0, border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
              <Button
                variant={shell === 'bash' ? 'default' : 'secondary'}
                size="sm"
                style={{ borderRadius: 0, border: 'none' }}
                onClick={() => setShell('bash')}
              >
                Bash
              </Button>
              <Button
                variant={shell === 'powershell' ? 'default' : 'secondary'}
                size="sm"
                style={{ borderRadius: 0, border: 'none', borderLeft: '1px solid var(--border)' }}
                onClick={() => setShell('powershell')}
              >
                PowerShell
              </Button>
            </div>
          </div>
          <div className="docker-cmd-wrap">
            <pre className="docker-cmd sensitive">{dockerCmd}</pre>
            <Button variant="secondary" size="sm" className="docker-cmd-copy" onClick={handleCopy}>
              {copied ? 'Copied!' : 'Copy'}
            </Button>
          </div>
          <p style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 12 }}>
            Run this command on any Docker host that has network access to your ESP devices (port 3232 for OTA).
            The worker will poll this server for build jobs, compile firmware, and push updates directly to your devices.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
