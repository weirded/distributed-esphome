import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { useEffect, useRef } from 'react';
import { buildWsUrl } from '../api/client';
import { stripYaml } from '../utils';

interface Props {
  target: string;
  onClose: () => void;
}

export function DeviceLogModal({ target, onClose }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Initialize xterm and WebSocket when the modal opens
  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      cursorBlink: false,
      disableStdin: true,
      scrollback: 50000,
      fontSize: 12,
      fontFamily: "'Fira Code', 'Cascadia Code', Consolas, monospace",
      theme: {
        background: '#0d1117',
        foreground: '#a3e635',
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
  }, [target]);

  // Keyboard handler
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const mouseDownTargetRef = useRef<EventTarget | null>(null);
  function handleOverlayMouseDown(e: React.MouseEvent<HTMLDivElement>) {
    mouseDownTargetRef.current = e.target;
  }
  function handleOverlayClick(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget && mouseDownTargetRef.current === e.currentTarget) {
      onClose();
    }
  }

  function handleDownload() {
    const term = termRef.current;
    if (!term) return;
    const buffer = term.buffer.active;
    const lines: string[] = [];
    for (let i = 0; i < buffer.length; i++) {
      lines.push(buffer.getLine(i)?.translateToString() ?? '');
    }
    const text = lines.join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    a.href = url;
    a.download = `${stripYaml(target)}-live-${ts}.log`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div
      id="device-log-modal"
      className="modal-overlay open"
      onMouseDown={handleOverlayMouseDown}
      onClick={handleOverlayClick}
    >
      <div className="modal">
        <div className="modal-header">
          <div className="modal-header-left">
            <h3>{stripYaml(target)}</h3>
            <span className="badge badge-working">Live Logs</span>
          </div>
          <button className="btn-secondary btn-sm" onClick={handleDownload} title="Download log">
            &#8595; Download
          </button>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body" style={{ padding: 0 }}>
          <div ref={containerRef} className="xterm-container" style={{ width: '100%', height: '100%' }} />
        </div>
      </div>
    </div>
  );
}
