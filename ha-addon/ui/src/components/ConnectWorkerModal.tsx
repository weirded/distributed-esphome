import { useEffect, useRef, useState } from 'react';
import type { ServerInfo } from '../types';

interface Props {
  serverInfo: ServerInfo;
  esphomeVersion: string | null;
  onClose: () => void;
}

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
}): string {
  const {
    serverUrl, token, containerName, hostname, maxJobs,
    seedVersion, hostPlatform, restartPolicy, clientTag,
  } = params;

  const lines = ['docker run -d \\'];
  lines.push(`  --name ${containerName} \\`);
  if (restartPolicy !== 'no') {
    lines.push(`  --restart ${restartPolicy} \\`);
  }
  lines.push(`  --hostname ${hostname || '$(hostname)'} \\`);
  lines.push(`  -e SERVER_URL=${serverUrl} \\`);
  lines.push(`  -e SERVER_TOKEN=${token} \\`);
  lines.push(`  -e MAX_PARALLEL_JOBS=${maxJobs} \\`);
  if (seedVersion) {
    lines.push(`  -e ESPHOME_SEED_VERSION=${seedVersion} \\`);
  }
  if (hostPlatform) {
    lines.push(`  -e HOST_PLATFORM=${JSON.stringify(hostPlatform)} \\`);
  }
  lines.push(`  -v esphome-versions:/esphome-versions \\`);
  lines.push(`  ghcr.io/weirded/esphome-dist-client:${clientTag}`);

  return lines.join('\n');
}

export function ConnectWorkerModal({ serverInfo, esphomeVersion, onClose }: Props) {
  const port = serverInfo.port || 8765;
  const addrs = serverInfo.server_addresses?.length
    ? serverInfo.server_addresses
    : [serverInfo.server_ip || window.location.hostname];
  const urlOptions = addrs.map(addr => `http://${addr}:${port}`);

  const [serverUrl, setServerUrl] = useState(urlOptions[0] || '');
  const [containerName, setContainerName] = useState('distributed-esphome-worker');
  const [hostname, setHostname] = useState('');
  const [maxJobs, setMaxJobs] = useState(2);
  const [seedVersion, setSeedVersion] = useState(esphomeVersion || '');
  const seedUserEdited = useRef(false);
  const [hostPlatform, setHostPlatform] = useState('');
  const [restartPolicy, setRestartPolicy] = useState('unless-stopped');
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
  });

  function handleOverlayClick(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget) onClose();
  }

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
    <div id="connect-modal" className="modal-overlay open" onClick={handleOverlayClick}>
      <div className="modal" style={{ maxWidth: 720 }}>
        <div className="modal-header">
          <div className="modal-header-left">
            <h3>Connect a Build Worker</h3>
          </div>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body" style={{ padding: 18 }}>
          <div className="connect-form">
            <div>
              <label>Server URL</label>
              <select value={serverUrl} onChange={e => setServerUrl(e.target.value)}>
                {urlOptions.map(u => <option key={u} value={u}>{u}</option>)}
              </select>
            </div>
            <div>
              <label>Server Token</label>
              <input type="text" value={serverInfo.token || ''} readOnly />
            </div>
            <div>
              <label>Container Name</label>
              <input
                type="text"
                value={containerName}
                onChange={e => setContainerName(e.target.value)}
              />
            </div>
            <div>
              <label>Hostname</label>
              <input
                type="text"
                value={hostname}
                placeholder="$(hostname)"
                onChange={e => setHostname(e.target.value)}
              />
            </div>
            <div>
              <label>Max Parallel Jobs</label>
              <input
                type="number"
                value={maxJobs}
                min={1}
                max={8}
                onChange={e => setMaxJobs(parseInt(e.target.value, 10) || 2)}
              />
            </div>
            <div>
              <label>ESPHome Seed Version</label>
              <input
                type="text"
                value={seedVersion}
                onChange={e => { seedUserEdited.current = true; setSeedVersion(e.target.value); }}
              />
            </div>
            <div>
              <label>
                Host Platform{' '}
                <span style={{ color: 'var(--text-muted)', fontWeight: 400, textTransform: 'none' }}>
                  (optional)
                </span>
              </label>
              <input
                type="text"
                value={hostPlatform}
                placeholder="e.g. macOS 15.3 (Apple M1 Pro)"
                onChange={e => setHostPlatform(e.target.value)}
              />
            </div>
            <div>
              <label>Restart Policy</label>
              <select value={restartPolicy} onChange={e => setRestartPolicy(e.target.value)}>
                <option value="unless-stopped">unless-stopped</option>
                <option value="always">always</option>
                <option value="no">no</option>
              </select>
            </div>
          </div>
          <div className="docker-cmd-wrap">
            <pre className="docker-cmd">{dockerCmd}</pre>
            <button className="btn-secondary btn-sm docker-cmd-copy" onClick={handleCopy}>
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
          <p style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 12 }}>
            Run this command on any Docker host that has network access to your ESP devices (port 3232 for OTA).
            The worker will poll this server for build jobs, compile firmware, and push updates directly to your devices.
          </p>
        </div>
      </div>
    </div>
  );
}
