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
 * and keyboard navigation. This removes ~60 lines of manual DOM math and
 * fixes the CLAUDE.md "default to shadcn/ui" violation.
 *
 * Menu items preserve their previous ordering, disabled-with-tooltip
 * behaviors (Restart when no `has_restart_button`, Copy API Key when no
 * `has_api_key`), and click-through actions. The trigger remains the ⋮
 * glyph so the row visual is unchanged.
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
}

export function DeviceContextMenu({
  target: t,
  onToast,
  onRename,
  onDuplicate,
  onDelete,
  onLogs,
  onPin,
  onUnpin,
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
    <DropdownMenu>
      <DropdownMenuTrigger
        className="action-menu-trigger cursor-pointer"
        aria-label="More actions"
        title="More actions"
      >
        &#8942;
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[200px] w-max max-w-[320px]">
        <DropdownMenuGroup>
          <DropdownMenuLabel>Device</DropdownMenuLabel>
          <DropdownMenuItem onClick={() => onLogs(t.target)}>Live Logs</DropdownMenuItem>
          {/* #14: grayed out when the YAML doesn't expose a restart button. */}
          <DropdownMenuItem
            onClick={handleRestart}
            disabled={!t.has_restart_button}
            title={t.has_restart_button ? undefined : "No restart button in this device's YAML — add `button: [{platform: restart}]` to enable."}
          >
            Restart
          </DropdownMenuItem>
          <DropdownMenuItem onClick={handleCopyApiKey} disabled={!t.has_api_key}>
            Copy API Key
          </DropdownMenuItem>
        </DropdownMenuGroup>

        <DropdownMenuSeparator />

        <DropdownMenuGroup>
          <DropdownMenuLabel>Config</DropdownMenuLabel>
          {/* #93: "Schedule Upgrade…" removed — accessible via the Upgrade
              button by switching to "Scheduled" mode. */}
          {t.pinned_version ? (
            <DropdownMenuItem onClick={() => onUnpin(t.target)}>
              Unpin version ({t.pinned_version})
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem onClick={() => onPin(t.target)}>
              Pin to current version
            </DropdownMenuItem>
          )}
          <DropdownMenuItem onClick={() => onRename(t.target)}>Rename</DropdownMenuItem>
          {/* CD.6: duplicate this device into a new file */}
          <DropdownMenuItem onClick={() => onDuplicate(t)}>Duplicate…</DropdownMenuItem>
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
