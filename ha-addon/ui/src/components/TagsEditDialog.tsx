import { useEffect, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from './ui/dialog';
import { Button } from './ui/button';
import { Input } from './ui/input';

/**
 * TG.6 / TG.5 — first-cut tag editor used by both the Workers and Devices
 * tabs. Plain comma-separated text input; the server normalises (trim /
 * drop-empty / dedupe) so a paste like ``"prod, prod, linux"`` saves as
 * ``["prod", "linux"]`` without a chip-input library on the UI side.
 *
 * Designed for tag *editing*, not *routing-rule authoring* — when TG.7's
 * autocomplete chip-input lands the dialog content gets swapped, the
 * `onSave([...])` API stays the same.
 */

interface Props {
  /** Open/close state owned by the parent (so the parent can lift it out
   *  of any TanStack row cell — same `actionsMenuOpenClientId` pattern as
   *  the Workers Actions menu, see CLAUDE.md "Lift DropdownMenu open state
   *  out of any row cell"). */
  open: boolean;
  onOpenChange: (open: boolean) => void;

  /** Human-readable subject line — "Worker macdaddy" / "Device kitchen.yaml". */
  subject: string;

  /** Current tag list — controlled value the dialog seeds its input with. */
  initial: string[];

  /** Save handler. Receives the parsed list (no leading/trailing whitespace
   *  on members; the server normalises further). Throws on failure; the
   *  dialog catches and surfaces the error inline without closing. */
  onSave: (tags: string[]) => Promise<void>;
}

function parseInput(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of raw.split(',')) {
    const t = part.trim();
    if (!t || seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  return out;
}

export function TagsEditDialog({ open, onOpenChange, subject, initial, onSave }: Props) {
  const [text, setText] = useState(() => initial.join(', '));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-seed when the dialog re-opens for a different subject.
  useEffect(() => {
    if (open) {
      setText(initial.join(', '));
      setError(null);
    }
  }, [open, initial]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave(parseInput(text));
      onOpenChange(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save tags');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit tags — {subject}</DialogTitle>
          <DialogDescription>
            Comma-separated tag list. Leading/trailing whitespace is trimmed,
            empties and duplicates are dropped on save.
          </DialogDescription>
        </DialogHeader>
        <Input
          value={text}
          autoFocus
          placeholder="e.g. prod, fast, linux"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !saving) {
              e.preventDefault();
              void handleSave();
            }
          }}
        />
        {error && (
          <div className="rounded-md border border-[var(--danger,#ef4444)] bg-[var(--danger,#ef4444)]/10 px-2 py-1 text-[12px] text-[var(--danger,#ef4444)]">
            {error}
          </div>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="secondary" size="sm" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
