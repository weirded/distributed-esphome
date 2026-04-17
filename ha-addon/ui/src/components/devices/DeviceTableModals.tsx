import { useEffect, useRef, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '../ui/dialog';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { stripYaml } from '../../utils';

/**
 * Modals used by the Devices tab (QS.19).
 *
 * Extracted from DevicesTab.tsx as part of the 1.4.1 DevicesTab split. No
 * behavior changes — same rendering, same state machine. Enables the next
 * extractions (DeviceTableActions, useDeviceColumns) to happen against a
 * smaller DevicesTab.tsx.
 *
 * RenameModal is re-exported from ../DevicesTab for existing App.tsx imports.
 */

export function RenameModal({ currentName, onConfirm, onClose }: {
  currentName: string;
  onConfirm: (newName: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(stripYaml(currentName));
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.select(); }, []);

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rename Device</DialogTitle>
        </DialogHeader>
        <div className="p-4">
          <Label htmlFor="rename-device-name" className="text-[12px] normal-case tracking-normal mb-1.5">
            New device name
          </Label>
          <Input
            id="rename-device-name"
            ref={inputRef}
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && name.trim() && name.trim() !== stripYaml(currentName) && onConfirm(name.trim())}
          />
          <p className="text-[12px] text-[var(--text-muted)] mt-2">
            This will update the config file, rename it, and compile + upgrade the device with the new name via OTA.
          </p>
        </div>
        <DialogFooter>
          <Button variant="secondary" size="sm" onClick={onClose}>Cancel</Button>
          <Button
            size="sm"
            disabled={!name.trim() || name.trim() === stripYaml(currentName)}
            onClick={() => onConfirm(name.trim())}
          >
            Rename &amp; Upgrade
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function DeleteModal({ target, onConfirm, onClose }: {
  target: string;
  onConfirm: (archive: boolean) => void;
  onClose: () => void;
}) {
  const [confirmPermanent, setConfirmPermanent] = useState(false);

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete Device</DialogTitle>
        </DialogHeader>
        <div style={{ padding: '16px' }}>
          {!confirmPermanent ? (
            <p>Are you sure you want to delete <strong>{stripYaml(target)}</strong>?</p>
          ) : (
            <p style={{ color: 'var(--danger)' }}>
              This will <strong>permanently delete</strong> {stripYaml(target)}. This cannot be undone.
            </p>
          )}
        </div>
        <DialogFooter>
          {!confirmPermanent ? (
            <>
              <Button variant="secondary" size="sm" onClick={onClose}>Cancel</Button>
              <Button variant="warn" size="sm" onClick={() => onConfirm(true)}>Archive</Button>
              <Button variant="destructive" size="sm" onClick={() => setConfirmPermanent(true)}>Delete Permanently</Button>
            </>
          ) : (
            <>
              <Button variant="secondary" size="sm" onClick={() => setConfirmPermanent(false)}>Back</Button>
              <Button variant="destructive" size="sm" onClick={() => onConfirm(false)}>Yes, Delete Forever</Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
