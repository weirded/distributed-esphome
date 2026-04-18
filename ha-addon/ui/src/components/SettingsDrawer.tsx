import { useEffect, useState } from 'react';
import useSWR from 'swr';
import { toast } from 'sonner';
import { Copy, Eye, EyeOff } from 'lucide-react';

import { commitFile, getSettings, updateSettings, type AppSettings } from '@/api/client';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';

// SP.4: the in-app Settings drawer.
//
// Sectioned so the shape scales as more settings land in later releases.
// Save-on-change — no bulk Save button. Each row owns its draft state
// locally, commits on blur (numeric fields) or change (switch), and
// surfaces validation errors as a toast.

interface SettingsDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Bug #17: list of filenames that currently have uncommitted
   * changes. When the user flips auto-commit from on → off with
   * any dirty targets in this list, we show a confirmation dialog
   * offering to commit them first. Empty array when everything's
   * clean or the repo isn't a git repo at all. */
  dirtyTargets?: string[];
}

export function SettingsDrawer({ open, onOpenChange, dirtyTargets = [] }: SettingsDrawerProps) {
  const { data, error, isLoading, mutate } = useSWR<AppSettings>(
    open ? 'settings' : null,
    getSettings,
    { revalidateOnFocus: false },
  );

  // Bug #17: auto-commit-toggle-off confirmation state. `true` when
  // the Dialog is open; a pending-promise handle lets us resolve the
  // user's choice inside the patch() flow.
  const [turnOffOpen, setTurnOffOpen] = useState(false);
  const [turnOffBusy, setTurnOffBusy] = useState(false);

  async function patch(partial: Partial<AppSettings>): Promise<boolean> {
    // Bug #17: intercept the auto-commit flip-to-off when there are
    // uncommitted changes. Instead of patching straight away, we open
    // the confirmation dialog; its buttons will finish the PATCH.
    if (
      partial.auto_commit_on_save === false
      && data?.auto_commit_on_save === true
      && dirtyTargets.length > 0
    ) {
      setTurnOffOpen(true);
      return false;
    }
    try {
      const updated = await updateSettings(partial);
      await mutate(updated, false);
      toast.success('Setting saved');
      return true;
    } catch (err) {
      toast.error((err as Error).message);
      await mutate();
      return false;
    }
  }

  async function patchRaw(partial: Partial<AppSettings>): Promise<void> {
    // Bypass the dirty-check — used by the confirmation dialog's
    // "Turn off anyway" / "Commit and turn off" branches.
    const updated = await updateSettings(partial);
    await mutate(updated, false);
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <div>
            <SheetTitle>Settings</SheetTitle>
            <SheetDescription>Changes take effect immediately.</SheetDescription>
          </div>
        </SheetHeader>
        <SheetBody>
          {error && (
            <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-400">
              Failed to load settings: {error.message}
            </div>
          )}
          {isLoading && <div className="text-xs text-[var(--text-muted)]">Loading…</div>}
          {data && (
            <div className="flex flex-col gap-6">
              <Section title="Config versioning">
                <BoolRow
                  label="Auto-commit on save"
                  help="Every save creates a local git commit in /config/esphome/. Turn off if you manage this directory with your own git workflow."
                  value={data.auto_commit_on_save}
                  onChange={v => patch({ auto_commit_on_save: v })}
                />
                <StringRow
                  label="Commit author name"
                  help="Used on Fleet-created commits. If /config/esphome/ has its own user.name set (per-repo, global, or system), that wins."
                  maxLength={100}
                  value={data.git_author_name}
                  onCommit={v => patch({ git_author_name: v })}
                />
                <StringRow
                  label="Commit author email"
                  help="Paired with the name above. Free-form — no format validation."
                  maxLength={256}
                  value={data.git_author_email}
                  onCommit={v => patch({ git_author_email: v })}
                />
              </Section>
              <Section title="Job history">
                <IntRow
                  label="Retention (days)"
                  help="How long to keep per-job compile history. 0 = unlimited."
                  min={0}
                  max={3650}
                  value={data.job_history_retention_days}
                  onCommit={v => patch({ job_history_retention_days: v })}
                />
              </Section>
              <Section title="Disk management">
                <NumRow
                  label="Firmware cache size (GB)"
                  help="Maximum disk space the server will use to cache compiled firmware binaries."
                  min={0.1}
                  max={1024}
                  step={0.1}
                  value={data.firmware_cache_max_gb}
                  onCommit={v => patch({ firmware_cache_max_gb: v })}
                />
                <IntRow
                  label="Job log retention (days)"
                  help="How long to keep per-job build logs on disk. 0 = unlimited."
                  min={0}
                  max={3650}
                  value={data.job_log_retention_days}
                  onCommit={v => patch({ job_log_retention_days: v })}
                />
              </Section>
              <Section title="Authentication">
                <SecretRow
                  label="Server token"
                  help="Shared bearer token for build workers and direct-port API access. Changing this will disconnect existing workers until their SERVER_TOKEN env var is updated."
                  value={data.server_token}
                  onCommit={v => patch({ server_token: v })}
                />
                <BoolRow
                  label="Require Home Assistant auth on direct port"
                  help="When on, requests to port 8765 (outside the Home Assistant Ingress tunnel) must carry a valid HA bearer token or this server token. Leave on unless you have a specific reason to allow anonymous direct-port access."
                  value={data.require_ha_auth}
                  onChange={v => patch({ require_ha_auth: v })}
                />
              </Section>
              <Section title="Timeouts">
                <IntRow
                  label="Job timeout (seconds)"
                  help="Maximum wall-clock seconds a single compile job may run before the server marks it timed-out."
                  min={60}
                  max={14400}
                  value={data.job_timeout}
                  onCommit={v => patch({ job_timeout: v })}
                />
                <IntRow
                  label="OTA timeout (seconds)"
                  help="Maximum seconds for the OTA upload to a device after a successful compile."
                  min={15}
                  max={1800}
                  value={data.ota_timeout}
                  onCommit={v => patch({ ota_timeout: v })}
                />
                <IntRow
                  label="Worker offline threshold (seconds)"
                  help="Seconds without a worker heartbeat before it's flagged offline in the Workers tab."
                  min={15}
                  max={3600}
                  value={data.worker_offline_threshold}
                  onCommit={v => patch({ worker_offline_threshold: v })}
                />
              </Section>
              <Section title="Polling">
                <IntRow
                  label="Device poll interval (seconds)"
                  help="How often the server polls each ESPHome device over its native API to refresh online status and running-firmware version."
                  min={10}
                  max={3600}
                  value={data.device_poll_interval}
                  onCommit={v => patch({ device_poll_interval: v })}
                />
              </Section>
              <Section title="About">
                <p className="text-xs text-[var(--text-muted)]">
                  Settings are stored in <code className="rounded bg-[var(--surface2)] px-1 py-0.5">/data/settings.json</code>{' '}
                  inside the add-on and persist across updates. Deployment-level options (token, port,{' '}
                  <code className="rounded bg-[var(--surface2)] px-1 py-0.5">require_ha_auth</code>) remain on the
                  Home Assistant add-on Configuration tab.
                </p>
              </Section>
            </div>
          )}
        </SheetBody>
      </SheetContent>

      {/* Bug #17: confirmation shown when the user flips auto-commit
          off while there are uncommitted changes somewhere in the
          fleet. Three outcomes: Commit-then-turn-off, turn-off-anyway,
          or cancel (leaves the toggle untouched). */}
      <Dialog
        open={turnOffOpen}
        onOpenChange={(o) => { if (!o && !turnOffBusy) setTurnOffOpen(false); }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Turn off auto-commit?</DialogTitle>
          </DialogHeader>
          <div className="px-4 py-3 text-sm text-[var(--text)]">
            <p>
              You have uncommitted changes to <strong>{dirtyTargets.length}</strong>{' '}
              file{dirtyTargets.length === 1 ? '' : 's'}. Turning off auto-commit
              leaves them in the working tree — they stay on disk but they
              won't show up in history until you commit them manually.
            </p>
            {dirtyTargets.length > 0 && (
              <ul className="mt-2 flex flex-wrap gap-1">
                {dirtyTargets.slice(0, 8).map(t => (
                  <li key={t}>
                    <code className="rounded bg-[var(--surface2)] px-1.5 py-0.5 font-mono text-[11px]">
                      {t}
                    </code>
                  </li>
                ))}
                {dirtyTargets.length > 8 && (
                  <li className="text-xs text-[var(--text-muted)] self-center">
                    …and {dirtyTargets.length - 8} more
                  </li>
                )}
              </ul>
            )}
            <p className="mt-3 text-xs text-[var(--text-muted)]">
              Commit them now to preserve the history, or turn off anyway
              if you want to commit them yourself later.
            </p>
          </div>
          <DialogFooter>
            <DialogClose>
              <Button variant="secondary" size="sm" disabled={turnOffBusy}>Cancel</Button>
            </DialogClose>
            <Button
              variant="outline"
              size="sm"
              disabled={turnOffBusy}
              onClick={async () => {
                setTurnOffBusy(true);
                try {
                  await patchRaw({ auto_commit_on_save: false });
                  toast.success('Auto-commit turned off; uncommitted changes left in place');
                  setTurnOffOpen(false);
                } catch (err) {
                  toast.error('Failed to update setting: ' + (err as Error).message);
                } finally {
                  setTurnOffBusy(false);
                }
              }}
            >
              Turn off anyway
            </Button>
            <Button
              size="sm"
              disabled={turnOffBusy}
              onClick={async () => {
                setTurnOffBusy(true);
                try {
                  // One commit per dirty file. Default message on each
                  // matches the manual-commit flow's (manual) marker.
                  const results = await Promise.all(
                    dirtyTargets.map(t => commitFile(t).catch(err => ({ committed: false, err: (err as Error).message, target: t }))),
                  );
                  const committed = results.filter(r => (r as { committed: boolean }).committed).length;
                  const failed = results.length - committed;
                  if (failed === 0) {
                    toast.success(`Committed ${committed} file${committed === 1 ? '' : 's'}`);
                  } else if (committed > 0) {
                    toast.info(`Committed ${committed}, ${failed} failed`);
                  } else {
                    toast.error('No files committed');
                  }
                  await patchRaw({ auto_commit_on_save: false });
                  setTurnOffOpen(false);
                } catch (err) {
                  toast.error('Failed: ' + (err as Error).message);
                } finally {
                  setTurnOffBusy(false);
                }
              }}
            >
              Commit {dirtyTargets.length} and turn off
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Sheet>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">{title}</h3>
      <div className="flex flex-col gap-3">{children}</div>
    </section>
  );
}

function Row({
  label,
  help,
  control,
  id,
}: {
  label: string;
  help?: string;
  control: React.ReactNode;
  id?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="flex flex-col gap-0.5">
        <label htmlFor={id} className="text-sm text-[var(--text)]">
          {label}
        </label>
        {help && <p className="text-xs text-[var(--text-muted)]">{help}</p>}
      </div>
      <div className="shrink-0">{control}</div>
    </div>
  );
}

function BoolRow({
  label,
  help,
  value,
  onChange,
}: {
  label: string;
  help?: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <Row
      label={label}
      help={help}
      control={
        <Switch
          checked={value}
          onCheckedChange={(next: boolean) => onChange(next)}
          aria-label={label}
        />
      }
    />
  );
}

interface NumericRowProps {
  label: string;
  help?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  integer: boolean;
  onCommit: (v: number) => Promise<boolean>;
}

function NumericRow({
  label,
  help,
  value,
  min,
  max,
  step,
  integer,
  onCommit,
}: NumericRowProps) {
  const [draft, setDraft] = useState<string>(String(value));
  const [focused, setFocused] = useState(false);

  // When the upstream value changes (e.g., another tab updated it, or a
  // rejected patch reverted), adopt the new value — but not while the
  // user is mid-edit, so their typing isn't clobbered.
  useEffect(() => {
    if (!focused) setDraft(String(value));
  }, [value, focused]);

  async function commit() {
    setFocused(false);
    const n = Number(draft);
    const valid = Number.isFinite(n) && (!integer || Number.isInteger(n)) && n >= min && n <= max;
    if (!valid) {
      toast.error(`${label} must be ${integer ? 'an integer' : 'a number'} between ${min} and ${max}`);
      setDraft(String(value));
      return;
    }
    if (n === value) return;
    const ok = await onCommit(n);
    if (!ok) setDraft(String(value));
  }

  return (
    <Row
      label={label}
      help={help}
      control={
        <Input
          type="number"
          min={min}
          max={max}
          step={step}
          className="w-24 text-right"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={commit}
          onKeyDown={e => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
          }}
        />
      }
    />
  );
}

function IntRow(props: Omit<NumericRowProps, 'step' | 'integer'>) {
  return <NumericRow {...props} step={1} integer={true} />;
}

function NumRow(props: Omit<NumericRowProps, 'integer'>) {
  return <NumericRow {...props} integer={false} />;
}

function SecretRow({
  label,
  help,
  value,
  onCommit,
}: {
  label: string;
  help?: string;
  value: string;
  onCommit: (v: string) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState<string>(value);
  const [focused, setFocused] = useState(false);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    if (!focused) setDraft(value);
  }, [value, focused]);

  async function commit() {
    setFocused(false);
    const trimmed = draft.trim();
    if (!trimmed) {
      toast.error(`${label} must not be empty`);
      setDraft(value);
      return;
    }
    if (/\s/.test(trimmed)) {
      toast.error(`${label} must not contain whitespace`);
      setDraft(value);
      return;
    }
    if (trimmed === value) return;
    const ok = await onCommit(trimmed);
    if (!ok) setDraft(value);
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      toast.success('Token copied');
    } catch {
      toast.error('Clipboard copy failed');
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-3">
        <label className="text-sm text-[var(--text)]">{label}</label>
      </div>
      <div className="flex items-center gap-2">
        <Input
          type={revealed ? 'text' : 'password'}
          className="flex-1 font-mono text-xs"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={commit}
          onKeyDown={e => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
          }}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={revealed ? 'Hide token' : 'Show token'}
          title={revealed ? 'Hide token' : 'Show token'}
          onClick={() => setRevealed(r => !r)}
        >
          {revealed ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Copy token"
          title="Copy token"
          onClick={copy}
        >
          <Copy className="size-4" />
        </Button>
      </div>
      {help && <p className="text-xs text-[var(--text-muted)]">{help}</p>}
    </div>
  );
}

function StringRow({
  label,
  help,
  value,
  maxLength,
  onCommit,
}: {
  label: string;
  help?: string;
  value: string;
  maxLength: number;
  onCommit: (v: string) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState<string>(value);
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (!focused) setDraft(value);
  }, [value, focused]);

  async function commit() {
    setFocused(false);
    const trimmed = draft.trim();
    if (!trimmed) {
      toast.error(`${label} must not be empty`);
      setDraft(value);
      return;
    }
    if (trimmed.length > maxLength) {
      toast.error(`${label} must be ${maxLength} characters or fewer`);
      setDraft(value);
      return;
    }
    if (trimmed === value) return;
    const ok = await onCommit(trimmed);
    if (!ok) setDraft(value);
  }

  return (
    <Row
      label={label}
      help={help}
      control={
        <Input
          type="text"
          className="w-56"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={commit}
          onKeyDown={e => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
          }}
        />
      }
    />
  );
}
