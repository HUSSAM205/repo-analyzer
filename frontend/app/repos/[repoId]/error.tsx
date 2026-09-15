"use client";

import { useEffect } from "react";
import Link from "next/link";
import { AlertTriangle } from "lucide-react";

// Catches a render error anywhere in a specific repo's workspace (header,
// briefing, or the WorkspaceShell layout itself) -- narrower still than
// app/repos/error.tsx. A crash inside one of the three panels (file tree,
// code viewer, chat) is caught closer to the source by <PanelErrorBoundary>
// (see components/error-boundary.tsx) and never reaches this far up; this
// is the backstop for anything outside those three panels.
export default function RepoWorkspaceError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error(error);
  }, [error]);

  return (
    <main className="flex flex-col items-center gap-3 px-6 py-16 text-center">
      <AlertTriangle className="h-8 w-8 text-destructive" aria-hidden="true" />
      <h1 className="text-xl font-semibold text-foreground">This workspace hit an unexpected error</h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        The analyzed repository data is safe -- this was a rendering error. Try again, or head back to your
        repositories.
      </p>
      <div className="mt-2 flex items-center gap-3">
        <button
          type="button"
          onClick={reset}
          className="inline-flex items-center gap-1 rounded-md bg-gradient-to-r from-primary to-indigo-500 px-4 py-2 text-sm font-medium text-primary-foreground shadow-md transition-transform hover:scale-[1.02]"
        >
          Try again
        </button>
        <Link href="/repos" className="text-sm text-muted-foreground transition-colors hover:text-foreground">
          Back to repositories
        </Link>
      </div>
    </main>
  );
}
