import type { EsphomeVersions } from '../types';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from './ui/dropdown-menu';

interface Props {
  versions: EsphomeVersions;
  onSelect: (version: string) => void;
  onRefresh?: () => void;
}

export function EsphomeVersionDropdown({ versions, onSelect, onRefresh }: Props) {
  const sel = versions.selected || '?';

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
    <DropdownMenu>
      <DropdownMenuTrigger className="rounded-full border border-[var(--border)] bg-[var(--surface2)] px-2 py-0.5 text-[11px] text-[var(--text-muted)] whitespace-nowrap" title="Click to change ESPHome version" style={{ cursor: 'pointer' }}>
        ESPHome {sel} &#9660;
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuGroup>
          <DropdownMenuLabel>ESPHome Version</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {versions.available.length === 0 ? (
            <DropdownMenuItem disabled>Loading...</DropdownMenuItem>
          ) : (
            versions.available.map(v => (
              <DropdownMenuItem
                key={v}
                onClick={() => onSelect(v)}
                style={v === versions.selected ? { color: 'var(--accent)', fontWeight: 600 } : undefined}
              >
                {v}
                {v === versions.detected && (
                  <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 8 }}>(installed)</span>
                )}
              </DropdownMenuItem>
            ))
          )}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
    {onRefresh && (
      <button
        className="rounded-full border border-[var(--border)] bg-[var(--surface2)] px-1.5 py-0.5 text-[11px] text-[var(--text-muted)] cursor-pointer hover:bg-[var(--border)]"
        title="Refresh available ESPHome versions from PyPI"
        onClick={onRefresh}
      >
        &#8635;
      </button>
    )}
    </span>
  );
}
