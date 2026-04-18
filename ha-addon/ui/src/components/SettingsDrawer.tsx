import { useEffect, useState } from 'react';
import useSWR from 'swr';
import { toast } from 'sonner';

import { getSettings, updateSettings, type AppSettings } from '@/api/client';
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
}

export function SettingsDrawer({ open, onOpenChange }: SettingsDrawerProps) {
  const { data, error, isLoading, mutate } = useSWR<AppSettings>(
    open ? 'settings' : null,
    getSettings,
    { revalidateOnFocus: false },
  );

  async function patch(partial: Partial<AppSettings>): Promise<boolean> {
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
