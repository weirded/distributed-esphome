import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { useCallback, useEffect, useRef, useState } from 'react';
import { buildWsUrl } from '../api/client';
import { stripYaml } from '../utils';
import { copyTerminalText, downloadTerminalText } from '../utils/terminal';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Button } from './ui/button';

interface Props {
  target: string;
  onClose: () => void;
}

export function DeviceLogModal({ target, onClose }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerMounted, setContainerMounted] = useState(false);
  const termRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Track when container div is in the DOM (Dialog portal is async)
  const containerCallbackRef = useCallback((node: HTMLDivElement | null) => {
    containerRef.current = node;
    setContainerMounted(!!node);
  }, []);

  // Initialize xterm and WebSocket when the container is mounted
  useEffect(() => {
    if (!containerMounted || !containerRef.current) return;

    const term = new Terminal({
      cursorBlink: false,
      disableStdin: true,
      scrollback: 50000,
      fontSize: 12,
      fontFamily: "'Fira Code', 'Cascadia Code', Consolas, monospace",
      theme: {
        background: '#0d1117',
        foreground: '#e2e8f0',
        cursor: '#0d1117',
      },
      convertEol: true,
    });

    containerRef.current.innerHTML = '';
    term.open(containerRef.current);
    termRef.current = term;

    // Fit terminal to container — retry a few times as modal opens
    function fit() {
      if (!termRef.current) return;
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const core = (term as any)._core;
        const cellW = core?._renderService?.dimensions?.css?.cell?.width;
        const cellH = core?._renderService?.dimensions?.css?.cell?.height;
        if (cellW > 0 && cellH > 0 && containerRef.current) {
          const dims = containerRef.current.getBoundingClientRect();
          const cols = Math.max(40, Math.floor(dims.width / cellW));
          const rows = Math.max(10, Math.floor(dims.height / cellH));
          term.resize(cols, rows);
        }
      } catch { /* ignore */ }
    }
    requestAnimationFrame(fit);
    setTimeout(fit, 100);
    setTimeout(fit, 300);

    // Open WebSocket to the device log endpoint
    const wsPath = `ui/api/targets/${encodeURIComponent(target)}/logs/ws`;
    try {
      const ws = new WebSocket(buildWsUrl(wsPath));
      ws.onmessage = (e) => {
        if (termRef.current) termRef.current.write(e.data as string);
      };
      ws.onerror = () => {
        if (termRef.current) termRef.current.write('\r\nWebSocket error — connection failed.\r\n');
      };
      ws.onclose = () => {
        wsRef.current = null;
        if (termRef.current) termRef.current.write('\r\n[Connection closed]\r\n');
      };
      wsRef.current = ws;
    } catch {
      term.write('Failed to open WebSocket connection.\r\n');
    }

    return () => {
      if (wsRef.current) {
        try { wsRef.current.close(); } catch { /* ignore */ }
        wsRef.current = null;
      }
      if (termRef.current) {
        termRef.current.dispose();
        termRef.current = null;
      }
    };
  }, [target, containerMounted]);

  const handleCopy = () => copyTerminalText(termRef.current);
  const handleDownload = () => downloadTerminalText(termRef.current, stripYaml(target) + '-live');

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="dialog-lg">
        <DialogHeader>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 0 }}>
            <DialogTitle>{stripYaml(target)}</DialogTitle>
            <span className="inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide bg-[#1e3a5f] text-[#60a5fa]">Live Logs</span>
          </div>
          <Button variant="secondary" size="sm" onClick={handleCopy} title="Copy log to clipboard">
            Copy
          </Button>
          <Button variant="secondary" size="sm" onClick={handleDownload} title="Download log as file">
            &#8595; Download
          </Button>
        </DialogHeader>
        <div style={{ flex: 1, padding: 0, overflow: 'hidden' }}>
          <div ref={containerCallbackRef} className="xterm-container" style={{ width: '100%', height: '100%' }} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
