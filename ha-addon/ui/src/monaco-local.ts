/**
 * CF.1 — point @monaco-editor/react at the locally-bundled
 * ``monaco-editor`` package so we can drop ``cdn.jsdelivr.net`` from
 * the CSP and ship a self-contained UI.
 *
 * By default, ``@monaco-editor/react``'s loader fetches Monaco's
 * runtime + worker scripts from jsDelivr at first editor mount. That
 * forced the addon's CSP to allow ``https://cdn.jsdelivr.net`` across
 * script-src / style-src / font-src / connect-src — a long-standing
 * supply-chain wart, and a reliability hazard (the editor just breaks
 * when jsDelivr is down or blocked by the user's network).
 *
 * The fix: import ``monaco-editor`` normally (Vite bundles it into the
 * app's chunks), wire up ``self.MonacoEnvironment`` so Monaco spawns
 * its own Web Worker from that same bundle, and call
 * ``loader.config({ monaco })`` so ``@monaco-editor/react`` uses the
 * local module instead of fetching from CDN.
 *
 * YAML specifically doesn't ship a dedicated language worker — the
 * standard ``editor.worker`` handles its tokenisation — so one worker
 * constructor covers every label Monaco asks for.
 */

// Tree-shaken Monaco import: only the core editor + YAML tokenisation
// ship to the browser. The full ``monaco-editor`` barrel pulls in every
// basic language (TypeScript, JSON, Go, Solidity, Rust, Dockerfile…) —
// ~3.6 MB raw on disk — for zero benefit here since ESPHome configs are
// always YAML. ``editor.api`` is the one-file core entry; the YAML
// contribution side-effect import registers YAML with Monaco's language
// registry so ``defaultLanguage="yaml"`` works on the Editor component.
// Using the explicit ``.js`` extension bypasses monaco-editor's
// package.json exports map (which only exports ``.`` via its ``module``
// field, which in turn re-exports every bundled language). With the
// full path + .js extension, TS under ``moduleResolution: bundler``
// still finds the sibling ``.d.ts`` for types while Vite bundles just
// what's imported.
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api.js';
import 'monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution.js';
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import { loader } from '@monaco-editor/react';

// MonacoEnvironment must be set on `self` BEFORE Monaco is used.
// Vite's `?worker` import returns a Worker constructor that wraps the
// bundled worker script — same-origin, CSP-friendly, and no CDN fetch.
// Cast to unknown then the partial type Monaco expects to satisfy
// the "global augmentation" pattern without dragging in @types/monaco-*.
(self as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = {
  // Monaco passes a (_moduleId, label) pair — we return the same worker
  // for every label because YAML doesn't have a language-specific worker
  // and the basic editor worker covers tokenisation + diff / search.
  getWorker(_moduleId: string, _label: string): Worker {
    return new EditorWorker();
  },
};

loader.config({ monaco });
