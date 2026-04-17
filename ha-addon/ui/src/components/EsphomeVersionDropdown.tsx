import { useMemo, useState } from 'react';
import { RotateCw } from 'lucide-react';
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

function isBeta(v: string): boolean {
  return /\d(a|b|rc|dev)\d/i.test(v);
}

export function EsphomeVersionDropdown({ versions, onSelect, onRefresh }: Props) {
  const sel = versions.selected || '?';
  const [search, setSearch] = useState('');
  const [showBetas, setShowBetas] = useState(false);

  const filtered = useMemo(() => {
    let list = versions.available;
    if (!showBetas) list = list.filter(v => !isBeta(v));
    if (search) {
      const lc = search.toLowerCase();
      list = list.filter(v => v.toLowerCase().includes(lc));
    }
    return list;
  }, [versions.available, showBetas, search]);

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
    <DropdownMenu>
      <DropdownMenuTrigger className="rounded-full border border-[var(--border)] bg-[var(--surface2)] px-2 py-0.5 text-[11px] text-[var(--text-muted)] whitespace-nowrap" title="Click to change ESPHome version" style={{ cursor: 'pointer' }}>
        ESPHome {sel} <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" style={{ display: 'inline', verticalAlign: 'middle' }}><path d="m6 9 6 6 6-6"/></svg>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" style={{ maxHeight: 400, overflowY: 'auto' }}>
        <DropdownMenuGroup>
          <DropdownMenuLabel>ESPHome Version</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <div className="px-2 pb-1.5 flex flex-col gap-1.5">
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search versions..."
              className="w-full rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-[12px] text-[var(--text)] outline-none placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]"
              onClick={e => e.stopPropagation()}
              onKeyDown={e => e.stopPropagation()}
            />
            <label className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)] cursor-pointer">
              <input type="checkbox" checked={showBetas} onChange={e => setShowBetas(e.target.checked)} />
              Show betas
            </label>
          </div>
          <DropdownMenuSeparator />
          {filtered.length === 0 ? (
            <DropdownMenuItem disabled>
              {versions.available.length === 0 ? 'Loading...' : 'No matches'}
            </DropdownMenuItem>
          ) : (
            filtered.map(v => (
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
        className="inline-flex items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface2)] w-[22px] h-[22px] text-[var(--text-muted)] cursor-pointer hover:bg-[var(--border)]"
        title="Refresh available ESPHome versions from PyPI"
        aria-label="Refresh ESPHome versions"
        onClick={onRefresh}
      >
        <RotateCw className="size-3" />
      </button>
    )}
    </span>
  );
}
