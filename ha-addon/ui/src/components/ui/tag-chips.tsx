import { Tag } from 'lucide-react';

/**
 * TG.5 / TG.6 — render a worker or device tag list as chip pills.
 *
 * Read-only first cut; inline edit + click-to-filter handlers land later
 * (TG.5 + TG.6 follow-up turns). The empty case renders nothing so the
 * cell is visually empty rather than stamped with an em-dash — matches
 * the spec ("Empty-cell rendering: leave blank, not '—'").
 */
export function TagChips({ tags }: { tags: string[] | null | undefined }) {
  if (!tags || tags.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {tags.map(t => (
        <span
          key={t}
          className="inline-flex items-center gap-0.5 rounded-full border border-[var(--border)] bg-[var(--surface2)] px-1.5 py-px text-[10px] leading-none text-[var(--text-muted)]"
          title={`Tag: ${t}`}
        >
          <Tag className="size-2.5" aria-hidden="true" />
          {t}
        </span>
      ))}
    </span>
  );
}
