"use client";

import { useEffect, useState } from "react";
import { FileTreeNode } from "./file-tree-node";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api-client";
import type { FileTreeEntry, FileTreeResponse } from "@/lib/types";

export function FileTree({
  repoId,
  polling,
  selectedPath,
  onSelectFile,
}: {
  repoId: string;
  // Whether the repo's analysis job (if any) is still being polled by the
  // parent page. `page.tsx` owns the single `useJobPolling` call for this
  // repo -- shared with `RepoHeader` -- and passes the result down here
  // rather than each component running its own independent poll of
  // `GET /api/jobs/{id}` for the same job. A freshly-submitted repo lands
  // here with `polling` true while analysis is still running in the
  // background worker -- fetching the file tree once on mount (the naive
  // approach) races the ingestion job and permanently shows "No files
  // found", even after the job completes, because nothing re-triggers the
  // fetch. `polling` flips from true to false the moment the job reaches a
  // terminal state, so re-running the fetch when it changes picks up the
  // real file list right when analysis actually finishes. When there's no
  // job for this page load (browsing an already-analyzed repo), `polling`
  // is false from the start and this behaves exactly like a single
  // fetch-on-mount.
  polling: boolean;
  selectedPath: string | null;
  onSelectFile: (path: string) => void;
}) {
  const [entries, setEntries] = useState<FileTreeEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Reset any error from a prior attempt before this re-run's fetch
    // resolves. Without this, a transient failure on the first (too-early)
    // fetch while the job is still running would set `error` once, and the
    // later re-fetch triggered by `polling` going false could succeed and
    // populate `entries` -- but the stale `error` would still win the
    // `if (error) return ...` check below and leave the tree stuck showing
    // the error forever. Same pattern already used in page.tsx and
    // code-viewer.tsx for their own fetch effects.
    setError(null);
    apiFetch(`/api/repos/${repoId}/files`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load file tree");
        return res.json() as Promise<FileTreeResponse>;
      })
      .then((data) => {
        if (!cancelled) setEntries(data.entries);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load the file tree.");
      });
    return () => {
      cancelled = true;
    };
  }, [repoId, polling]);

  if (error) {
    return <p className="p-4 text-sm text-destructive">{error}</p>;
  }

  if (entries === null) {
    return (
      <div className="space-y-2 p-3">
        {[...Array(6)].map((_, i) => (
          <Skeleton key={i} className="h-4 w-[80%]" style={{ marginLeft: `${(i % 3) * 12}px` }} />
        ))}
      </div>
    );
  }

  if (entries.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">No files found for this repository.</p>;
  }

  return (
    <div className="py-2">
      {entries.map((entry) => (
        <FileTreeNode key={entry.path} entry={entry} depth={0} selectedPath={selectedPath} onSelectFile={onSelectFile} />
      ))}
    </div>
  );
}
