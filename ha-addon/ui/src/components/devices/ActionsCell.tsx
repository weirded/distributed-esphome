import { memo } from 'react';
import type { Target } from '../../types';
import { Button } from '../ui/button';
import { DeviceContextMenu } from './DeviceContextMenu';
import { driftTooltip, hasDriftedConfig } from './drift';

/**
 * Row actions cell: Upgrade + Edit + hamburger menu (#4).
 *
 * Extracted as a dedicated React.memo'd component so the cell subtree is
 * referentially stable across SWR polls. Previously the cell body was an
 * inline arrow inside `useDeviceColumns` that React reconciled but did NOT
 * skip-render, meaning every poll called the arrow, rebuilt the children,
 * and gave Base UI's Menu Positioner an opportunity to re-fire — which the
 * user saw as "twitching" when the menu was open.
 *
 * The compare below is deliberately tight: only the Target fields actually
 * read in render, plus `inFlight` (changes when a job enters/leaves active
 * state for this row), plus `open`. Handler props are treated as always-
 * equal; they're closures that rebind to stable underlying callbacks.
 */

// QS.20-related: stable style ref so React's style-prop compare is O(1).
const rowStyle = { display: 'flex', gap: 4, alignItems: 'center' } as const;

type ToastFn = (msg: string, type?: 'info' | 'success' | 'error') => void;

interface Props {
  target: Target;
  inFlight: boolean;
  menuOpen: boolean;
  onUpgradeOne: (target: string) => void;
  onEdit: (target: string) => void;
  onLogs: (target: string) => void;
  onToast: ToastFn;
  onDuplicate: (target: string) => void;
  onRequestRename: (target: string) => void;
  onRequestDelete: (target: string) => void;
  /** Bug #3: archive the target without showing the Delete confirmation
   *  modal — archived configs are restorable from Settings. */
  onArchive: (target: string) => void;
  onPin: (target: string) => void;
  onUnpin: (target: string) => void;
  /** AV.6: open the per-file History panel. */
  onOpenHistory: (target: string) => void;
  /** JH.5: open the per-device Compile History panel. */
  onOpenCompileHistory: (target: string) => void;
  /** Bug #16: open the manual-commit dialog for this target. */
  onCommitChanges: (target: string) => void;
  /** RC.1: open the read-only rendered-config viewer. */
  onViewRenderedConfig: (target: string) => void;
  onMenuOpenChange: (open: boolean) => void;
}

function ActionsCellImpl({
  target: t,
  inFlight,
  menuOpen,
  onUpgradeOne,
  onEdit,
  onLogs,
  onToast,
  onDuplicate,
  onRequestRename,
  onRequestDelete,
  onArchive,
  onPin,
  onUnpin,
  onOpenHistory,
  onOpenCompileHistory,
  onCommitChanges,
  onViewRenderedConfig,
  onMenuOpenChange,
}: Props) {
  // Bug #32: highlight the Upgrade button when the YAML has drifted.
  // `hasDriftedConfig` is the single source of truth shared with the
  // "config changed" badge in useDeviceColumns — see ./drift.ts for the
  // precedence (git-diff-since-flash > git-status > mtime). `needs_update`
  // remains the ESPHome-compiler-version signal and also wins the green
  // variant.
  const configDrifted = hasDriftedConfig(t);
  const upgradeVariant: 'success' | 'secondary' =
    t.needs_update || configDrifted ? 'success' : 'secondary';
  const upgradeTitle = inFlight
    ? 'A build is already running. Click to queue the next compile (will use the latest YAML at the time it starts).'
    : configDrifted && !t.needs_update
      ? (driftTooltip(t) ?? 'Config has changed since this device was last flashed — Upgrade to apply.')
      : undefined;

  return (
    <div style={rowStyle}>
      <Button
        variant={upgradeVariant}
        size="sm"
        title={upgradeTitle}
        onClick={() => onUpgradeOne(t.target)}
      >
        Upgrade
      </Button>
      <Button variant="secondary" size="sm" onClick={() => onEdit(t.target)}>Edit</Button>
      <DeviceContextMenu
        target={t}
        onToast={onToast}
        onRename={onRequestRename}
        onDuplicate={(tg) => onDuplicate(tg.target)}
        onDelete={onRequestDelete}
        onArchive={onArchive}
        onLogs={onLogs}
        onPin={onPin}
        onUnpin={onUnpin}
        onOpenHistory={onOpenHistory}
        onOpenCompileHistory={onOpenCompileHistory}
        onCommitChanges={onCommitChanges}
        onViewRenderedConfig={onViewRenderedConfig}
        open={menuOpen}
        onOpenChange={onMenuOpenChange}
      />
    </div>
  );
}

function propsEqual(prev: Props, next: Props): boolean {
  if (prev.inFlight !== next.inFlight) return false;
  if (prev.menuOpen !== next.menuOpen) return false;
  const a = prev.target;
  const b = next.target;
  return (
    a.target === b.target &&
    a.needs_update === b.needs_update &&
    a.has_restart_button === b.has_restart_button &&
    a.has_api_key === b.has_api_key &&
    a.pinned_version === b.pinned_version &&
    a.has_uncommitted_changes === b.has_uncommitted_changes &&
    // Bug #32: new config-drift signals that drive Upgrade button color.
    a.config_drifted_since_flash === b.config_drifted_since_flash &&
    a.config_modified === b.config_modified
  );
}

export const ActionsCell = memo(ActionsCellImpl, propsEqual);
