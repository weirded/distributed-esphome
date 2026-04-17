import { getSecretKeys } from '../../api/client';
import { fetchComponentSchema } from '../../api/esphomeSchema';
import { loadComponentList } from './yamlValidation';

/**
 * Monaco YAML completion provider for ESPHome configs (QS.22).
 *
 * Extracted from EditorModal.tsx. Suggests:
 *   - top-level component names at indent 0 (from the loaded component list)
 *   - config_vars from the parent component's schema at indent > 0
 *   - secret keys after `!secret`
 *   - a COMMON_SUB_KEYS fallback when no component schema is available
 *
 * Monaco registers completion providers globally, so the register function
 * gates on a module-level flag to prevent double-registration if the editor
 * re-mounts.
 */

// Common sub-keys offered as a last-resort fallback when no component schema
// is available (e.g. custom components not in schema.esphome.io).
const COMMON_SUB_KEYS = [
  'platform', 'name', 'id', 'pin', 'internal', 'disabled_by_default',
  'on_value', 'on_state', 'filters', 'update_interval', 'unit_of_measurement',
  'device_class', 'state_class', 'accuracy_decimals', 'icon', 'address',
  'sda', 'scl', 'frequency', 'rx_pin', 'tx_pin', 'baud_rate',
];

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

/** Walk up from the current line to find the nearest indent-0 YAML key. */
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

/** Indent level of the line at the cursor (Infinity for blank lines). */
function currentLineIndent(
  model: import('monaco-editor').editor.ITextModel,
  position: import('monaco-editor').Position,
): number {
  const lineText = model.getLineContent(position.lineNumber);
  const trimmed = lineText.trimStart();
  if (!trimmed) return Infinity;
  return lineText.length - trimmed.length;
}

// The completion provider reads the current ESPHome version at suggestion
// time. Since the provider is registered once globally and lives outside the
// component lifecycle, the component updates this via `setEsphomeVersion`
// whenever the `esphomeVersion` prop changes.
let _currentEsphomeVersion = 'dev';
let _completionRegistered = false;

export function setEsphomeVersion(version: string): void {
  _currentEsphomeVersion = version;
}

export function registerEsphomeCompletionProvider(monaco: typeof import('monaco-editor')): void {
  if (_completionRegistered) return;
  _completionRegistered = true;

  monaco.languages.registerCompletionItemProvider('yaml', {
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

      const components = await loadComponentList();
      const indent = currentLineIndent(model, position);

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
}
