import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { useCallback, useEffect, useRef, useState } from 'react';
import { buildWsUrl, getJobLog } from '../api/client';
import { copyTerminalText, downloadTerminalText } from '../utils/terminal';
import type { Job, Worker } from '../types';
import { fmtDuration, getJobBadge } from '../utils';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Button } from './ui/button';

interface Props {
  jobId: string | null;
  queue: Job[];
  workers: Worker[];
  onClose: () => void;
  onRetry: (ids: string[]) => void;
  onEdit?: (target: string) => void;
  stacked?: boolean;
}

export function LogModal({ jobId, queue, workers, onClose, onRetry, onEdit, stacked }: Props) {
  const isOpen = jobId !== null;
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerMounted, setContainerMounted] = useState(false);
  const containerCallbackRef = useCallback((node: HTMLDivElement | null) => {
    containerRef.current = node;
    setContainerMounted(!!node);
  }, []);
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

  // Initialize terminal and connections when jobId changes or container mounts
  useEffect(() => {
    mountedRef.current = true;
    if (!jobId || !containerMounted || !containerRef.current) return;

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
    // We deliberately don't re-run when queue changes — only when jobId/container changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, containerMounted, startPolling]);

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

    if (!job.validate_only && ['failed', 'timed_out', 'success'].includes(job.state)) {
      retryEl = (
        <Button
          variant="warn"
          size="sm"
          onClick={() => { onRetry([job.id]); onClose(); }}
        >
          Retry
        </Button>
      );
    }
  }

  const handleCopy = () => copyTerminalText(termRef.current);
  const handleDownload = () => downloadTerminalText(termRef.current, job?.target ?? 'log');

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className={`dialog-lg${stacked ? ' stacked' : ''}`} style={stacked ? { zIndex: 500 } : undefined}>
        <DialogHeader>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 0 }}>
            <DialogTitle style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{modalTitle}</DialogTitle>
            {badgeEl}
            {metaEl}
            {retryEl}
          </div>
          {onEdit && job && !job.validate_only && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => { onEdit(job.target); onClose(); }}
              title="Open config in editor"
            >
              Edit
            </Button>
          )}
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
