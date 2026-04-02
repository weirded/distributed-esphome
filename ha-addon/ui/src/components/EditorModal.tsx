import Editor, { type OnMount } from '@monaco-editor/react';
import * as yaml from 'js-yaml';
import { useEffect, useRef, useState } from 'react';
import { getEsphomeSchema, getSecretKeys, getTargetContent, saveTargetContent } from '../api/client';
import type { ToastType } from './Toast';

// ESPHome uses custom YAML tags that standard parsers reject. Register them so
// js-yaml can parse ESPHome configs without throwing on !include, !secret, etc.
const ESPHOME_SCHEMA = yaml.DEFAULT_SCHEMA.extend([
  new yaml.Type('!include', { kind: 'scalar', construct: (data) => data }),
  new yaml.Type('!secret', { kind: 'scalar', construct: (data) => data }),
  new yaml.Type('!lambda', { kind: 'scalar', construct: (data) => data }),
  new yaml.Type('!extend', { kind: 'mapping', construct: (data) => data }),
  new yaml.Type('!remove', { kind: 'scalar', construct: () => null }),
]);

// Common sub-keys offered as a last-resort fallback when no component schema
// is available (e.g. custom components not in schema.esphome.io).
const COMMON_SUB_KEYS = [
  'platform', 'name', 'id', 'pin', 'internal', 'disabled_by_default',
  'on_value', 'on_state', 'filters', 'update_interval', 'unit_of_measurement',
  'device_class', 'state_class', 'accuracy_decimals', 'icon', 'address',
  'sda', 'scl', 'frequency', 'rx_pin', 'tx_pin', 'baud_rate',
];

// ---- Per-component schema fetching from schema.esphome.io ----

// Module-level cache: key is "<version>/<component>", value is raw JSON response.
const _schemaCache: Record<string, unknown> = {};

async function fetchComponentSchema(component: string, esphomeVersion: string): Promise<unknown> {
  const key = `${esphomeVersion}/${component}`;
  if (_schemaCache[key] !== undefined) return _schemaCache[key];

  // Try version-specific first, fall back to 'dev' which always exists.
  for (const ver of [esphomeVersion, 'dev']) {
    try {
      const r = await fetch(`https://schema.esphome.io/${ver}/${component}.json`);
      if (r.ok) {
        const data: unknown = await r.json();
        _schemaCache[key] = data;
        return data;
      }
    } catch {
      // Network error — try next version or give up.
    }
  }

  // Cache negative result so we don't retry on every keystroke.
  _schemaCache[key] = null;
  return null;
}

interface ConfigVar {
  name: string;
  docs?: string;
  required?: boolean;
}

function getConfigVars(schemaData: unknown, componentName: string): ConfigVar[] {
  if (!schemaData || typeof schemaData !== 'object') return [];

  const comp = (schemaData as Record<string, unknown>)[componentName];
  if (!comp || typeof comp !== 'object') return [];

  const schemas = (comp as Record<string, unknown>).schemas;
  if (!schemas || typeof schemas !== 'object') return [];

  const configSchema = (schemas as Record<string, unknown>).CONFIG_SCHEMA;
  if (!configSchema || typeof configSchema !== 'object') return [];

  const schema = (configSchema as Record<string, unknown>).schema;
  if (!schema || typeof schema !== 'object') return [];

  const configVars = (schema as Record<string, unknown>).config_vars;
  if (!configVars || typeof configVars !== 'object') return [];

  return Object.entries(configVars as Record<string, unknown>).map(([name, info]) => ({
    name,
    docs: (info && typeof info === 'object' && typeof (info as Record<string, unknown>).docs === 'string')
      ? (info as Record<string, string>).docs
      : '',
    required: (info && typeof info === 'object')
      ? (info as Record<string, unknown>).key === 'Required'
      : false,
  }));
}

// Walk up from the current line to find the nearest indent-0 YAML key, which
// is the top-level component name the cursor is nested under.
function findParentComponent(
  model: import('monaco-editor').editor.ITextModel,
  lineNumber: number,
): string | null {
  for (let i = lineNumber; i >= 1; i--) {
    const line = model.getLineContent(i);
    const trimmed = line.trimStart();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const indent = line.length - trimmed.length;
    if (indent === 0) {
      const colonIdx = trimmed.indexOf(':');
      const key = colonIdx >= 0 ? trimmed.slice(0, colonIdx).trim() : trimmed.trim();
      return key || null;
    }
  }
  return null;
}

interface Props {
  target: string | null;
  onClose: () => void;
  onToast: (msg: string, type?: ToastType) => void;
  onValidate?: (target: string) => void;
  onCompile?: (target: string) => void;
  monacoTheme?: string;
  esphomeVersion?: string | null;
}

// Module-level variable that holds the ESPHome version currently in use.
// Set each time the editor mounts so the async completion provider can read it
// without needing a closure that captures a stale prop value.
let _currentEsphomeVersion = 'dev';

// Module-level component list cache — fetched once per page load from the
// server's /ui/api/esphome-schema endpoint which reflects the actual installed
// ESPHome package rather than a hardcoded subset.
let _componentList: string[] = [];
let _componentListPromise: Promise<string[]> | null = null;

function loadComponentList(): Promise<string[]> {
  if (_componentList.length > 0) return Promise.resolve(_componentList);
  if (_componentListPromise) return _componentListPromise;
  _componentListPromise = getEsphomeSchema()
    .then(components => {
      _componentList = components;
      return components;
    })
    .catch(() => []);
  return _componentListPromise;
}

// Collect YAML syntax error markers by actually parsing the content.
// Uses an ESPHome-aware schema so custom tags (!include, !secret, !lambda,
// !extend, !remove) don't themselves cause parse errors.
function collectSyntaxMarkers(
  model: import('monaco-editor').editor.ITextModel,
  monaco: typeof import('monaco-editor'),
): import('monaco-editor').editor.IMarkerData[] {
  const markers: import('monaco-editor').editor.IMarkerData[] = [];
  try {
    yaml.loadAll(model.getValue(), undefined, { schema: ESPHOME_SCHEMA });
  } catch (e: unknown) {
    const err = e as { mark?: { line?: number; column?: number }; reason?: string; message?: string };
    if (err.mark) {
      const line = (err.mark.line ?? 0) + 1;
      const col = (err.mark.column ?? 0) + 1;
      markers.push({
        severity: monaco.MarkerSeverity.Error,
        message: err.reason || err.message || 'YAML syntax error',
        startLineNumber: line,
        startColumn: col,
        endLineNumber: line,
        endColumn: model.getLineLength(line) + 1,
      });
    }
  }
  return markers;
}

// Build Monaco markers: YAML syntax errors (errors) plus unknown top-level
// keys (warnings, only when no syntax errors and component list is loaded).
function validateYaml(
  model: import('monaco-editor').editor.ITextModel,
  monaco: typeof import('monaco-editor'),
): void {
  // Always check syntax first — if parsing fails, skip schema warnings since
  // the document isn't even well-formed.
  const syntaxMarkers = collectSyntaxMarkers(model, monaco);
  if (syntaxMarkers.length > 0) {
    monaco.editor.setModelMarkers(model, 'esphome', syntaxMarkers);
    return;
  }

  // If the component list hasn't loaded yet, only report syntax errors.
  if (_componentList.length === 0) {
    monaco.editor.setModelMarkers(model, 'esphome', []);
    return;
  }

  const componentSet = new Set(_componentList);
  const schemaMarkers: import('monaco-editor').editor.IMarkerData[] = [];
  const content = model.getValue();
  const lines = content.split('\n');

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
    if (key && !componentSet.has(key)) {
      schemaMarkers.push({
        severity: monaco.MarkerSeverity.Warning,
        message: `Unknown component: "${key}"`,
        startLineNumber: i + 1,
        startColumn: 1,
        endLineNumber: i + 1,
        endColumn: key.length + 1,
      });
    }
  }

  monaco.editor.setModelMarkers(model, 'esphome', schemaMarkers);
}

// Determine the indent level of the current cursor line, ignoring blank lines.
function currentLineIndent(
  model: import('monaco-editor').editor.ITextModel,
  position: import('monaco-editor').Position,
): number {
  const lineText = model.getLineContent(position.lineNumber);
  const trimmed = lineText.trimStart();
  if (!trimmed) return Infinity; // blank line — treat as unknown
  return lineText.length - trimmed.length;
}

// Guard: only register the completion provider and validation once per page load.
let _completionRegistered = false;

// Debounce timer handle for validation
let _validationTimer: ReturnType<typeof setTimeout> | null = null;

export function EditorModal({ target, onClose, onToast, onValidate, onCompile, monacoTheme = 'vs-dark', esphomeVersion }: Props) {
  const isOpen = target !== null;
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);

  // Keep the module-level version variable in sync so the completion provider
  // (registered once, outside the component lifecycle) always sees the current value.
  useEffect(() => {
    if (esphomeVersion) _currentEsphomeVersion = esphomeVersion;
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
      // Fire on space (for "!secret <cursor>") and colon (sub-key context).
      triggerCharacters: [' ', ':'],

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

        // Ensure the component list is loaded before offering completions.
        const components = await loadComponentList();

        const indent = currentLineIndent(model, position);

        // 2. Top-level (indent 0): suggest all ESPHome component names.
        if (indent === 0) {
          return {
            suggestions: components.map(name => ({
              label: name,
              kind: monaco.languages.CompletionItemKind.Module,
              insertText: name + ':\n  ',
              documentation: `ESPHome component: ${name}`,
              range,
            })),
          };
        }

        // 3. Indented context: fetch per-component schema from schema.esphome.io
        //    and suggest its config_vars. Fall back to COMMON_SUB_KEYS if the
        //    schema is unavailable (custom components, network error, etc.).
        const parent = findParentComponent(model, position.lineNumber);
        if (parent) {
          try {
            const schemaData = await fetchComponentSchema(parent, _currentEsphomeVersion);
            const vars = getConfigVars(schemaData, parent);
            if (vars.length > 0) {
              return {
                suggestions: vars.map(v => ({
                  label: v.name,
                  kind: v.required
                    ? monaco.languages.CompletionItemKind.Field
                    : monaco.languages.CompletionItemKind.Property,
                  insertText: v.name + ': ',
                  documentation: v.docs,
                  // Required keys sort first; within each group, alphabetical.
                  sortText: (v.required ? '0' : '1') + v.name,
                  range,
                })),
              };
            }
          } catch {
            // Schema fetch failed — fall through to generic keys below.
          }
        }

        return {
          suggestions: COMMON_SUB_KEYS.map(k => ({
            label: k,
            kind: monaco.languages.CompletionItemKind.Property,
            insertText: k + ': ',
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
        if (!model) return;
        validateYaml(model, monaco);
      }, 500);
    });

    // Run an initial validation pass; re-run once the component list arrives
    // so unknown-component warnings appear without requiring a keystroke.
    const model = editor.getModel();
    if (model) validateYaml(model, monaco);
    loadComponentList().then(() => {
      const m = editor.getModel();
      if (m) validateYaml(m, monaco);
    }).catch(() => null);
  }

  async function handleSave() {
    if (!editorRef.current || !target) return;
    const value = editorRef.current.getValue();
    try {
      await saveTargetContent(target, value);
      onToast('Saved ' + target, 'success');
      onClose();
    } catch (err) {
      onToast('Save failed: ' + (err as Error).message, 'error');
    }
  }

  async function handleSaveAndUpgrade() {
    if (!editorRef.current || !target) return;
    const value = editorRef.current.getValue();
    try {
      await saveTargetContent(target, value);
      onToast('Saved ' + target, 'success');
      onCompile?.(target);
      onClose();
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
          {onCompile && target && target !== 'secrets.yaml' && (
            <button
              className="btn-success btn-sm"
              onClick={handleSaveAndUpgrade}
              title="Save and trigger firmware compile + OTA"
            >
              Save &amp; Upgrade
            </button>
          )}
          {onValidate && target && target !== 'secrets.yaml' && (
            <button
              className="btn-secondary btn-sm"
              onClick={() => onValidate(target)}
              title="Validate config via esphome config (2-5s)"
            >
              Validate
            </button>
          )}
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
                quickSuggestions: { other: true, strings: true, comments: false },
                suggestOnTriggerCharacters: true,
                wordBasedSuggestions: 'off',
                acceptSuggestionOnCommitCharacter: true,
              }}
              onMount={handleEditorDidMount}
            />
          )}
        </div>
      </div>
    </div>
  );
}
