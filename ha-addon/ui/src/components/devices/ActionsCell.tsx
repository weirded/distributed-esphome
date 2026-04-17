import { memo } from 'react';
import type { Target } from '../../types';
import { Button } from '../ui/button';
import { DeviceContextMenu } from './DeviceContextMenu';

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
  onPin: (target: string) => void;
  onUnpin: (target: string) => void;
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
  onPin,
  onUnpin,
  onMenuOpenChange,
}: Props) {
  const upgradeVariant = t.needs_update ? 'success' : 'secondary';
  const upgradeTitle = inFlight
    ? 'A build is already running. Click to queue the next compile (will use the latest YAML at the time it starts).'
    : undefined;

  return (
    <div style={rowStyle}>
      <Button
        variant={upgradeVariant as 'success' | 'secondary'}
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
        onLogs={onLogs}
        onPin={onPin}
        onUnpin={onUnpin}
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
    a.pinned_version === b.pinned_version
  );
}

export const ActionsCell = memo(ActionsCellImpl, propsEqual);
