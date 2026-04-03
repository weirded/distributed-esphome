import { useEffect, useRef } from 'react';
import type { EsphomeVersions } from '../types';

interface Props {
  versions: EsphomeVersions;
  open: boolean;
  onToggle: (e: React.MouseEvent) => void;
  onSelect: (version: string) => void;
}

export function EsphomeVersionDropdown({ versions, open, onToggle, onSelect }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handler(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        // Trigger a synthetic click to let parent know — but parent handles document clicks
      }
    }
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [open]);

  const sel = versions.selected || '?';

  return (
    <div className="esphome-version-wrap" ref={wrapRef}>
      <span className="version-badge" onClick={onToggle} title="Click to change ESPHome version">
        ESPHome {sel} <span className="esphome-version-caret">&#9660;</span>
      </span>
      <div className={`esphome-version-dropdown${open ? ' open' : ''}`}>
        <div className="vd-header">ESPHome Version</div>
        {versions.available.length === 0 ? (
          <div className="vd-loading">Loading...</div>
        ) : (
          versions.available.map(v => (
            <div
              key={v}
              className={`vd-item${v === versions.selected ? ' active' : ''}`}
              onClick={() => onSelect(v)}
            >
              <span>{v}</span>
              {v === versions.detected && <span className="vd-label">(installed)</span>}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
