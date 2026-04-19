import { useEffect, useState } from 'react';
import useSWR from 'swr';
import { toast } from 'sonner';
import { Copy, Eye, EyeOff } from 'lucide-react';

import {
  commitFile,
  deleteArchivedConfig,
  getArchivedConfigs,
  getSettings,
  restoreArchivedConfig,
  updateSettings,
  type AppSettings,
  type ArchivedConfig,
} from '@/api/client';
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

  // Bug #21 (supersedes #17): confirmation state for the
  // auto-commit-toggle-on prompt. Fires when the user flips the
  // toggle from OFF → ON with dirty files: from that point on all
  // future saves will auto-commit, but the existing uncommitted
  // state won't unless it gets touched. The prompt asks whether to
  // commit those stragglers before the new behavior kicks in.
  const [turnOnOpen, setTurnOnOpen] = useState(false);
  const [turnOnBusy, setTurnOnBusy] = useState(false);

  async function patch(partial: Partial<AppSettings>): Promise<boolean> {
    // Bug #21: intercept the auto-commit flip-to-ON when there are
    // uncommitted changes. Instead of patching straight away, we open
    // the confirmation dialog; its buttons will finish the PATCH.
    if (
      partial.auto_commit_on_save === true
      && data?.auto_commit_on_save === false
      && dirtyTargets.length > 0
    ) {
      setTurnOnOpen(true);
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
              {/* CF.2: archived-config viewer. Server endpoints
                  `/ui/api/archive` + `/ui/api/archive/{f}/restore` +
                  DELETE have been live since 1.2.0 — this section is the
                  first UI consumer. Rendered inside the Settings drawer
                  (rather than as a new tab or modal) because the action
                  is rare, it's adjacent to the other "manage server
                  state" toggles, and a dedicated surface would
                  over-weight how often users actually reach for it. */}
              <Section title="Archived devices">
                <ArchivedDevicesList />
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

      {/* Bug #21: confirmation when the user flips auto-commit OFF →
          ON with uncommitted changes. Subsequent saves will start
          auto-committing, but the existing dirty files won't get
          committed until the user touches them again. Offer to flush
          them now so history stays continuous. */}
      <Dialog
        open={turnOnOpen}
        onOpenChange={(o) => { if (!o && !turnOnBusy) setTurnOnOpen(false); }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Turn on auto-commit?</DialogTitle>
          </DialogHeader>
          <div className="px-4 py-3 text-sm text-[var(--text)]">
            <p>
              You have uncommitted changes to <strong>{dirtyTargets.length}</strong>{' '}
              file{dirtyTargets.length === 1 ? '' : 's'}. From now on every save will
              auto-commit — but those existing edits won't be committed
              automatically until you touch each file again.
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
              Commit them now to keep history continuous, or turn on
              anyway if you'd rather commit them yourself later.
            </p>
          </div>
          <DialogFooter>
            <DialogClose>
              <Button variant="secondary" size="sm" disabled={turnOnBusy}>Cancel</Button>
            </DialogClose>
            <Button
              variant="outline"
              size="sm"
              disabled={turnOnBusy}
              onClick={async () => {
                setTurnOnBusy(true);
                try {
                  await patchRaw({ auto_commit_on_save: true });
                  toast.success('Auto-commit turned on; existing uncommitted changes left in place');
                  setTurnOnOpen(false);
                } catch (err) {
                  toast.error('Failed to update setting: ' + (err as Error).message);
                } finally {
                  setTurnOnBusy(false);
                }
              }}
            >
              Turn on anyway
            </Button>
            <Button
              size="sm"
              disabled={turnOnBusy}
              onClick={async () => {
                setTurnOnBusy(true);
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
                  await patchRaw({ auto_commit_on_save: true });
                  setTurnOnOpen(false);
                } catch (err) {
                  toast.error('Failed: ' + (err as Error).message);
                } finally {
                  setTurnOnBusy(false);
                }
              }}
            >
              Commit {dirtyTargets.length} and turn on
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


// --------------------------------------------------------------------- //
// CF.2: archived-config viewer.
// --------------------------------------------------------------------- //

function ArchivedDevicesList() {
  const { data, error, isLoading, mutate } = useSWR<ArchivedConfig[]>(
    'archived-configs',
    getArchivedConfigs,
    { revalidateOnFocus: false },
  );
  const [busy, setBusy] = useState<string | null>(null);
  // Two-step delete confirmation — matches the live device-delete flow:
  // the Permanently-delete action is destructive and should not be
  // one-click from the list.
  const [deleteCandidate, setDeleteCandidate] = useState<ArchivedConfig | null>(null);

  async function handleRestore(filename: string) {
    setBusy(filename);
    try {
      await restoreArchivedConfig(filename);
      toast.success(`Restored ${filename}`);
      await mutate();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function handleConfirmDelete(filename: string) {
    setBusy(filename);
    try {
      await deleteArchivedConfig(filename);
      toast.success(`Permanently deleted ${filename}`);
      await mutate();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(null);
      setDeleteCandidate(null);
    }
  }

  if (error) {
    return (
      <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-400">
        Failed to load archive: {error.message}
      </div>
    );
  }
  if (isLoading && !data) {
    return <div className="text-xs text-[var(--text-muted)]">Loading…</div>;
  }
  if (!data || data.length === 0) {
    return (
      <p className="text-xs text-[var(--text-muted)]">
        No archived devices. Deleted devices land here unless you pass{' '}
        <code className="rounded bg-[var(--surface2)] px-1 py-0.5">archive=false</code>.
      </p>
    );
  }

  return (
    <>
      <p className="text-xs text-[var(--text-muted)]">
        Devices you delete are kept here so you can restore them later. Restore puts the YAML
        back under <code className="rounded bg-[var(--surface2)] px-1 py-0.5">/config/esphome/</code>;
        permanent-delete removes the file from disk entirely and cannot be undone.
      </p>
      <ul className="flex flex-col gap-2 text-xs">
        {data.map((a) => {
          const ago = Math.floor((Date.now() / 1000 - a.archived_at));
          const when = ago < 60 ? `${ago}s ago`
            : ago < 3600 ? `${Math.floor(ago / 60)}m ago`
              : ago < 86_400 ? `${Math.floor(ago / 3600)}h ago`
                : `${Math.floor(ago / 86_400)}d ago`;
          const kb = (a.size / 1024).toFixed(1);
          return (
            <li key={a.filename} className="flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface2)] px-2 py-1.5">
              <div className="flex-1 min-w-0">
                <div className="truncate font-mono text-[12px] text-[var(--text)]" title={a.filename}>
                  {a.filename}
                </div>
                <div className="text-[10px] text-[var(--text-muted)]">
                  {when} · {kb} KB
                </div>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => handleRestore(a.filename)}
                disabled={busy !== null}
              >
                Restore
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => setDeleteCandidate(a)}
                disabled={busy !== null}
                title="Permanently delete — cannot be undone"
              >
                Delete
              </Button>
            </li>
          );
        })}
      </ul>

      {/* Two-step delete confirmation — destructive action. */}
      <Dialog
        open={deleteCandidate !== null}
        onOpenChange={(o) => { if (!o && busy === null) setDeleteCandidate(null); }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Permanently delete {deleteCandidate?.filename}?</DialogTitle>
          </DialogHeader>
          <div className="px-4 py-3 text-sm text-[var(--text)]">
            <p>
              This removes the archived file from disk. You won't be able to restore it
              after this action.
            </p>
          </div>
          <DialogFooter>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setDeleteCandidate(null)}
              disabled={busy !== null}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => deleteCandidate && handleConfirmDelete(deleteCandidate.filename)}
              disabled={busy !== null}
            >
              Delete permanently
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
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
