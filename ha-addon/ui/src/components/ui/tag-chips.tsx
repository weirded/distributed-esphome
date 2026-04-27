import { Tag } from 'lucide-react';

/**
 * TG.5 / TG.6 — render a worker or device tag list as chip pills.
 *
 * Bug #6: each tag picks a color from a fixed palette via a stable hash of
 * its text. Same tag → same color across rows / tabs / pages. Light-mode
 * and dark-mode palettes are intentionally desaturated (HSL S=70%, L=88%
 * for light backgrounds; S=55%, L=22% for dark backgrounds) so the table
 * doesn't look like a circus. Foreground text picks the darker / lighter
 * end of the same hue so contrast stays AA against the chosen background.
 *
 * The empty case renders nothing so the cell is visually empty rather than
 * stamped with an em-dash — matches the TG.5 spec ("Empty-cell rendering:
 * leave blank, not '—'").
 */

// 12 hues spaced ~30° apart around the HSL wheel. Enough variety that
// real fleets ("kitchen", "office", "garage", "prod", "linux", "fast")
// rarely collide; small enough that the table doesn't get loud.
const HUES = [0, 30, 60, 95, 130, 160, 190, 215, 240, 270, 300, 335];

function tagHueIndex(tag: string): number {
  // djb2 — small, stable, no deps. Same tag string always maps to the
  // same hue, regardless of where it's rendered.
  let h = 5381;
  for (let i = 0; i < tag.length; i++) {
    h = ((h << 5) + h + tag.charCodeAt(i)) | 0;
  }
  return Math.abs(h) % HUES.length;
}

interface ChipStyle {
  background: string;
  borderColor: string;
  color: string;
}

function tagChipStyle(tag: string): ChipStyle {
  const hue = HUES[tagHueIndex(tag)];
  // One palette, intentionally readable on both themes. The project uses
  // a manual ``[data-theme="light"]`` toggle (theme.css) rather than
  // prefers-color-scheme, so ``light-dark()`` doesn't work here. Pastel
  // background (50% S / 85% L) provides contrast against the dark app
  // surface ``#1a1d27`` and against the light surface ``#ffffff``;
  // dark same-hue text (70% S / 25% L) is AA-readable against the
  // pastel background regardless of theme.
  return {
    background: `hsl(${hue}, 60%, 88%)`,
    borderColor: `hsl(${hue}, 40%, 70%)`,
    color: `hsl(${hue}, 60%, 22%)`,
  };
}

export function TagChips({ tags }: { tags: string[] | null | undefined }) {
  if (!tags || tags.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {tags.map(t => {
        const s = tagChipStyle(t);
        return (
          <span
            key={t}
            className="inline-flex items-center gap-0.5 rounded-full border px-1.5 py-px text-[10px] leading-none"
            style={s}
            title={`Tag: ${t}`}
          >
            <Tag className="size-2.5" aria-hidden="true" />
            {t}
          </span>
        );
      })}
    </span>
  );
}
