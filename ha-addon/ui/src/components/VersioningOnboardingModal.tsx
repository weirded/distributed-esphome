/**
 * #98 — first-login onboarding for the config-versioning feature.
 *
 * Rendered by ``App.tsx`` whenever ``appSettings.versioning_enabled``
 * is ``'unset'`` (the fresh-install default). Offers Pat two explicit
 * paths — turn versioning on, or leave it off. Either choice commits
 * the setting to ``'on'`` / ``'off'`` so the modal doesn't reappear
 * on the next page load.
 *
 * Deliberately NOT dismissable via Esc / outside-click: the setting
 * has to move out of ``'unset'`` for the server's git operations to
 * start running (or stay off). Letting the user dismiss without
 * picking leaves the add-on in its inert state forever, which is
 * arguably fine but also means the question keeps reappearing and
 * Pat wonders if something's broken. The modal is a one-time ask;
 * treat it like an install-time consent prompt.
 */

import { useState } from 'react';
import { GitBranch, History, RotateCcw } from 'lucide-react';

import { updateSettings } from '@/api/client';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { toast } from 'sonner';


export function VersioningOnboardingModal({ onDecided }: { onDecided: () => void }) {
  const [busy, setBusy] = useState(false);

  async function choose(value: 'on' | 'off') {
    setBusy(true);
    try {
      await updateSettings({ versioning_enabled: value });
      toast.success(value === 'on' ? 'Config versioning turned on' : 'Config versioning stays off');
      onDecided();
    } catch (err) {
      toast.error('Failed to save: ' + (err as Error).message);
      setBusy(false);
    }
  }

  return (
    // Open=true always (App.tsx only mounts the component when the
    // setting is 'unset'). onOpenChange is absent on purpose — no
    // Esc / outside-click dismiss.
    <Dialog open>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitBranch className="size-4" aria-hidden="true" />
            Turn on config versioning?
          </DialogTitle>
        </DialogHeader>
        <div className="px-4 py-3 text-sm text-[var(--text)] space-y-3">
          <p>
            ESPHome Fleet can keep a local git history of{' '}
            <code className="rounded bg-[var(--surface2)] px-1 py-0.5 font-mono text-xs">
              /config/esphome/
            </code>{' '}
            so every edit is saved as a commit. This gives you:
          </p>
          <ul className="list-disc list-inside space-y-1 text-xs text-[var(--text-muted)] pl-2">
            <li className="flex items-start gap-2">
              <History className="size-3.5 mt-0.5 shrink-0" aria-hidden="true" />
              <span>Per-file history you can scroll through from the Devices hamburger.</span>
            </li>
            <li className="flex items-start gap-2">
              <RotateCcw className="size-3.5 mt-0.5 shrink-0" aria-hidden="true" />
              <span>One-click rollback to any earlier version of any YAML.</span>
            </li>
            <li className="flex items-start gap-2">
              <GitBranch className="size-3.5 mt-0.5 shrink-0" aria-hidden="true" />
              <span>A real <code className="font-mono">.git/</code> directory — your normal git tooling works too.</span>
            </li>
          </ul>
          <p className="text-xs text-[var(--text-muted)]">
            Turning this on creates a local repo on first save. Turning it off later is a single toggle in Settings
            — the repo stays on disk either way.
          </p>
          <p className="text-xs text-[var(--text-muted)]">
            You can change your mind anytime in <strong>Settings → Config versioning</strong>.
          </p>
        </div>
        <DialogFooter>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => choose('off')}
            disabled={busy}
          >
            Leave off
          </Button>
          <Button
            size="sm"
            onClick={() => choose('on')}
            disabled={busy}
          >
            Turn on versioning
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
