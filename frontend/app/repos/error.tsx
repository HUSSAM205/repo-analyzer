"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";

// Catches a render error anywhere in "/repos" (the landing/workspace-list
// page) specifically -- narrower than the root app/error.tsx, so a failure
// here doesn't take down error reporting for the rest of the app, and the
// retry only needs to re-render this one route.
export default function ReposError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error(error);
  }, [error]);

  return (
    <main className="mx-auto flex max-w-6xl flex-col items-center gap-3 px-6 py-16 text-center">
      <AlertTriangle className="h-8 w-8 text-destructive" aria-hidden="true" />
      <h1 className="text-xl font-semibold text-foreground">This page hit an unexpected error</h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        Your repositories are safe -- this was a rendering error, not a data problem. Try again below.
      </p>
      <button
        type="button"
        onClick={reset}
        className="mt-2 inline-flex items-center gap-1 rounded-md bg-gradient-to-r from-primary to-indigo-500 px-4 py-2 text-sm font-medium text-primary-foreground shadow-md transition-transform hover:scale-[1.02]"
      >
        Try again
      </button>
    </main>
  );
}
