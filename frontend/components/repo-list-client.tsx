"use client";

import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { RepoList } from "@/components/repo-list";
import { Skeleton } from "@/components/ui/skeleton";
import { ensureSessionBootstrapped } from "@/lib/session-bootstrap";
import type { Repo } from "@/lib/types";

type State = { status: "loading" } | { status: "ready"; repos: Repo[] } | { status: "error" };

// Renders in place of the server-fetched <RepoList> on ReposPage when no
// session cookie exists yet (see middleware.ts and app/repos/page.tsx) --
// the page shell (Hero, FAQ, footer) has already painted by the time this
// mounts; this only ever gates the repo-list section, never first paint.
export function RepoListClient() {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        await ensureSessionBootstrapped();
        const res = await fetch("/api/repos", { cache: "no-store" });
        if (!res.ok) {
          if (!cancelled) setState({ status: "error" });
          return;
        }
        const repos = (await res.json()) as Repo[];
        if (!cancelled) setState({ status: "ready", repos });
      } catch {
        if (!cancelled) setState({ status: "error" });
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.status === "loading") {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true" aria-label="Loading repositories">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border p-8 text-center">
        <AlertTriangle className="h-6 w-6 text-destructive" aria-hidden="true" />
        <p className="text-sm font-medium text-zinc-100">Can&apos;t reach the server</p>
        <p className="text-sm text-muted-foreground">
          We couldn&apos;t load your repositories right now. The backend may be temporarily unavailable -- please
          try refreshing the page in a moment.
        </p>
      </div>
    );
  }

  return <RepoList repos={state.repos} />;
}
