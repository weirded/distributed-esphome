import { useCallback, useEffect, useState } from 'react';
import { Activity, Check, Copy, Loader2, X } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogClose,
} from './ui/dialog';
import { Button } from './ui/button';
import { pingDevice, type PingResult } from '../api/client';
import { stripYaml } from '../utils';

interface Props {
  target: string;
  onClose: () => void;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
}

/**
 * DM.2: Per-device ICMP ping diagnostic.
 *
 * Resolves the recurring "is it offline, is it on a flaky AP, or is the
 * controller's mDNS stale?" triage step that today requires shelling
 * into the add-on. Hits ``POST /ui/api/targets/{filename}/ping`` which
 * runs ``icmplib.async_ping`` against the resolved OTA address (same
 * helper the upload path uses, so the ping target matches what an OTA
 * would hit).
 *
 * Worst-case wall time for an unreachable host is `(count-1)*interval +
 * timeout` ≈ 3.8 s — batch UX, no streaming.
 */
export default function PingDeviceModal({ target, onClose, onToast }: Props) {
  const [result, setResult] = useState<PingResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(true);
  const [address, setAddress] = useState<string | null>(null);

  const runPing = useCallback(async () => {
    setPending(true);
    setError(null);
    try {
      const r = await pingDevice(target);
      setResult(r);
      setAddress(r.address);
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg);
      setResult(null);
      // Try to parse the address out of the failure body so the modal can still
      // show "Pinged: <addr>" on a non-200 path. Best-effort; falls back to —.
      try {
        const m = msg.match(/"address":\s*"([^"]+)"/);
        if (m) setAddress(m[1]);
      } catch { /* swallow */ }
    } finally {
      setPending(false);
    }
  }, [target]);

  useEffect(() => {
    runPing();
  }, [runPing]);

  function copyAsText() {
    if (!result) return;
    const lines = [
      `Ping result for ${stripYaml(target)} (${result.address})`,
      `  is_alive:       ${result.is_alive ? 'YES' : 'NO'}`,
      `  packets_sent:   ${result.packets_sent}`,
      `  packets_recv:   ${result.packets_received}`,
      `  packet_loss:    ${(result.packet_loss * 100).toFixed(1)}%`,
      `  min_rtt:        ${result.min_rtt.toFixed(2)} ms`,
      `  avg_rtt:        ${result.avg_rtt.toFixed(2)} ms`,
      `  max_rtt:        ${result.max_rtt.toFixed(2)} ms`,
      `  jitter:         ${result.jitter.toFixed(2)} ms`,
    ];
    navigator.clipboard.writeText(lines.join('\n')).then(
      () => onToast('Ping result copied', 'success'),
      () => onToast('Could not copy to clipboard', 'error'),
    );
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Activity className="size-4" aria-hidden="true" />
            Ping {stripYaml(target)}
          </DialogTitle>
        </DialogHeader>
        <div className="px-4 py-3 flex flex-col gap-2 text-sm text-[var(--text)]">
          {pending && (
            <div className="flex items-center gap-2 text-[var(--text-muted)]">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              <span>Pinging {address || 'device'}… (~4 s)</span>
            </div>
          )}
          {!pending && error && (
            <div className="flex items-start gap-2 text-[var(--danger)]">
              <X className="size-4 shrink-0 mt-0.5" aria-hidden="true" />
              <div className="break-words">
                <div className="font-medium">Ping failed</div>
                <div className="text-[11px] mt-0.5">{error}</div>
              </div>
            </div>
          )}
          {!pending && result && (
            <>
              <div className="flex items-center gap-2">
                <span
                  className={`inline-block size-2.5 rounded-full ${result.is_alive ? 'bg-[var(--success)]' : 'bg-[var(--danger)]'}`}
                  aria-hidden="true"
                />
                <span className="font-medium">
                  {result.is_alive ? 'Reachable' : 'No response'}
                </span>
                <span className="text-[11px] text-[var(--text-muted)]">
                  via {result.address}
                </span>
              </div>
              <table className="text-[12px] w-full">
                <tbody>
                  <tr><td className="pr-3 py-0.5 text-[var(--text-muted)]">Packets sent</td><td className="tabular-nums">{result.packets_sent}</td></tr>
                  <tr><td className="pr-3 py-0.5 text-[var(--text-muted)]">Packets received</td><td className="tabular-nums">{result.packets_received}</td></tr>
                  <tr><td className="pr-3 py-0.5 text-[var(--text-muted)]">Packet loss</td><td className="tabular-nums">{(result.packet_loss * 100).toFixed(1)}%</td></tr>
                  <tr><td className="pr-3 py-0.5 text-[var(--text-muted)]">RTT min / avg / max</td>
                    <td className="tabular-nums">
                      {result.min_rtt.toFixed(2)} / {result.avg_rtt.toFixed(2)} / {result.max_rtt.toFixed(2)} ms
                    </td>
                  </tr>
                  <tr><td className="pr-3 py-0.5 text-[var(--text-muted)]">Jitter</td><td className="tabular-nums">{result.jitter.toFixed(2)} ms</td></tr>
                </tbody>
              </table>
            </>
          )}
        </div>
        <DialogFooter>
          <Button
            variant="secondary"
            size="sm"
            onClick={copyAsText}
            disabled={pending || !result}
          >
            <Copy className="size-3.5 mr-1" aria-hidden="true" />
            Copy as text
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={runPing}
            disabled={pending}
          >
            {pending ? (
              <Loader2 className="size-3.5 mr-1 animate-spin" aria-hidden="true" />
            ) : (
              <Check className="size-3.5 mr-1" aria-hidden="true" />
            )}
            {pending ? 'Pinging…' : 'Run again'}
          </Button>
          <DialogClose>
            <Button size="sm">Close</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
