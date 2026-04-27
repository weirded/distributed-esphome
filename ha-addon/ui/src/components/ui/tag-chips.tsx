import { X } from 'lucide-react';

/**
 * TG.5 / TG.6 — render a worker or device tag as a colored chip pill.
 *
 * Bug #6: each tag picks a color from a 12-hue palette via a stable djb2
 * hash of its text. Same tag string → same color across rows / tabs /
 * pages so "kitchen" looks the same on a device row as on a worker row,
 * and "prod" stays visually distinct from "linux".
 *
 * Bug #12: GitHub-issue-label-style solid chips (saturated mid-tone bg
 * with white text) instead of washed-out pastels. The single palette
 * works on both ``[data-theme="light"]`` and ``[data-theme="dark"]``
 * surfaces because ``hsl(h, 65%, 45%)`` is dark enough for white text
 * to read AA-contrast and saturated enough to register as the chip's
 * color (not gray) against either surface.
 *
 * Bug #11: ``TagChip`` accepts an optional ``onRemove`` handler — passing
 * one renders a small × inside the chip so the editor can mutate. Without
 * it the chip is a plain read-only pill, identical to what the table
 * cells render.
 */

// Bug #24: doubled the palette from 12 to 24 colors and widened the
// hue + lightness spread so adjacent tags read as different colors at
// chip size. The dev.10 (#21) palette only used Tailwind's 600 stop
// across 12 hues — clusters like red/orange or violet/fuchsia/pink
// still felt "the same color" at 12px when two of them landed next to
// each other in a row. Now we cover 17 Tailwind 600 hues (the full
// spectrum) plus 7 darker 800-stop variants of widely-spaced hues to
// add a second "perceptual band" of identity. White text reads
// AA-contrast on every entry, on both ``[data-theme="light"]`` and
// ``[data-theme="dark"]`` surfaces.
const PALETTE: { bg: string; border: string }[] = [
  // 600-stop, full Tailwind spectrum — 17 distinct hues.
  { bg: '#dc2626', border: '#991b1b' }, // red-600
  { bg: '#ea580c', border: '#9a3412' }, // orange-600
  { bg: '#d97706', border: '#92400e' }, // amber-600
  { bg: '#ca8a04', border: '#854d0e' }, // yellow-600
  { bg: '#65a30d', border: '#3f6212' }, // lime-600
  { bg: '#16a34a', border: '#15803d' }, // green-600
  { bg: '#059669', border: '#065f46' }, // emerald-600
  { bg: '#0d9488', border: '#115e59' }, // teal-600
  { bg: '#0891b2', border: '#155e75' }, // cyan-600
  { bg: '#0284c7', border: '#075985' }, // sky-600
  { bg: '#2563eb', border: '#1e40af' }, // blue-600
  { bg: '#4f46e5', border: '#3730a3' }, // indigo-600
  { bg: '#7c3aed', border: '#5b21b6' }, // violet-600
  { bg: '#9333ea', border: '#6b21a8' }, // purple-600
  { bg: '#c026d3', border: '#86198f' }, // fuchsia-600
  { bg: '#db2777', border: '#9d174d' }, // pink-600
  { bg: '#e11d48', border: '#9f1239' }, // rose-600
  // 800-stop darker variants of widely-spaced hues — second perceptual
  // band so the same-hash-bucket-collision risk drops in half.
  { bg: '#7f1d1d', border: '#450a0a' }, // red-800
  { bg: '#854d0e', border: '#422006' }, // yellow-800 (mustard)
  { bg: '#166534', border: '#052e16' }, // green-800
  { bg: '#155e75', border: '#083344' }, // cyan-800
  { bg: '#1e3a8a', border: '#172554' }, // blue-900-ish
  { bg: '#5b21b6', border: '#2e1065' }, // violet-800
  { bg: '#9d174d', border: '#500724' }, // pink-800
  // Neutral fallback.
  { bg: '#475569', border: '#334155' }, // slate-600
];

function tagHueIndex(tag: string): number {
  // djb2 hash — small, stable, no deps. Same tag string always picks
  // the same palette entry, regardless of where it's rendered.
  let h = 5381;
  for (let i = 0; i < tag.length; i++) {
    h = ((h << 5) + h + tag.charCodeAt(i)) | 0;
  }
  return Math.abs(h) % PALETTE.length;
}

function tagChipStyle(tag: string): { background: string; borderColor: string; color: string } {
  const c = PALETTE[tagHueIndex(tag)];
  return {
    background: c.bg,
    borderColor: c.border,
    color: '#ffffff',
  };
}

interface ChipProps {
  tag: string;
  /** Bug #11: render an inline × the caller can wire to "remove this tag". */
  onRemove?: () => void;
  /** Optional click handler for the whole chip (e.g. picker suggestions
   *  call ``addTag(t)`` when the user clicks). Mutually exclusive with
   *  ``onRemove`` in practice — a chip is either "click body to add" or
   *  "click × to remove". */
  onClick?: () => void;
  /** TG.5/TG.6 filter pill: optional usage count rendered as a faint
   *  ``(N)`` suffix. Doesn't participate in the color hash so the same
   *  tag stays the same color across rows / pill-bar / editor. */
  count?: number;
}

export function TagChip({ tag, onRemove, onClick, count }: ChipProps) {
  const s = tagChipStyle(tag);
  const interactive = onClick != null;
  return (
    <span
      className={
        // Bug #15: drop the Lucide Tag icon — the chip color + text is
        // already a strong "this is a tag" signal, the icon just ate
        // horizontal space in narrow table cells.
        // Bug #16: bumped to 12px / 1.5 line-height for legibility now
        // that the column has more room.
        'inline-flex items-center rounded-full border px-2 py-0.5 text-[12px] leading-tight ' +
        (interactive ? 'cursor-pointer hover:opacity-90 transition-opacity' : '')
      }
      style={s}
      title={`Tag: ${tag}`}
      onClick={onClick}
      role={interactive ? 'button' : undefined}
    >
      {tag}
      {count != null && (
        <span className="ml-1 opacity-70 text-[10px]">({count})</span>
      )}
      {onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          aria-label={`Remove tag ${tag}`}
          className="ml-1 inline-flex size-3.5 items-center justify-center rounded-full bg-white/20 hover:bg-white/40"
          tabIndex={-1}
        >
          <X className="size-2.5" />
        </button>
      )}
    </span>
  );
}

export function TagChips({ tags }: { tags: string[] | null | undefined }) {
  if (!tags || tags.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {tags.map(t => <TagChip key={t} tag={t} />)}
    </span>
  );
}
