"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";

// Root-level App Router error boundary -- catches any render error not
// already caught by a more specific nested error.tsx (app/repos/error.tsx,
// app/repos/[repoId]/error.tsx) or a panel-level <PanelErrorBoundary> (see
// components/error-boundary.tsx). Without this file at all, an unhandled
// render error anywhere crashed straight to Next's generic, unthemed error
// screen with no way back into the app.
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // eslint-disable-next-line no-console -- server-side error reporting
    // isn't wired up for the frontend; this is the one place a render error
    // is still visible at all, for local debugging.
    console.error(error);
  }, [error]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
      <div className="glass flex flex-col items-center gap-3 rounded-2xl border border-border/60 bg-white/70 px-8 py-10 shadow-xl dark:bg-zinc-900/60">
        <AlertTriangle className="h-8 w-8 text-destructive" aria-hidden="true" />
        <h1 className="text-2xl font-semibold text-foreground">Something went wrong</h1>
        <p className="max-w-sm text-sm text-muted-foreground">
          An unexpected error occurred while rendering this page. Your data is safe -- try again below.
        </p>
        <button
          type="button"
          onClick={reset}
          className="mt-2 inline-flex items-center gap-1 rounded-md bg-gradient-to-r from-primary to-indigo-500 px-4 py-2 text-sm font-medium text-primary-foreground shadow-md transition-transform hover:scale-[1.02]"
        >
          Try again
        </button>
      </div>
    </main>
  );
}
