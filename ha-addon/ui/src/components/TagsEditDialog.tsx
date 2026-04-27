import { useEffect, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Button } from './ui/button';
import { TagChipInput } from './ui/tag-chip-input';

/**
 * TG.5 / TG.6 / bug #11 — chip-input tag editor used by both the Workers
 * and Devices tabs.
 *
 * Each existing tag renders as a colored chip with an inline × to remove
 * it. The trailing input lets the user type a new tag (Enter or comma to
 * commit, Backspace on empty input drops the last chip). Below the input
 * a "Suggestions" row lists fleet-wide tags not yet attached — clicking
 * one adds it. Suggestions filter to substring matches as the user types
 * so "ki…" narrows the pool to "kitchen".
 *
 * Bug #14: the seed-from-``initial`` effect only fires on the open
 * transition (false→true), not on every parent re-render — the parent
 * tab polls SWR at 1Hz and would otherwise wipe in-progress edits.
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

  /** Current tag list — controlled value the dialog seeds with on each
   *  open transition. */
  initial: string[];

  /** Fleet-wide pool of known tags (caller computes the union of every
   *  device + worker's ``tags`` array). The dialog filters out anything
   *  already on this entry and shows the remainder as clickable
   *  suggestions; substring match against the input prefix narrows them
   *  further. Empty array = no suggestions row. */
  suggestions: string[];

  /** Save handler. Receives the final tag list (no leading/trailing
   *  whitespace; duplicates already dropped). Throws on failure; the
   *  dialog catches and surfaces the error inline without closing. */
  onSave: (tags: string[]) => Promise<void>;
}

export function TagsEditDialog({ open, onOpenChange, subject, initial, suggestions, onSave }: Props) {
  const [tags, setTags] = useState<string[]>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Bug #14: re-seed only on the open transition, not on every render.
  // ``initial`` is a fresh array reference each parent SWR poll even when
  // the values are unchanged; depending on it would wipe in-progress edits.
  useEffect(() => {
    if (open) {
      setTags(initial);
      setError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave(tags);
      onOpenChange(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save tags');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false}>
        {/* shadcn DialogHeader is flex-row justify-between — keep it title-only.
            Description + body content live in the padded body section below
            so they don't collide horizontally with the title. Bug #17. */}
        <DialogHeader>
          <DialogTitle>Edit tags — {subject}</DialogTitle>
        </DialogHeader>

        <div className="px-4 py-3 space-y-3">
          <p className="text-[12px] text-[var(--text-muted)]">
            Type a tag and press Enter or comma to add, or pick from the
            autocomplete dropdown. Click × to remove.
          </p>

          {/* Bug #20: chip-input + autocomplete dropdown extracted into
              TagChipInput so ConnectWorkerModal (bug #25) can reuse the
              same UX. Enter on an empty input saves the dialog. */}
          <TagChipInput
            tags={tags}
            onChange={setTags}
            suggestions={suggestions}
            autoFocus
            onSubmit={() => { if (!saving) void handleSave(); }}
          />

          {error && (
            <div className="rounded-md border border-[var(--danger,#ef4444)] bg-[var(--danger,#ef4444)]/10 px-2.5 py-1.5 text-[12px] text-[var(--danger,#ef4444)]">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="secondary" size="sm" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
