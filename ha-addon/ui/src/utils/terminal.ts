import { toast } from 'sonner';
import type { Terminal } from '@xterm/xterm';

export function getTerminalText(term: Terminal | null): string {
  if (!term) return '';
  const buffer = term.buffer.active;
  const lines: string[] = [];
  for (let i = 0; i < buffer.length; i++) {
    lines.push(buffer.getLine(i)?.translateToString() ?? '');
  }
  return lines.join('\n');
}

export function copyTerminalText(term: Terminal | null): void {
  const text = getTerminalText(term);
  if (!text) return;
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(() => toast.success('Copied to clipboard'));
  } else {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;opacity:0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    toast.success('Copied to clipboard');
  }
}

export function downloadTerminalText(term: Terminal | null, filename: string): void {
  const text = getTerminalText(term);
  if (!text) return;
  const blob = new Blob([text], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  a.href = url;
  a.download = `${filename}-${ts}.log`;
  a.click();
  URL.revokeObjectURL(url);
}

/** Trigger a browser download of an in-memory text string. Timestamp
 * is appended so repeated downloads don't collide in the browser's
 * downloads folder. (#109 — used by Request diagnostics.) */
export function downloadTextFile(text: string, filename: string): void {
  const blob = new Blob([text], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const base = filename.replace(/\.txt$/, '');
  a.href = url;
  a.download = `${base}-${ts}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}
