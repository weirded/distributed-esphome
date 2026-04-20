import { memo } from 'react';
import { MoreVertical } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from '../ui/dropdown-menu';
import { getApiKey, restartDevice } from '../../api/client';
import { stripYaml } from '../../utils';
import type { Target } from '../../types';

/**
 * Per-row hamburger menu for the Devices tab (QS.16).
 *
 * Replaces the hand-rolled `DeviceMenu` that used `position: fixed` with
 * pixel-coordinate tracking, a custom viewport-flip calculation, and a
 * backdrop click-catcher. shadcn's DropdownMenu (Radix-based) handles all
 * of that natively: placement, click-outside, Escape-to-close, focus trap,
 * and keyboard navigation.
 *
 * Menu items preserve their previous ordering, disabled-with-tooltip
 * behaviors (Restart when no `has_restart_button`, Copy API Key when no
 * `has_api_key`), and click-through actions. The trigger remains the ⋮
 * glyph so the row visual is unchanged.
 *
 * #2/#3: wrapped in React.memo with a custom equality check. SWR hands us
 * a fresh `target` object every poll (new reference, same values), which
 * would otherwise re-render the DropdownMenu and cause a visible flash in
 * the overlay's CSS transitions. The compare below treats function props
 * as always-equal (identity changes don't matter for behavior) and
 * compares the target fields we actually read. Open state lives in the
 * parent, so it's still authoritative across re-renders.
 */

interface Props {
  target: Target;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
  onRename: (target: string) => void;
  onDuplicate: (target: Target) => void;
  onDelete: (target: string) => void;
  onLogs: (target: string) => void;
  onPin: (target: string) => void;
  onUnpin: (target: string) => void;
  /** AV.6: open the per-file History panel. */
  onOpenHistory: (target: string) => void;
  /** JH.5: open the per-device Compile History panel. */
  onOpenCompileHistory: (target: string) => void;
  /** Bug #16: open the manual-commit dialog for this target. Only
   * offered when the target has uncommitted changes. */
  onCommitChanges: (target: string) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function DeviceContextMenuImpl({
  target: t,
  onToast,
  onRename,
  onDuplicate,
  onDelete,
  onLogs,
  onPin,
  onUnpin,
  onOpenHistory,
  onOpenCompileHistory,
  onCommitChanges,
  open,
  onOpenChange,
}: Props) {
  async function handleCopyApiKey() {
    try {
      const key = await getApiKey(t.target);
      await navigator.clipboard.writeText(key);
      onToast('API key copied!', 'success');
    } catch {
      onToast('No API key found', 'info');
    }
  }

  async function handleRestart() {
    try {
      await restartDevice(t.target);
      onToast(`Restarting ${stripYaml(t.target)}...`, 'success');
    } catch (err) {
      onToast('Restart failed: ' + (err as Error).message, 'error');
    }
  }

  return (
    <DropdownMenu open={open} onOpenChange={onOpenChange}>
      <DropdownMenuTrigger
        className="action-menu-trigger cursor-pointer inline-flex items-center justify-center"
        aria-label="More actions"
        title="More actions"
      >
        <MoreVertical className="size-4" />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        /* #4: disable the Base-UI close animation for this menu instance.
           Across SWR polls, even small layout shifts in the row can cause
           Base-UI's Positioner to fire, and if the `data-closed` state
           toggles briefly the animate-out+animate-in sequence is visible
           as a "twitch". The open-in animation on first open is preserved;
           only the close animation is suppressed. */
        className="min-w-[200px] w-max max-w-[320px] data-[state=closed]:!animate-none"
      >
        <DropdownMenuGroup>
          <DropdownMenuLabel>Device</DropdownMenuLabel>
          <DropdownMenuItem onClick={() => onLogs(t.target)}>Live Logs</DropdownMenuItem>
          {/* JH.5: per-device past-compiles drawer. Reads from the
              persistent /ui/api/history table so the view survives
              queue coalescing + clears. */}
          <DropdownMenuItem onClick={() => onOpenCompileHistory(t.target)}>
            Compile history…
          </DropdownMenuItem>
          {/* #14: grayed out when the YAML doesn't expose a restart button. */}
          <DropdownMenuItem
            onClick={handleRestart}
            disabled={!t.has_restart_button}
            title={t.has_restart_button ? undefined : "No restart button in this device's YAML — add `button: [{platform: restart}]` to enable."}
          >
            Restart
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={handleCopyApiKey}
            disabled={!t.has_api_key}
            /* UX.11: disable-don't-fail tooltips explain why the item
               is disabled + what YAML change enables it. */
            title={t.has_api_key ? undefined : "This device has no `api:` block with an encryption key. Add `api: { encryption: { key: ... } }` to enable."}
          >
            Copy API Key
          </DropdownMenuItem>
        </DropdownMenuGroup>

        <DropdownMenuSeparator />

        <DropdownMenuGroup>
          <DropdownMenuLabel>Config</DropdownMenuLabel>
          {/* #93: "Schedule Upgrade…" removed — accessible via the Upgrade
              button by switching to "Scheduled" mode.
              Bug #29: "Pin version" was ambiguous under a "Config" group
              (pins the ESPHome compiler version, not the config). Spell
              it out — the config version concept lives in "View history…"
              just below. */}
          {t.pinned_version ? (
            <DropdownMenuItem onClick={() => onUnpin(t.target)}>
              Unpin ESPHome version ({t.pinned_version})
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem onClick={() => onPin(t.target)}>
              Pin ESPHome version to current
            </DropdownMenuItem>
          )}
          <DropdownMenuItem onClick={() => onRename(t.target)}>Rename</DropdownMenuItem>
          {/* CD.6: duplicate this device into a new file */}
          <DropdownMenuItem onClick={() => onDuplicate(t)}>Duplicate…</DropdownMenuItem>
          {/* AV.6: per-file config history + diff + rollback. Bug #29:
              "Config history…" disambiguates from ESPHome-version history
              (which lives in the version dropdown in the header). */}
          <DropdownMenuItem onClick={() => onOpenHistory(t.target)}>
            Config history…
          </DropdownMenuItem>
          {/* Bug #16: only shown when the target has uncommitted changes. */}
          {t.has_uncommitted_changes && (
            <DropdownMenuItem onClick={() => onCommitChanges(t.target)}>
              Commit changes…
            </DropdownMenuItem>
          )}
          <DropdownMenuItem
            variant="destructive"
            onClick={() => onDelete(t.target)}
          >
            Delete
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/**
 * Custom equality: compare only the Target fields we actually use in render,
 * plus `open`. Function props are treated as always-equal — the cell inlines
 * fresh arrows every render (closing over the current `setMenuOpenTarget`),
 * but their behavior is identical as long as they eventually call the same
 * underlying handlers.
 */
function propsEqual(prev: Props, next: Props): boolean {
  if (prev.open !== next.open) return false;
  const a = prev.target;
  const b = next.target;
  return (
    a.target === b.target &&
    a.has_restart_button === b.has_restart_button &&
    a.has_api_key === b.has_api_key &&
    a.pinned_version === b.pinned_version &&
    // Bug #16: dirty state controls the "Commit changes…" item's visibility.
    a.has_uncommitted_changes === b.has_uncommitted_changes
  );
}

export const DeviceContextMenu = memo(DeviceContextMenuImpl, propsEqual);
