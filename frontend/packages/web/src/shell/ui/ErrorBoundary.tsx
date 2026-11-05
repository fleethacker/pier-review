import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface Props {
  /** Name shown in the fallback, e.g. the panel title. */
  name: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Keeps one broken panel from blanking the whole app: it shows a short message with a Try again button, and the rest of
 * the screen keeps working. The error is still logged to the console for debugging.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`Panel "${this.props.name}" failed:`, error, info.componentStack);
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="rounded-sm border border-mil-red/40 bg-mil-red/10 p-3 text-[11px] text-mil-red">
        <p>The “{this.props.name}” panel hit a problem and was stopped. The rest of the app still works.</p>
        <p className="mt-1 text-mil-dim">{this.state.error.message.slice(0, 160)}</p>
        <button className="mt-2 rounded-sm border border-mil-border px-2 py-1 font-mono text-[10px] uppercase text-mil-text hover:text-white" onClick={() => this.setState({ error: null })}>
          Try again
        </button>
      </div>
    );
  }
}
