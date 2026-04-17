import * as yaml from 'js-yaml';
import { getEsphomeSchema } from '../../api/client';

/**
 * YAML syntax + schema validation for the Monaco editor (QS.22).
 *
 * Extracted from EditorModal.tsx. Keeps all Monaco-marker + ESPHome-schema
 * concerns together so the React component can focus on dialog state + user
 * interactions.
 *
 * Module-level state:
 *   - `_componentList` / `_componentListPromise` — fetched-once cache of the
 *     server's /ui/api/esphome-schema component names. Used for schema
 *     warnings (unknown top-level keys).
 *   - `_validationTimer` — debounce handle so typing doesn't re-run YAML
 *     parsing on every keystroke.
 */

// ESPHome uses custom YAML tags that standard parsers reject. Register them
// so js-yaml can parse ESPHome configs without throwing on !include, !secret,
// etc.
const ESPHOME_SCHEMA = yaml.DEFAULT_SCHEMA.extend([
  new yaml.Type('!include', { kind: 'scalar', construct: (data) => data }),
  new yaml.Type('!secret', { kind: 'scalar', construct: (data) => data }),
  new yaml.Type('!lambda', { kind: 'scalar', construct: (data) => data }),
  new yaml.Type('!extend', { kind: 'mapping', construct: (data) => data }),
  new yaml.Type('!remove', { kind: 'scalar', construct: () => null }),
]);

let _componentList: string[] = [];
let _componentListPromise: Promise<string[]> | null = null;
let _validationTimer: ReturnType<typeof setTimeout> | null = null;

export function loadComponentList(): Promise<string[]> {
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

/**
 * Parse the YAML; return Monaco markers for any syntax errors. Uses an
 * ESPHome-aware schema so custom tags don't themselves cause parse errors.
 */
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

/**
 * Build Monaco markers: YAML syntax errors (errors) plus unknown top-level
 * keys (warnings, only when no syntax errors and component list is loaded).
 */
export function validateYaml(
  model: import('monaco-editor').editor.ITextModel,
  monaco: typeof import('monaco-editor'),
): void {
  const syntaxMarkers = collectSyntaxMarkers(model, monaco);
  if (syntaxMarkers.length > 0) {
    monaco.editor.setModelMarkers(model, 'esphome', syntaxMarkers);
    return;
  }

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

/** Debounced wrapper around `validateYaml` so typing doesn't parse on every keystroke. */
export function validateYamlDebounced(
  model: import('monaco-editor').editor.ITextModel,
  monaco: typeof import('monaco-editor'),
  delayMs = 500,
): void {
  if (_validationTimer !== null) clearTimeout(_validationTimer);
  _validationTimer = setTimeout(() => {
    validateYaml(model, monaco);
  }, delayMs);
}
