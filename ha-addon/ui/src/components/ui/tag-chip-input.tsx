import { useMemo, useRef, useState } from 'react';
import { TagChip } from './tag-chips';

/**
 * Bug #25 — chip-input + autocomplete dropdown extracted from
 * TagsEditDialog so the ConnectWorkerModal Tags field can share the
 * same UX. Type a tag + Enter/comma to commit; Backspace on empty
 * input drops the last chip; click a dropdown row to attach an
 * existing fleet tag. Suggestions filter by substring against the
 * current input.
 */

interface Props {
  tags: string[];
  onChange: (tags: string[]) => void;
  suggestions: string[];
  placeholder?: string;
  /** Optional: fires when the user presses Enter on an empty input. The
   *  caller can use this for an "Enter = save" shortcut (TagsEditDialog
   *  does this). Empty-input Enter is a no-op when omitted. */
  onSubmit?: () => void;
  autoFocus?: boolean;
}

export function TagChipInput({
  tags,
  onChange,
  suggestions,
  placeholder,
  onSubmit,
  autoFocus = false,
}: Props) {
  const [input, setInput] = useState('');
  const [focused, setFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addTag = (raw: string) => {
    const v = raw.trim();
    if (!v) return;
    if (!tags.includes(v)) onChange([...tags, v]);
    setInput('');
    inputRef.current?.focus();
  };

  const removeTag = (t: string) => {
    onChange(tags.filter(x => x !== t));
    inputRef.current?.focus();
  };

  const filtered = useMemo(() => {
    const sel = new Set(tags);
    const q = input.trim().toLowerCase();
    return suggestions
      .filter(s => !sel.has(s))
      .filter(s => !q || s.toLowerCase().includes(q))
      .slice(0, 12);
  }, [suggestions, tags, input]);

  return (
    <div className="relative">
      <div
        className="flex flex-wrap items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface2)] px-2 py-1.5 min-h-[40px] cursor-text"
        onClick={() => inputRef.current?.focus()}
      >
        {tags.map(t => (
          <TagChip key={t} tag={t} onRemove={() => removeTag(t)} />
        ))}
        <input
          ref={inputRef}
          autoFocus={autoFocus}
          value={input}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault();
              if (input.trim()) addTag(input);
              else if (onSubmit) onSubmit();
            } else if (e.key === 'Backspace' && !input && tags.length > 0) {
              e.preventDefault();
              onChange(tags.slice(0, -1));
            } else if (e.key === 'Escape') {
              setFocused(false);
            }
          }}
          placeholder={tags.length === 0 ? placeholder ?? 'Type a tag and press Enter…' : ''}
          className="flex-1 min-w-[140px] bg-transparent outline-none text-[13px] text-[var(--text)] placeholder:text-[var(--text-muted)]"
        />
      </div>
      {focused && input.trim().length > 0 && filtered.length > 0 && (
        <div
          className="absolute left-0 right-0 top-full mt-1 z-10 rounded-md border border-[var(--border)] bg-[var(--surface)] shadow-lg max-h-[220px] overflow-y-auto py-1"
        >
          {filtered.map(t => (
            <button
              key={t}
              type="button"
              onMouseDown={(e) => {
                e.preventDefault();
                addTag(t);
              }}
              className="flex w-full items-center gap-2 px-2 py-1 text-left text-[13px] text-[var(--text)] hover:bg-[var(--surface2)]"
            >
              <TagChip tag={t} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
