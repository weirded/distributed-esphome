import Editor, { type OnMount } from '@monaco-editor/react';
import { useEffect, useRef, useState } from 'react';
import { getTargetContent, saveTargetContent } from '../api/client';
import type { ToastType } from './Toast';

interface Props {
  target: string | null;
  onClose: () => void;
  onToast: (msg: string, type?: ToastType) => void;
}

const YAML_KEYWORDS = [
  'esphome', 'name', 'friendly_name', 'comment', 'platform', 'board',
  'wifi', 'ssid', 'password', 'ap', 'logger', 'api', 'encryption', 'key',
  'ota', 'sensor', 'binary_sensor', 'switch', 'light', 'fan', 'climate',
  'cover', 'output', 'uart', 'i2c', 'spi', 'substitutions', 'packages',
  'esp32', 'esp8266', 'deep_sleep', 'interval', 'lambda', 'id', 'on_boot', 'on_shutdown',
];

let _completionRegistered = false;

export function EditorModal({ target, onClose, onToast }: Props) {
  const isOpen = target !== null;
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);

  // Load content when target changes
  useEffect(() => {
    if (!target) return;
    setLoading(true);
    getTargetContent(target)
      .then(c => {
        setContent(c);
        setLoading(false);
      })
      .catch(err => {
        onToast('Failed to load file: ' + (err as Error).message, 'error');
        setLoading(false);
        onClose();
      });
  }, [target, onClose, onToast]);

  // Keyboard handler
  useEffect(() => {
    if (!isOpen) return;
    function handler(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  function handleOverlayClick(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget) onClose();
  }

  function handleEditorDidMount(editor: Parameters<OnMount>[0], monaco: Parameters<OnMount>[1]) {
    editorRef.current = editor;

    if (!_completionRegistered) {
      _completionRegistered = true;
      monaco.languages.registerCompletionItemProvider('yaml', {
        provideCompletionItems(model: import('monaco-editor').editor.ITextModel, position: import('monaco-editor').Position) {
          const word = model.getWordUntilPosition(position);
          const range = {
            startLineNumber: position.lineNumber,
            endLineNumber: position.lineNumber,
            startColumn: word.startColumn,
            endColumn: word.endColumn,
          };
          return {
            suggestions: YAML_KEYWORDS.map(k => ({
              label: k,
              kind: monaco.languages.CompletionItemKind.Keyword,
              insertText: k,
              range,
            })),
          };
        },
      });
    }
  }

  async function handleSave() {
    if (!editorRef.current || !target) return;
    const value = editorRef.current.getValue();
    try {
      await saveTargetContent(target, value);
      onToast('Saved ' + target, 'success');
    } catch (err) {
      onToast('Save failed: ' + (err as Error).message, 'error');
    }
  }

  return (
    <div
      id="editor-modal"
      className={`editor-overlay${isOpen ? ' open' : ''}`}
      onClick={handleOverlayClick}
    >
      <div className="editor-modal">
        <div className="editor-header">
          <h3>{target || ''}</h3>
          <button className="btn-primary btn-sm" onClick={handleSave}>Save</button>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="monaco-container">
          {!loading && isOpen && (
            <Editor
              height="100%"
              defaultLanguage="yaml"
              value={content}
              theme="vs-dark"
              options={{
                fontSize: 13,
                lineNumbers: 'on',
                minimap: { enabled: false },
                wordWrap: 'on',
                scrollBeyondLastLine: false,
                automaticLayout: true,
                tabSize: 2,
                insertSpaces: true,
              }}
              onMount={handleEditorDidMount}
            />
          )}
        </div>
      </div>
    </div>
  );
}
