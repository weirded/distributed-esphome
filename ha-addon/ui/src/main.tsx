import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// CF.1: wire @monaco-editor/react to the locally-bundled `monaco-editor`
// package BEFORE any editor component mounts. Must happen before
// importing App (which transitively imports the editor modal). Dropping
// this import reverts to the jsDelivr-CDN loader + reintroduces the
// CSP origin we're trying to remove.
import './monaco-local'
import App from './App.tsx'
import { ErrorBoundary } from './components/ErrorBoundary'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
