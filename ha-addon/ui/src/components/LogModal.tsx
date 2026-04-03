import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { useCallback, useEffect, useRef, useState } from 'react';
import { buildWsUrl, getJobLog } from '../api/client';
import type { Job, Worker } from '../types';
import { fmtDuration, getJobBadge } from '../utils';

interface Props {
  jobId: string | null;
  queue: Job[];
  workers: Worker[];
  onClose: () => void;
  onRetry: (ids: string[]) => void;
  onEdit?: (target: string) => void;
}

export function LogModal({ jobId, queue, workers, onClose, onRetry, onEdit }: Props) {
  const isOpen = jobId !== null;
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollOffsetRef = useRef(0);
  const pollJobIdRef = useRef<string | null>(null);
  const mountedRef = useRef(false);

  // Live header updates
  const [, forceUpdate] = useState(0);
  const headerTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const job = jobId ? queue.find(j => j.id === jobId) ?? null : null;

  // Force header re-render every second while open
  useEffect(() => {
    if (!isOpen) return;
    headerTimerRef.current = setInterval(() => forceUpdate(n => n + 1), 1000);
    return () => {
      if (headerTimerRef.current) clearInterval(headerTimerRef.current);
    };
  }, [isOpen]);

  function stopWs() {
    if (wsRef.current) {
      try { wsRef.current.close(); } catch { /* ignore */ }
      wsRef.current = null;
    }
  }

  function stopPolling() {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    pollJobIdRef.current = null;
  }

  function disposeTerminal() {
    if (termRef.current) {
      termRef.current.dispose();
      termRef.current = null;
    }
  }

  const startPolling = useCallback((pJobId: string) => {
    pollOffsetRef.current = 0;
    pollJobIdRef.current = pJobId;

    async function poll() {
      if (!pollJobIdRef.current || !mountedRef.current) return;
      try {
        const data = await getJobLog(pollJobIdRef.current, pollOffsetRef.current);
        if (data.log && termRef.current) termRef.current.write(data.log);
        pollOffsetRef.current = data.offset;
        if (!data.finished) {
          pollTimerRef.current = setTimeout(poll, 500);
          return;
        }
      } catch { /* ignore */ }
      pollTimerRef.current = setTimeout(poll, 500);
    }

    poll();
  }, []);

  // Initialize terminal and connections when jobId changes
  useEffect(() => {
    mountedRef.current = true;
    if (!jobId || !containerRef.current) return;

    // Clean up previous
    stopWs();
    stopPolling();
    disposeTerminal();

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
        // Access internal render dimensions for precise cell size
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

    const currentJob = queue.find(j => j.id === jobId);
    const isLive = currentJob && ['working', 'pending'].includes(currentJob.state);

    if (isLive) {
      // Prefer WebSocket, fall back to HTTP polling
      try {
        const ws = new WebSocket(buildWsUrl(`ui/api/jobs/${jobId}/log/ws`));
        ws.onmessage = (e) => { if (termRef.current) termRef.current.write(e.data as string); };
        ws.onerror = () => {
          stopWs();
          startPolling(jobId);
        };
        ws.onclose = () => { wsRef.current = null; };
        wsRef.current = ws;
      } catch {
        startPolling(jobId);
      }
    } else if (currentJob?.log) {
      term.write(currentJob.log);
    }

    return () => {
      mountedRef.current = false;
      stopWs();
      stopPolling();
      disposeTerminal();
    };
    // We deliberately don't re-run when queue changes — only when jobId changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, startPolling]);

  // Keyboard handler
  useEffect(() => {
    if (!isOpen) return;
    function handler(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  // Only close on overlay click if mousedown also started on the overlay.
  // This prevents closing when the user drags to select text and the drag
  // ends outside the modal content area.
  const mouseDownTargetRef = useRef<EventTarget | null>(null);
  function handleOverlayMouseDown(e: React.MouseEvent<HTMLDivElement>) {
    mouseDownTargetRef.current = e.target;
  }
  function handleOverlayClick(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget && mouseDownTargetRef.current === e.currentTarget) {
      onClose();
    }
  }

  // Compute header contents from current job state
  let modalTitle = '';
  let badgeEl: React.ReactNode = null;
  let metaEl: React.ReactNode = null;
  let retryEl: React.ReactNode = null;

  if (job) {
    modalTitle = job.target;
    const { label, cls } = getJobBadge(job);
    badgeEl = <span className={cls}>{label}</span>;

    const clientName =
      job.assigned_hostname ||
      (job.assigned_client_id
        ? workers.find(c => c.client_id === job.assigned_client_id)?.hostname ||
          job.assigned_client_id.slice(0, 8)
        : null);
    const dur = job.duration_seconds != null ? fmtDuration(job.duration_seconds) + ' duration' : null;
    const meta = [clientName, dur].filter(Boolean).join(' · ');
    if (meta) {
      metaEl = <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{meta}</span>;
    }

    if (['failed', 'timed_out', 'success'].includes(job.state)) {
      retryEl = (
        <button
          className="btn-warn btn-sm"
          onClick={() => { onRetry([job.id]); onClose(); }}
        >
          Retry
        </button>
      );
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
    a.download = `${job?.target ?? 'log'}-${ts}.log`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div
      id="log-modal"
      className={`modal-overlay${isOpen ? ' open' : ''}`}
      onMouseDown={handleOverlayMouseDown}
      onClick={handleOverlayClick}
    >
      <div className="modal">
        <div className="modal-header">
          <div className="modal-header-left">
            <h3>{modalTitle}</h3>
            {badgeEl}
            {metaEl}
            {retryEl}
          </div>
          {onEdit && job && (
            <button
              className="btn-secondary btn-sm"
              onClick={() => { onEdit(job.target); onClose(); }}
              title="Open config in editor"
            >
              Edit
            </button>
          )}
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
