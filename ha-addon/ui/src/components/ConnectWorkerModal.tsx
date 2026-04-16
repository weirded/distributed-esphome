import { useEffect, useReducer, useRef, useState } from 'react';
import type { ServerInfo, WorkerPreset } from '../types';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Button } from './ui/button';
import { ButtonGroup } from './ui/button-group';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Select } from './ui/select';

interface Props {
  serverInfo: ServerInfo;
  esphomeVersion: string | null;
  onClose: () => void;
  /** Pre-populate fields when reconnecting an existing worker (bug #7). */
  preset?: WorkerPreset | null;
}

// UX.10: supported output formats in the Connect Worker modal. `compose`
// emits a docker-compose.yml snippet, replacing the old static
// docker-compose.worker.yml that was retired from the repo root — the
// modal generates the live-from-server equivalent with the real
// SERVER_URL / SERVER_TOKEN baked in.
type Format = 'bash' | 'powershell' | 'compose';

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
  format: Format;
}): string {
  const {
    serverUrl, token, containerName, hostname, maxJobs,
    seedVersion, hostPlatform, restartPolicy, clientTag, format,
  } = params;

  if (format === 'compose') {
    const envLines: string[] = [
      `      - SERVER_URL=${serverUrl}`,
      `      - SERVER_TOKEN=${token}`,
      `      - MAX_PARALLEL_JOBS=${maxJobs}`,
    ];
    if (hostname) envLines.push(`      - HOSTNAME=${hostname}`);
    if (seedVersion) envLines.push(`      - ESPHOME_SEED_VERSION=${seedVersion}`);
    if (hostPlatform) envLines.push(`      - HOST_PLATFORM=${hostPlatform}`);
    const yaml = [
      'name: esphome-fleet-worker',
      '',
      'services:',
      '  worker:',
      `    image: ghcr.io/weirded/esphome-dist-client:${clientTag}`,
      `    container_name: ${containerName}`,
      ...(restartPolicy !== 'no' ? [`    restart: ${restartPolicy}`] : []),
      '    network_mode: host',
      '    environment:',
      ...envLines,
      '    volumes:',
      '      - esphome-versions:/esphome-versions',
      '',
      'volumes:',
      '  esphome-versions:',
      '    name: esphome-versions',
    ];
    return yaml.join('\n');
  }

  const cont = format === 'powershell' ? '`' : '\\';
  const hostnameVar = format === 'powershell' ? '$env:COMPUTERNAME' : '$(hostname)';

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

// QS.27: consolidate the modal's form fields under one reducer instead
// of 8 parallel useState hooks. Makes the "preset" pre-population path
// a single dispatch + keeps the pre-rendered docker command derived
// from one source of truth.
interface FormState {
  serverUrl: string;
  containerName: string;
  hostname: string;
  maxJobs: number;
  seedVersion: string;
  hostPlatform: string;
  restartPolicy: string;
  // UX.10: renamed from `shell` to cover the new `compose` output too.
  format: Format;
}

type FormAction =
  | { type: 'set'; field: keyof FormState; value: FormState[keyof FormState] }
  | { type: 'reset'; next: FormState };

function formReducer(state: FormState, action: FormAction): FormState {
  switch (action.type) {
    case 'set':
      return { ...state, [action.field]: action.value };
    case 'reset':
      return action.next;
  }
}

export function ConnectWorkerModal({ serverInfo, esphomeVersion, onClose, preset }: Props) {
  const port = serverInfo.port || 8765;
  const addrs = serverInfo.server_addresses?.length
    ? serverInfo.server_addresses
    : [serverInfo.server_ip || window.location.hostname];
  const urlOptions = addrs.map(addr => `http://${addr}:${port}`);

  // Preset fields pre-populate when reconnecting an existing worker
  // (bug #7). We read them once at mount and don't sync later — the
  // modal is short-lived and a mid-edit prop change would be surprising.
  const [form, dispatch] = useReducer(formReducer, {
    serverUrl: urlOptions[0] || '',
    // UX.9: renamed from 'distributed-esphome-worker' to match the
    // ESPHome Fleet rebrand. Shows in `docker ps`, dashboards, and
    // logs — only affects newly-copied commands, not existing containers.
    containerName: 'esphome-fleet-worker',
    hostname: preset?.hostname ?? '',
    maxJobs: preset?.max_parallel_jobs ?? 2,
    seedVersion: esphomeVersion || '',
    hostPlatform: preset?.host_platform ?? '',
    restartPolicy: 'unless-stopped',
    format: 'bash',
  });
  const seedUserEdited = useRef(false);
  const [copied, setCopied] = useState(false);

  // Convenience aliases so JSX stays readable.
  const { serverUrl, containerName, hostname, maxJobs, seedVersion,
    hostPlatform, restartPolicy, format } = form;
  const set = <K extends keyof FormState>(field: K, value: FormState[K]) =>
    dispatch({ type: 'set', field, value });

  // Sync seed version from props unless user manually edited it
  useEffect(() => {
    if (!seedUserEdited.current && esphomeVersion) {
      dispatch({ type: 'set', field: 'seedVersion', value: esphomeVersion });
    }
  }, [esphomeVersion]);

  // Keep server URL dropdown in sync when addresses change
  useEffect(() => {
    if (!urlOptions.includes(serverUrl)) {
      dispatch({ type: 'set', field: 'serverUrl', value: urlOptions[0] || '' });
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
    format,
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
              <Label>Server URL</Label>
              <Select value={serverUrl} onChange={e => set('serverUrl', e.target.value)}>
                {urlOptions.map(u => <option key={u} value={u}>{u}</option>)}
              </Select>
            </div>
            <div>
              <Label>Server Token</Label>
              <Input
                className="sensitive text-[var(--text-muted)] cursor-default"
                type="text"
                value={serverInfo.token || ''}
                readOnly
              />
            </div>
            <div>
              <Label>Container Name</Label>
              <Input
                type="text"
                value={containerName}
                onChange={e => set('containerName', e.target.value)}
              />
            </div>
            <div>
              <Label>Hostname</Label>
              <Input
                type="text"
                value={hostname}
                placeholder="$(hostname)"
                onChange={e => set('hostname', e.target.value)}
              />
            </div>
            <div>
              <Label>Max Parallel Jobs</Label>
              <Input
                type="number"
                value={maxJobs}
                min={1}
                max={8}
                onChange={e => set('maxJobs', parseInt(e.target.value, 10) || 2)}
              />
            </div>
            <div>
              <Label>ESPHome Seed Version</Label>
              <Input
                type="text"
                value={seedVersion}
                onChange={e => { seedUserEdited.current = true; set('seedVersion', e.target.value); }}
              />
            </div>
            <div>
              <Label>
                Host Platform{' '}
                <span className="text-[var(--text-muted)] font-normal normal-case">(optional)</span>
              </Label>
              <Input
                type="text"
                value={hostPlatform}
                placeholder="e.g. macOS 15.3 (Apple M1 Pro)"
                onChange={e => set('hostPlatform', e.target.value)}
              />
            </div>
            <div>
              <Label>Restart Policy</Label>
              <Select value={restartPolicy} onChange={e => set('restartPolicy', e.target.value)}>
                <option value="unless-stopped">unless-stopped</option>
                <option value="always">always</option>
                <option value="no">no</option>
              </Select>
            </div>
          </div>
          <div className="flex items-center gap-2 mb-2">
            <Label className="mb-0">Format</Label>
            <ButtonGroup>
              <Button
                variant={format === 'bash' ? 'default' : 'secondary'}
                size="sm"
                onClick={() => set('format', 'bash')}
              >
                Bash
              </Button>
              <Button
                variant={format === 'powershell' ? 'default' : 'secondary'}
                size="sm"
                onClick={() => set('format', 'powershell')}
              >
                PowerShell
              </Button>
              {/* UX.10: `docker compose` tab replaces the repo-root
                  docker-compose.worker.yml file. The snippet below
                  bakes in the user's real SERVER_URL + SERVER_TOKEN,
                  so it can't drift from the running server config. */}
              <Button
                variant={format === 'compose' ? 'default' : 'secondary'}
                size="sm"
                onClick={() => set('format', 'compose')}
              >
                Docker Compose
              </Button>
            </ButtonGroup>
          </div>
          <div className="docker-cmd-wrap">
            <pre className="docker-cmd sensitive">{dockerCmd}</pre>
            <Button variant="secondary" size="sm" className="docker-cmd-copy" onClick={handleCopy}>
              {copied ? 'Copied!' : 'Copy'}
            </Button>
          </div>
          <p style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 12 }}>
            {format === 'compose'
              ? 'Save this snippet as docker-compose.yml on a Docker host with network access to your ESP devices, then run `docker compose up -d`.'
              : 'Run this command on any Docker host that has network access to your ESP devices (port 3232 for OTA). The worker will poll this server for build jobs, compile firmware, and push updates directly to your devices.'}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
