import Editor, { type OnMount } from '@monaco-editor/react';
import { useEffect, useRef, useState } from 'react';
import { getSecretKeys, getTargetContent, saveTargetContent } from '../api/client';
import type { ToastType } from './Toast';

interface Props {
  target: string | null;
  onClose: () => void;
  onToast: (msg: string, type?: ToastType) => void;
  monacoTheme?: string;
}

// Fallback keyword list used when the schema fails to load
const YAML_KEYWORDS = [
  'esphome', 'name', 'friendly_name', 'comment', 'platform', 'board',
  'wifi', 'ssid', 'password', 'ap', 'logger', 'api', 'encryption', 'key',
  'ota', 'sensor', 'binary_sensor', 'switch', 'light', 'fan', 'climate',
  'cover', 'output', 'uart', 'i2c', 'spi', 'substitutions', 'packages',
  'esp32', 'esp8266', 'deep_sleep', 'interval', 'lambda', 'id', 'on_boot', 'on_shutdown',
];

// Module-level schema cache — kept in JS memory (not sessionStorage) because
// the schema is ~200KB+ and sessionStorage access is synchronous but
// JSON.parse of that size is slow on repeated opens.
let esphomeSchema: Record<string, unknown> | null = null;
let schemaLoadPromise: Promise<Record<string, unknown> | null> | null = null;

async function loadEsphomeSchema(): Promise<Record<string, unknown> | null> {
  if (esphomeSchema) return esphomeSchema;
  if (schemaLoadPromise) return schemaLoadPromise;
  schemaLoadPromise = fetch('https://json.esphome.io/esphome.json')
    .then(r => r.json())
    .then((schema: Record<string, unknown>) => {
      esphomeSchema = schema;
      return schema;
    })
    .catch(() => null);
  return schemaLoadPromise;
}

// Resolve a $ref string (e.g. "#/definitions/Foo") within the root schema.
function resolveRef(root: Record<string, unknown>, ref: string): Record<string, unknown> | null {
  if (!ref.startsWith('#/')) return null;
  const parts = ref.slice(2).split('/');
  let node: unknown = root;
  for (const part of parts) {
    if (node == null || typeof node !== 'object') return null;
    node = (node as Record<string, unknown>)[part];
  }
  return (node != null && typeof node === 'object') ? node as Record<string, unknown> : null;
}

// Walk down the schema following the YAML key path, resolving $refs along the way.
function resolveSchemaPath(
  root: Record<string, unknown>,
  path: string[],
): Record<string, unknown> | null {
  let current: Record<string, unknown> | null = root;
  for (const key of path) {
    if (!current) return null;
    // Resolve any top-level $ref on the current node
    while (current && current.$ref && typeof current.$ref === 'string') {
      current = resolveRef(root, current.$ref);
    }
    if (!current) return null;
    const props = current.properties as Record<string, unknown> | undefined;
    if (props && key in props) {
      const child = props[key];
      current = (child != null && typeof child === 'object')
        ? child as Record<string, unknown>
        : null;
    } else if (current.additionalProperties && typeof current.additionalProperties === 'object') {
      current = current.additionalProperties as Record<string, unknown>;
    } else {
      return null;
    }
  }
  // Resolve a final $ref on the landed node
  while (current && current.$ref && typeof current.$ref === 'string') {
    current = resolveRef(root, current.$ref);
  }
  return current;
}

// Determine the logical YAML key-path at a given cursor position by walking
// upward through the lines and tracking indentation levels.
function getYamlPath(
  model: import('monaco-editor').editor.ITextModel,
  position: import('monaco-editor').Position,
): string[] {
  const path: string[] = [];
  let currentIndent = Infinity;

  for (let lineNum = position.lineNumber; lineNum >= 1; lineNum--) {
    const lineText = model.getLineContent(lineNum);
    const trimmed = lineText.trimStart();
    if (!trimmed || trimmed.startsWith('#')) continue;

    const indent = lineText.length - trimmed.length;
    if (indent >= currentIndent) continue;

    // Skip list items — they don't contribute a named key to the path
    if (trimmed.startsWith('- ')) {
      currentIndent = indent;
      continue;
    }

    const colonIdx = trimmed.indexOf(':');
    if (colonIdx > 0) {
      const key = trimmed.slice(0, colonIdx).trim();
      if (key) {
        path.unshift(key);
        currentIndent = indent;
      }
    }

    if (currentIndent === 0) break;
  }

  // Remove the key being typed on the current line — we want the parent context
  path.pop();
  return path;
}

// Build Monaco markers for unknown top-level keys (only top-level to keep
// complexity manageable for a first validation pass).
function validateYaml(
  model: import('monaco-editor').editor.ITextModel,
  schema: Record<string, unknown>,
  monaco: typeof import('monaco-editor'),
): void {
  const markers: import('monaco-editor').editor.IMarkerData[] = [];
  const content = model.getValue();
  const lines = content.split('\n');
  const topProps = (schema.properties as Record<string, unknown> | undefined) ?? {};

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trimStart();
    if (!trimmed || trimmed.startsWith('#') || trimmed.startsWith('-')) continue;

    const indent = line.length - trimmed.length;
    if (indent !== 0) continue;

    // Skip lines where the value starts with a YAML custom tag — these are valid
    // ESPHome constructs (e.g. key: !secret foo, key: !include file.yaml)
    const colonIdx = trimmed.indexOf(':');
    if (colonIdx < 0) continue;
    const afterColon = trimmed.slice(colonIdx + 1).trim();
    if (afterColon.startsWith('!')) continue;

    const key = trimmed.slice(0, colonIdx).trim();
    if (key && !(key in topProps)) {
      markers.push({
        severity: monaco.MarkerSeverity.Warning,
        message: `Unknown component: "${key}"`,
        startLineNumber: i + 1,
        startColumn: 1,
        endLineNumber: i + 1,
        endColumn: key.length + 1,
      });
    }
  }

  monaco.editor.setModelMarkers(model, 'esphome', markers);
}

// Guard: only register the completion provider and validation once per page load.
let _completionRegistered = false;

// Debounce timer handle for validation
let _validationTimer: ReturnType<typeof setTimeout> | null = null;

export function EditorModal({ target, onClose, onToast, monacoTheme = 'vs-dark' }: Props) {
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

    // Start fetching the schema as soon as the editor opens so it's ready
    // by the time the user begins typing.
    loadEsphomeSchema().catch(() => null);
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

  function handleEditorDidMount(
    editor: Parameters<OnMount>[0],
    monaco: Parameters<OnMount>[1],
  ) {
    editorRef.current = editor;

    if (_completionRegistered) return;
    _completionRegistered = true;

    // --- Completion provider ---
    monaco.languages.registerCompletionItemProvider('yaml', {
      // triggerCharacters lets us fire on space after "!secret"
      triggerCharacters: [' '],

      async provideCompletionItems(
        model: import('monaco-editor').editor.ITextModel,
        position: import('monaco-editor').Position,
      ) {
        const word = model.getWordUntilPosition(position);
        const range = {
          startLineNumber: position.lineNumber,
          endLineNumber: position.lineNumber,
          startColumn: word.startColumn,
          endColumn: word.endColumn,
        };

        // 1. Detect "!secret <cursor>" — offer secret key names from the server
        const lineContent = model.getLineContent(position.lineNumber);
        const beforeCursor = lineContent.substring(0, position.column - 1);
        if (/!secret\s+\S*$/.test(beforeCursor) || beforeCursor.trimEnd().endsWith('!secret')) {
          try {
            const keys = await getSecretKeys();
            return {
              suggestions: keys.map(k => ({
                label: k,
                kind: monaco.languages.CompletionItemKind.Variable,
                insertText: k,
                documentation: 'Secret from secrets.yaml',
                range,
              })),
            };
          } catch {
            return { suggestions: [] };
          }
        }

        // 2. Schema-driven property completions
        const schema = esphomeSchema;
        if (schema) {
          const path = getYamlPath(model, position);
          const node = resolveSchemaPath(schema, path);
          const props = node?.properties as Record<string, unknown> | undefined;
          if (props) {
            return {
              suggestions: Object.entries(props).map(([key, prop]) => {
                const p = (prop != null && typeof prop === 'object')
                  ? prop as Record<string, unknown>
                  : {};
                return {
                  label: key,
                  kind: monaco.languages.CompletionItemKind.Property,
                  insertText: key + ': ',
                  documentation: typeof p.description === 'string' ? p.description : '',
                  range,
                };
              }),
            };
          }
        }

        // 3. Fallback: static keyword list
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

    // --- Inline validation on content change ---
    editor.onDidChangeModelContent(() => {
      if (_validationTimer !== null) clearTimeout(_validationTimer);
      _validationTimer = setTimeout(() => {
        const model = editor.getModel();
        if (!model || !esphomeSchema) return;
        validateYaml(model, esphomeSchema, monaco);
      }, 500);
    });

    // Run an initial validation pass once the schema is available
    loadEsphomeSchema().then(schema => {
      if (!schema) return;
      const model = editor.getModel();
      if (model) validateYaml(model, schema, monaco);
    }).catch(() => null);
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
              }}
              onMount={handleEditorDidMount}
            />
          )}
        </div>
      </div>
    </div>
  );
}
