"use client";

import { Component, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

interface Props {
  /** Shown in the fallback -- e.g. "file tree", "code viewer", "AI chat". */
  label: string;
  children: ReactNode;
  /**
   * Called alongside this boundary's own reset when Retry is clicked -- lets
   * a parent that owns real fetch state (repoId, a selected path, etc.)
   * refetch/remount at the same time, since resetting `hasError` alone does
   * nothing if the same props that caused the error are still what's being
   * rendered. React batches this callback's state update together with the
   * boundary's own `setState` (both fire synchronously in the same click
   * handler), so the very next render already reflects both.
   */
  onReset?: () => void;
}

interface State {
  hasError: boolean;
}

// A React error boundary genuinely requires a class component -- there is
// no hooks-based equivalent to getDerivedStateFromError/componentDidCatch.
// Used to isolate one workspace panel (file tree, code viewer, AI chat)
// from the others: if one throws during render, the surrounding workspace
// shell (header, tabs, the other two panels) stays fully interactive
// instead of the whole workspace crashing to the nearest route-level
// error.tsx (see app/repos/[repoId]/error.tsx, which is the backstop for
// everything OUTSIDE these three panels).
export class PanelErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    // eslint-disable-next-line no-console
    console.error(`PanelErrorBoundary (${this.props.label}) caught:`, error);
  }

  private handleRetry = () => {
    this.setState({ hasError: false });
    this.props.onReset?.();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
          <AlertTriangle className="h-6 w-6 text-destructive" aria-hidden="true" />
          <p className="text-sm font-medium text-foreground">The {this.props.label} hit an error</p>
          <p className="max-w-xs text-xs text-muted-foreground">
            The rest of the workspace is unaffected -- try reloading just this panel.
          </p>
          <button
            type="button"
            onClick={this.handleRetry}
            className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-primary/40"
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
