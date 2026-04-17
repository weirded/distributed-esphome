import { cn } from "@/lib/utils";

/**
 * Field label component (QS.11).
 *
 * The "block field-label" pattern — uppercase, tracking-wide, muted text
 * sitting above an input — appears 11+ times across `ConnectWorkerModal`,
 * `UpgradeModal`, and `DeviceTableModals`. Each instance was hand-rolling
 * the same Tailwind class string. Centralized here so a future tweak (e.g.
 * adopting a `text-foreground/60` color token) lands in one place.
 *
 * Pass `htmlFor` to associate the label with an input by id — recommended
 * for accessibility (clicking the label focuses the field, screen readers
 * announce them together).
 */
function Label({
  className,
  ...props
}: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      data-slot="label"
      className={cn(
        "block text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)] mb-1",
        className,
      )}
      {...props}
    />
  );
}

export { Label };
