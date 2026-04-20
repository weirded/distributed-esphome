/**
 * Minimal ANSI SGR → React renderer.
 *
 * PlatformIO / ESPHome compile output sprinkles SGR colour codes
 * (`\x1b[31m…\x1b[0m`) into its logs. In the Queue tab's live log modal
 * xterm.js interprets them natively, but for *static* log-excerpt
 * rendering in the Job History drawers (JH.5 / JH.7) we just want text
 * with the right colour — no terminal emulator, no selection model,
 * no scrollback. A 30-line regex-driven splitter is the right size.
 *
 * Supports: foreground 30–37 / 90–97, background 40–47 / 100–107,
 * bold (1), dim (2), and reset (0 or empty params). 256-colour and
 * truecolour sequences are accepted syntactically but rendered in the
 * default colour — this is a readability aid, not a faithful terminal.
 * Non-SGR escape sequences (cursor motion, screen clear, etc.) are
 * stripped so they don't show up as literal mojibake.
 */

import type { ReactNode } from 'react';

// 8-colour palette + bright variants. Dark theme — these are the
// xterm.js defaults tuned to stay readable against var(--surface2).
const FG: Record<number, string> = {
  30: '#000000', 31: '#cd3131', 32: '#0dbc79', 33: '#e5e510',
  34: '#2472c8', 35: '#bc3fbc', 36: '#11a8cd', 37: '#e5e5e5',
  90: '#666666', 91: '#f14c4c', 92: '#23d18b', 93: '#f5f543',
  94: '#3b8eea', 95: '#d670d6', 96: '#29b8db', 97: '#ffffff',
};
const BG: Record<number, string> = {
  40: '#000000', 41: '#cd3131', 42: '#0dbc79', 43: '#e5e510',
  44: '#2472c8', 45: '#bc3fbc', 46: '#11a8cd', 47: '#e5e5e5',
  100: '#666666', 101: '#f14c4c', 102: '#23d18b', 103: '#f5f543',
  104: '#3b8eea', 105: '#d670d6', 106: '#29b8db', 107: '#ffffff',
};

type Style = {
  color?: string;
  backgroundColor?: string;
  fontWeight?: 'bold';
  opacity?: number;
};

function applyParams(style: Style, params: number[]): Style {
  // Empty param set == CSI[m == reset — matches xterm.
  if (params.length === 0) return {};
  let s: Style = { ...style };
  let i = 0;
  while (i < params.length) {
    const p = params[i];
    if (p === 0) { s = {}; i++; continue; }
    if (p === 1) { s.fontWeight = 'bold'; i++; continue; }
    if (p === 2) { s.opacity = 0.7; i++; continue; }
    if (p === 22) { delete s.fontWeight; delete s.opacity; i++; continue; }
    if (p === 39) { delete s.color; i++; continue; }
    if (p === 49) { delete s.backgroundColor; i++; continue; }
    if (FG[p]) { s.color = FG[p]; i++; continue; }
    if (BG[p]) { s.backgroundColor = BG[p]; i++; continue; }
    // 256-colour (38;5;n) and truecolour (38;2;r;g;b) — swallow the
    // sub-args without applying a colour. Keeping the logic honest is
    // not worth the weight for a static-log-viewer.
    if (p === 38 || p === 48) {
      const mode = params[i + 1];
      if (mode === 5) i += 3;
      else if (mode === 2) i += 5;
      else i += 2;
      continue;
    }
    i++;
  }
  return s;
}

// Match a CSI sequence. Supports the SGR ("m") family + swallows every
// other terminal control sequence (cursor moves, erase, bell, etc.).
const CSI_RE = /\x1b\[([0-9;]*)([A-Za-z])|\x1b\]([^\x07]*?)\x07|\x1b[=>]/g;

export function renderAnsi(raw: string): ReactNode {
  if (!raw) return null;
  // Bug #51: PlatformIO emits progress bars as `partial\rpartial\r…final\n`
  // where each `\r` means "redraw this line from column 0". The previous
  // implementation dropped the `\r` outright which left *all* the partial
  // states concatenated end-to-end — unreadable garbage. Proper terminal
  // semantics: split into physical lines by `\n`, and within each line
  // keep only the segment after the last `\r` (the final frame of that
  // line's redraw sequence). `\r\n` pairs are normalized to `\n`.
  const physicalLines = raw.replace(/\r\n/g, '\n').split('\n');
  const input = physicalLines
    .map((line) => {
      const lastCr = line.lastIndexOf('\r');
      return lastCr === -1 ? line : line.slice(lastCr + 1);
    })
    .join('\n');

  const out: ReactNode[] = [];
  let style: Style = {};
  let lastIdx = 0;
  let segKey = 0;

  const pushSegment = (text: string) => {
    if (!text) return;
    if (Object.keys(style).length === 0) {
      out.push(text);
    } else {
      out.push(<span key={segKey++} style={style}>{text}</span>);
    }
  };

  let m: RegExpExecArray | null;
  CSI_RE.lastIndex = 0;
  while ((m = CSI_RE.exec(input)) !== null) {
    pushSegment(input.slice(lastIdx, m.index));
    lastIdx = m.index + m[0].length;
    // Only CSI-SGR (final byte === 'm') applies style; others just get
    // stripped from the output.
    if (m[2] === 'm') {
      const params = m[1] === ''
        ? []
        : m[1].split(';').map((p) => (p === '' ? 0 : parseInt(p, 10))).filter((n) => !Number.isNaN(n));
      style = applyParams(style, params);
    }
  }
  pushSegment(input.slice(lastIdx));
  return out;
}
