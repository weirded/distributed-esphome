import { Download } from 'lucide-react';

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './ui/dropdown-menu';

/**
 * Bug #1 (1.6.1): shared firmware Download dropdown for the Queue tab
 * (QueueTab), the per-device Compile-history drawer, and the fleet-wide
 * Queue History dialog. All three surfaces rendered the same set of .bin
 * / .bin.gz × factory / ota links with slightly different copy and a
 * copy-pasted Base-UI dropdown — extracted here so we can't drift.
 *
 * Parent controls the ``open`` state via ``(open, onOpenChange)`` so
 * rows in TanStack tables don't re-mount the menu mid-click when SWR
 * hands us a fresh data reference. This is the same pattern we use for
 * the Devices-tab hamburger (#2, 1.4.1) and the Queue tab's original
 * inline dropdown (#71, 1.5.0); consolidated here.
 */

const variantLabel = (variant: string): string => {
  switch (variant) {
    case 'factory': return 'Factory image';
    case 'ota':     return 'OTA image';
    case 'firmware': return 'Firmware';
    default:        return variant;
  }
};

interface Props {
  jobId: string;
  variants: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Optional label override — history rows prefer a bare icon to save
   *  table width, the Queue row uses the labelled "Download" button. */
  label?: string;
  /** Size of the trigger. ``sm`` matches the Queue row's other action
   *  buttons; ``icon`` collapses to a 28×28 square for history tables. */
  size?: 'sm' | 'icon';
}

export function FirmwareDownloadMenu({
  jobId,
  variants,
  open,
  onOpenChange,
  label = 'Download',
  size = 'sm',
}: Props) {
  if (variants.length === 0) return null;

  const triggerClass = size === 'icon'
    ? 'inline-flex items-center justify-center rounded-lg border border-border bg-background h-7 w-7 text-foreground hover:bg-muted cursor-pointer'
    : 'inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2.5 h-7 text-[0.8rem] font-medium text-foreground hover:bg-muted cursor-pointer';

  return (
    <DropdownMenu open={open} onOpenChange={onOpenChange}>
      <DropdownMenuTrigger
        className={triggerClass}
        title="Download compiled firmware"
        aria-label="Download firmware"
        onClick={(e) => e.stopPropagation()}
      >
        <Download className="size-3.5" aria-hidden="true" />
        {size === 'sm' && <span>{label}</span>}
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuGroup>
          {variants.map((variant) => (
            <DropdownMenuItem
              key={`${variant}-raw`}
              render={(props) => (
                <a
                  {...props}
                  href={`./ui/api/jobs/${jobId}/firmware?variant=${variant}`}
                  download
                  onClick={(e) => e.stopPropagation()}
                >
                  {variantLabel(variant)} (.bin)
                </a>
              )}
            />
          ))}
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          {variants.map((variant) => (
            <DropdownMenuItem
              key={`${variant}-gz`}
              render={(props) => (
                <a
                  {...props}
                  href={`./ui/api/jobs/${jobId}/firmware?variant=${variant}&gz=1`}
                  download
                  onClick={(e) => e.stopPropagation()}
                >
                  {variantLabel(variant)} (.bin.gz)
                </a>
              )}
            />
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
