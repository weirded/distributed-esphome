import Editor from '@monaco-editor/react';
import { Copy, Download, AlertCircle, KeyRound } from 'lucide-react';
import { useEffect, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Button } from './ui/button';
import { getRenderedConfig } from '../api/client';
import { stripYaml } from '../utils';

/**
 * RC.1 — read-only modal showing the YAML *as ESPHome will compile it*
 * for the chosen target.
 *
 * Today users diagnosing "why doesn't this substitution land?" / "is
 * the package field actually applied?" / "what did `!secret` resolve
 * to in this build?" have to shell into the add-on and run
 * `esphome config <yaml>` by hand. This modal lifts that diagnostic
 * into a one-click flow.
 *
 * Important: the rendered output resolves ``!secret`` references to
 * their plaintext values — the header carries a warning so the user
 * knows what they're about to copy. The modal never persists the
 * output beyond its own lifetime.
 */

interface Props {
  /** Target filename, e.g. ``cyd-office-info.yaml``. ``null`` = closed. */
  target: string | null;
  /** Friendly label for the title bar (falls back to the stripped filename). */
  displayName?: string | null;
  onClose: () => void;
  monacoTheme?: string;
}

export function RenderedConfigModal({ target, displayName, onClose, monacoTheme = 'vs-dark' }: Props) {
  const isOpen = target !== null;
  const [output, setOutput] = useState('');
  const [success, setSuccess] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!target) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getRenderedConfig(target)
      .then(r => {
        if (cancelled) return;
        setOutput(r.output);
        setSuccess(r.success);
        setLoading(false);
      })
      .catch(err => {
        if (cancelled) return;
        setError((err as Error).message);
        setOutput('');
        setSuccess(false);
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [target]);

  async function handleCopy() {
    if (!output) return;
    try {
      await navigator.clipboard.writeText(output);
    } catch {
      // Older browsers without async clipboard — fall through silently;
      // the user can still select-all in the editor.
    }
  }

  function handleDownload() {
    if (!output || !target) return;
    const blob = new Blob([output], { type: 'text/yaml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${stripYaml(target)}.rendered.yaml`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  const title = displayName || (target ? stripYaml(target) : 'Rendered config');

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="dialog-lg">
        <DialogHeader>
          <DialogTitle style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            Rendered config — {title}
          </DialogTitle>
        </DialogHeader>
        {/* Secret-warning subhead: always shown so the user sees it
            before they copy. The modal can't know whether the YAML
            uses !secret references at all without parsing the
            output, so the safer move is to flag it unconditionally. */}
        <div className="px-4 pt-2 pb-1 flex items-start gap-2 text-[12px] text-[var(--text-muted)]">
          <KeyRound className="size-4 shrink-0 mt-0.5 text-[var(--accent)]" />
          <span>
            This view contains the values of any{' '}
            <code className="bg-[var(--surface)] px-1 rounded">!secret</code>{' '}
            references — copy with care.
          </span>
        </div>

        <div className="px-4 pb-2 flex-1 min-h-0" style={{ minHeight: 400 }}>
          {loading && (
            <div className="text-[12px] text-[var(--text-muted)]">Rendering…</div>
          )}
          {!loading && error && (
            <div className="rounded-lg border border-[#fb923c] bg-[#3f1d1d] px-3 py-2 text-[12px] text-[#fb923c] flex items-start gap-2">
              <AlertCircle className="size-4 shrink-0 mt-0.5" />
              <div>
                <strong>Couldn't render this config.</strong>
                <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px]">{error}</pre>
              </div>
            </div>
          )}
          {!loading && !error && !success && (
            // Mirror the validate panel's failure shape: red banner +
            // raw stderr in a monospace block so the user sees exactly
            // what `esphome config` complained about.
            <div className="rounded-lg border border-[#fb923c] bg-[#3f1d1d] px-3 py-2 text-[12px] text-[#fb923c] mb-2 flex items-start gap-2">
              <AlertCircle className="size-4 shrink-0 mt-0.5" />
              <div>
                <strong>esphome config reported an error.</strong>
                <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px] max-h-[300px] overflow-auto">{output}</pre>
              </div>
            </div>
          )}
          {!loading && !error && success && (
            <Editor
              height="60vh"
              defaultLanguage="yaml"
              value={output}
              theme={monacoTheme}
              options={{
                readOnly: true,
                domReadOnly: true,
                minimap: { enabled: false },
                lineNumbers: 'on',
                wordWrap: 'on',
                scrollBeyondLastLine: false,
                renderWhitespace: 'none',
                folding: true,
                fontSize: 12,
              }}
            />
          )}
        </div>

        <DialogFooter>
          <Button
            variant="secondary"
            size="sm"
            onClick={handleCopy}
            disabled={!output || loading || !success}
          >
            <Copy className="size-3.5 mr-1" />
            Copy
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={handleDownload}
            disabled={!output || loading || !success}
          >
            <Download className="size-3.5 mr-1" />
            Download .yaml
          </Button>
          <Button size="sm" onClick={onClose}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
