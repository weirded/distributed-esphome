/**
 * SE.8 — Top-of-app banner for the server's ESPHome install lifecycle.
 *
 * Renders during the first-boot window where `ensure_esphome_installed`
 * is still running. Auto-hides once `esphome_install_status` transitions
 * to `"ready"`. On `"failed"`, shows a Retry button that POSTs to
 * `/ui/api/esphome/reinstall` — the server re-runs the install in the
 * background and the banner re-polls itself via SWR.
 *
 * Deliberately tiny: one div, one optional button, no animations.
 * The user's expected action is "wait a couple of minutes" — any more
 * UX would be overkill.
 */

import { useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import { reinstallEsphome } from '../api/client';
import type { ServerInfo } from '../types';

interface Props {
  serverInfo: ServerInfo | null;
  onRefresh: () => void;
}

export function EsphomeInstallBanner({ serverInfo, onRefresh }: Props) {
  const [retrying, setRetrying] = useState(false);
  const status = serverInfo?.esphome_install_status;
  const version = serverInfo?.esphome_server_version;

  if (!status || status === 'ready') return null;

  const handleRetry = async () => {
    setRetrying(true);
    try {
      await reinstallEsphome();
      onRefresh();
    } catch {
      // Swallow — server-info polling will eventually surface the
      // failed state again if it persists.
    } finally {
      setRetrying(false);
    }
  };

  const isFailed = status === 'failed';
  const bg = isFailed
    ? 'bg-[var(--destructive)]/10 border-[var(--destructive)] text-[var(--destructive)]'
    : 'bg-[var(--accent)]/10 border-[var(--accent)] text-[var(--accent)]';

  return (
    <div
      role="status"
      aria-live="polite"
      className={`flex items-center justify-between gap-3 border-b px-4 py-2 text-[13px] ${bg}`}
    >
      <div className="flex items-center gap-2">
        {isFailed ? (
          <AlertTriangle className="size-4 shrink-0" aria-hidden />
        ) : (
          <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
        )}
        <span>
          {isFailed
            ? `ESPHome ${version ?? ''} install failed — retry below or check the add-on log.`
            : `Installing ESPHome ${version ?? ''}… first-boot takes 1–3 minutes. Some features are unavailable until this finishes.`}
        </span>
      </div>
      {isFailed && (
        <button
          type="button"
          onClick={handleRetry}
          disabled={retrying}
          className="rounded-md border border-[var(--destructive)] bg-[var(--surface)] px-2 py-0.5 text-[12px] font-medium hover:bg-[var(--destructive)]/10 disabled:opacity-60"
        >
          {retrying ? 'Retrying…' : 'Retry'}
        </button>
      )}
    </div>
  );
}
