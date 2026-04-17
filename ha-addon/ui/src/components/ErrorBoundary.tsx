import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Button } from './ui/button';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * QS.26 — Top-level error boundary around <App />.
 *
 * Catches any uncaught render-tree throw and presents a minimal "something
 * went wrong" card with a reload button. Without this, a single
 * mis-typed cell renderer would blank the entire UI with no recovery path.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Forward to the console so the stack survives in browser devtools and
    // the HA add-on log capture; we deliberately don't ship to a remote
    // collector — this is a single-user home-lab tool.
    console.error('UI error boundary caught:', error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-[var(--bg)] p-6">
          <div className="max-w-lg rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 shadow-md">
            <h1 className="text-lg font-semibold text-[var(--text)]">Something went wrong</h1>
            <p className="mt-2 text-sm text-[var(--text-muted)]">
              The UI hit an uncaught error and can&apos;t continue. Reload to recover.
              The stack is in the browser console.
            </p>
            <pre className="mt-3 max-h-40 overflow-auto rounded bg-[var(--surface2)] p-2 text-[11px] text-[var(--text-muted)]">
              {this.state.error.message}
            </pre>
            <div className="mt-4 flex gap-2">
              <Button onClick={() => window.location.reload()}>Reload</Button>
              <Button variant="secondary" onClick={() => this.setState({ error: null })}>
                Dismiss
              </Button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
