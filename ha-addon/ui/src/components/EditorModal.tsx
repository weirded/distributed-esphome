import Editor, { type OnMount } from '@monaco-editor/react';
import { Check, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { getTargetContent, saveTargetContent } from '../api/client';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Button } from './ui/button';
// QS.22: Monaco glue (completion provider, YAML validation, initial pass)
// lives in ./editor/. EditorModal stays a thin dialog + state wrapper.
import { loadComponentList, setEsphomeVersion, setupEsphomeEditor } from './editor/monacoSetup';

type ToastType = 'info' | 'success' | 'error';

interface Props {
  target: string | null;
  onClose: () => void;
  /** #42: called right before onClose when the editor closes via a successful
   *  save (Save or Save & Upgrade). Parent uses this to distinguish a
   *  saved-close from a cancel/dismiss-close — cancelling out of a newly
   *  created device with no save should clean up the leftover file. */
  onSaved?: (target: string) => void;
  onToast: (msg: string, type?: ToastType) => void;
  onValidate?: (target: string) => Promise<{ success: boolean; output: string } | null>;
  onCompile?: (target: string) => void;
  monacoTheme?: string;
  esphomeVersion?: string | null;
}

// Track dirty-line decorations (module-level so the callback closure can access it)
let _dirtyDecorationIds: string[] = [];

export function EditorModal({ target, onClose, onSaved, onToast, onValidate, onCompile, monacoTheme = 'vs-dark', esphomeVersion }: Props) {
  const isOpen = target !== null;
  const [content, setContent] = useState('');
  const [, setLoading] = useState(false);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const monacoRef = useRef<Parameters<OnMount>[1] | null>(null);
  const savedContentRef = useRef('');
  const [dirtyLineCount, setDirtyLineCount] = useState(0);
  const [showCloseConfirm, setShowCloseConfirm] = useState(false);
  // #26: validation output shown inline below the editor.
  const [validateResult, setValidateResult] = useState<{ success: boolean; output: string } | null>(null);
  const [validating, setValidating] = useState(false);

  // Keep the completion provider's module-level version variable in sync so
  // it always sees the current value despite being registered once outside
  // the component lifecycle.
  useEffect(() => {
    if (esphomeVersion) setEsphomeVersion(esphomeVersion);
  }, [esphomeVersion]);

  // Keep stable refs to callbacks so the fetch effect depends only on [target],
  // not on new function references from each parent re-render (which would
  // re-fetch on every poll cycle and wipe local edits).
  const onCloseRef = useRef(onClose);
  const onToastRef = useRef(onToast);
  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);
  useEffect(() => { onToastRef.current = onToast; }, [onToast]);

  // Load content when target changes — intentionally [target] only so that
  // background polls refreshing the parent do NOT overwrite unsaved edits.
  useEffect(() => {
    if (!target) return;
    setLoading(true);
    getTargetContent(target)
      .then(c => {
        setContent(c);
        savedContentRef.current = c;
        setLoading(false);
      })
      .catch(err => {
        onToastRef.current('Failed to load file: ' + (err as Error).message, 'error');
        setLoading(false);
        onCloseRef.current();
      });

    // Pre-fetch the component list as soon as the editor opens so completions
    // are available without waiting for the first keypress.
    loadComponentList().catch(() => null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  async function updateDirtyDecorations(editor: Parameters<OnMount>[0]) {
    const model = editor.getModel();
    if (!model || !monacoRef.current) return;
    const monaco = monacoRef.current;

    const currentValue = model.getValue();
    const savedValue = savedContentRef.current;

    if (currentValue === savedValue) {
      _dirtyDecorationIds = editor.deltaDecorations(_dirtyDecorationIds, []);
      setDirtyLineCount(0);
      return;
    }

    // Use Monaco's built-in diff computation via the editor worker service.
    // Create a temporary model for the saved content so Monaco can diff them.
    const savedModel = monaco.editor.createModel(savedValue, 'yaml');
    try {
      let changes: { modifiedStartLineNumber: number; modifiedEndLineNumber: number }[] = [];
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const editorWorker = (monaco.editor as any) /* ALLOW_ANY: monaco internal */.getEditorWorkerService?.();
      if (editorWorker?.computeDiff) {
        const diff = await editorWorker.computeDiff(savedModel.uri, model.uri, false, 100000);
        changes = (diff?.changes ?? []).map((c: { modified: { startLineNumber: number; endLineNumberExclusive: number } }) => ({
          modifiedStartLineNumber: c.modified.startLineNumber,
          modifiedEndLineNumber: c.modified.endLineNumberExclusive - 1,
        }));
      }

      // Fallback: common prefix/suffix approach if worker API unavailable
      if (changes.length === 0 && currentValue !== savedValue) {
        const origLines = savedValue.split('\n');
        const modLines = currentValue.split('\n');
        let prefixLen = 0;
        while (prefixLen < origLines.length && prefixLen < modLines.length && origLines[prefixLen] === modLines[prefixLen]) prefixLen++;
        let suffixLen = 0;
        while (suffixLen < origLines.length - prefixLen && suffixLen < modLines.length - prefixLen && origLines[origLines.length - 1 - suffixLen] === modLines[modLines.length - 1 - suffixLen]) suffixLen++;
        if (prefixLen < modLines.length - suffixLen) {
          changes = [{ modifiedStartLineNumber: prefixLen + 1, modifiedEndLineNumber: modLines.length - suffixLen }];
        }
      }

      const decorations: import('monaco-editor').editor.IModelDeltaDecoration[] = [];
      for (const change of changes) {
        for (let line = change.modifiedStartLineNumber; line <= change.modifiedEndLineNumber; line++) {
          decorations.push({
            range: { startLineNumber: line, startColumn: 1, endLineNumber: line, endColumn: 1 },
            options: { isWholeLine: true, className: 'dirty-line', glyphMarginClassName: 'dirty-glyph' },
          });
        }
      }
      _dirtyDecorationIds = editor.deltaDecorations(_dirtyDecorationIds, decorations);
      setDirtyLineCount(decorations.length);
    } finally {
      savedModel.dispose();
    }
  }

  function handleEditorDidMount(
    editor: Parameters<OnMount>[0],
    monaco: Parameters<OnMount>[1],
  ) {
    editorRef.current = editor;
    monacoRef.current = monaco;
    _dirtyDecorationIds = [];

    // Completion + validation + initial pass are all handled in
    // ./editor/monacoSetup. We still need our own content-change listener
    // to update the dirty-line decorations on the left gutter.
    setupEsphomeEditor(editor, monaco);
    editor.onDidChangeModelContent(() => {
      updateDirtyDecorations(editor).catch(() => {});
    });
  }

  async function handleSave() {
    if (!editorRef.current || !target) return;
    const value = editorRef.current.getValue();
    try {
      const { renamedTo } = await saveTargetContent(target, value);
      const finalTarget = renamedTo ?? target;
      savedContentRef.current = value;
      if (editorRef.current) updateDirtyDecorations(editorRef.current).catch(() => {});
      onToast('Saved ' + finalTarget, 'success');
      onSaved?.(target);
      onClose();
    } catch (err) {
      onToast('Save failed: ' + (err as Error).message, 'error');
    }
  }

  async function handleSaveAndUpgrade() {
    if (!editorRef.current || !target) return;
    const value = editorRef.current.getValue();
    try {
      const { renamedTo } = await saveTargetContent(target, value);
      const finalTarget = renamedTo ?? target;
      savedContentRef.current = value;
      onToast('Saved ' + finalTarget, 'success');
      onSaved?.(target);
      onCompile?.(finalTarget);
      onClose();
    } catch (err) {
      onToast('Save failed: ' + (err as Error).message, 'error');
    }
  }

  if (!isOpen) return null;

  return (
    <Dialog open onOpenChange={(open) => {
      if (!open) {
        if (dirtyLineCount > 0) { setShowCloseConfirm(true); return; }
        onClose();
      }
    }}>
      <DialogContent className="dialog-xl" style={{ background: monacoTheme === 'vs' ? '#ffffff' : '#1e1e1e', border: monacoTheme === 'vs' ? '1px solid var(--border)' : '1px solid #3c3c3c' }}>
        <div className="editor-header">
          <h3>{(target || '').replace(/^\.pending\./, '')}</h3>
          <Button size="sm" onClick={handleSave}>Save</Button>
          {onCompile && target && target !== 'secrets.yaml' && (
            <Button
              variant="success"
              size="sm"
              onClick={handleSaveAndUpgrade}
              title="Save and trigger firmware compile + OTA"
            >
              Save &amp; Upgrade
            </Button>
          )}
          {onValidate && target && target !== 'secrets.yaml' && (
            <Button
              variant="secondary"
              size="sm"
              disabled={validating}
              onClick={async () => {
                if (!editorRef.current || !target) return;
                const value = editorRef.current.getValue();
                try {
                  await saveTargetContent(target, value);
                  savedContentRef.current = value;
                  updateDirtyDecorations(editorRef.current).catch(() => {});
                } catch (err) {
                  onToast('Save failed: ' + (err as Error).message, 'error');
                  return;
                }
                setValidating(true);
                setValidateResult(null);
                const result = await onValidate(target);
                setValidating(false);
                if (result) setValidateResult(result);
              }}
              title="Save and validate config via esphome config (2-5s)"
            >
              {validating ? 'Validating…' : 'Validate'}
            </Button>
          )}
        </div>
        <div className="monaco-container">
          <Editor
            height="100%"
            defaultLanguage="yaml"
            value={content}
            theme={monacoTheme}
            options={{
              fontSize: 13,
              lineNumbers: 'on',
              minimap: { enabled: false },
              wordWrap: 'on',
              scrollBeyondLastLine: false,
              automaticLayout: true,
              tabSize: 2,
              insertSpaces: true,
              quickSuggestions: { other: true, strings: true, comments: false },
              suggestOnTriggerCharacters: true,
              wordBasedSuggestions: 'off',
              acceptSuggestionOnCommitCharacter: true,
              hover: { enabled: true },
              glyphMargin: true,
            }}
            onMount={handleEditorDidMount}
          />
        </div>
        {/* #26: validation output panel — shows the raw esphome config output */}
        {validateResult && (
          <div
            className="border-t px-3 py-2 font-mono text-xs overflow-auto"
            style={{
              maxHeight: 180,
              background: validateResult.success ? 'var(--surface)' : 'rgba(239,68,68,0.08)',
              borderColor: validateResult.success ? 'var(--border)' : 'var(--destructive)',
              color: validateResult.success ? 'var(--success)' : 'var(--destructive)',
            }}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="inline-flex items-center gap-1 font-semibold text-[11px] uppercase tracking-wide">
                {validateResult.success
                  ? (<><Check className="size-3.5" aria-hidden="true" /> Validation passed</>)
                  : (<><X className="size-3.5" aria-hidden="true" /> Validation failed</>)}
              </span>
              <button
                className="text-[var(--text-muted)] text-[10px] cursor-pointer hover:text-[var(--text)]"
                onClick={() => setValidateResult(null)}
              >
                dismiss
              </button>
            </div>
            <pre className="whitespace-pre-wrap break-words m-0" style={{ color: 'var(--text)' }}>{validateResult.output}</pre>
          </div>
        )}
        {dirtyLineCount > 0 && !validateResult && (
          <div className="editor-footer">
            {dirtyLineCount} line{dirtyLineCount !== 1 ? 's' : ''} changed
          </div>
        )}
      </DialogContent>
      {showCloseConfirm && (
        <Dialog open onOpenChange={(open) => { if (!open) setShowCloseConfirm(false); }}>
          <DialogContent style={{ zIndex: 600 }}>
            <DialogHeader>
              <DialogTitle>Unsaved Changes</DialogTitle>
            </DialogHeader>
            <div style={{ padding: 16 }}>
              <p>You have {dirtyLineCount} unsaved line{dirtyLineCount !== 1 ? 's' : ''}. Close without saving?</p>
            </div>
            <DialogFooter>
              <Button variant="secondary" size="sm" onClick={() => setShowCloseConfirm(false)}>Cancel</Button>
              <Button variant="destructive" size="sm" onClick={() => { setShowCloseConfirm(false); onClose(); }}>Discard Changes</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </Dialog>
  );
}
