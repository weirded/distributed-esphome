import { cn } from "@/lib/utils";

/**
 * Segmented button group (QS.13).
 *
 * Wraps two or more `<Button>` children into a single visually-joined
 * control — adjacent borders share an edge, outer corners stay rounded,
 * inner corners are squared off. Used for the Bash/PowerShell shell
 * picker in ConnectWorkerModal; structured so a future add-on (e.g. a
 * unit toggle) can drop into the same component.
 *
 * Children are expected to be `<Button>` instances. The wrapper applies
 * the segmented styling via descendant selectors so callers don't need
 * to hand-roll `border-radius: 0 / borderLeft: 1px solid` overrides on
 * each button.
 */
function ButtonGroup({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      data-slot="button-group"
      role="group"
      className={cn(
        // Container: hairline border + rounded outside, hidden overflow
        // so child borders don't bleed past the rounded corners.
        "inline-flex overflow-hidden rounded-[var(--radius)] border border-[var(--border)]",
        // Children: kill each button's own border-radius and outer border;
        // re-add a left border on every button after the first as the
        // segment divider.
        "[&>*]:rounded-none [&>*]:border-0 [&>*+*]:border-l [&>*+*]:border-l-[var(--border)]",
        className,
      )}
      {...props}
    />
  );
}

export { ButtonGroup };
