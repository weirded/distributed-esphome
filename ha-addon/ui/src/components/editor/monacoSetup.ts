import type { OnMount } from '@monaco-editor/react';
import { registerEsphomeCompletionProvider, setEsphomeVersion } from './completionProvider';
import { loadComponentList, validateYaml, validateYamlDebounced } from './yamlValidation';

/**
 * Monaco editor setup orchestrator for ESPHome configs (QS.22).
 *
 * Wires up completion + validation + dirty-line tracking against a mounted
 * Monaco editor. Intended to be called once from EditorModal's `onMount`
 * callback; subsequent remounts short-circuit inside the individual
 * register functions.
 *
 * Returns an object of helpers the React component still wants to call
 * (e.g. to re-validate after a save or to trigger an initial pass).
 */
export function setupEsphomeEditor(
  editor: Parameters<OnMount>[0],
  monaco: Parameters<OnMount>[1],
): void {
  registerEsphomeCompletionProvider(monaco);

  // Re-validate on every content change (debounced).
  editor.onDidChangeModelContent(() => {
    const model = editor.getModel();
    if (!model) return;
    validateYamlDebounced(model, monaco, 500);
  });

  // Initial pass + re-validate once the component list arrives so unknown-
  // component warnings appear without waiting for a keypress.
  const model = editor.getModel();
  if (model) validateYaml(model, monaco);
  loadComponentList()
    .then(() => {
      const m = editor.getModel();
      if (m) validateYaml(m, monaco);
    })
    .catch(() => null);
}

export { setEsphomeVersion, loadComponentList, validateYaml };
