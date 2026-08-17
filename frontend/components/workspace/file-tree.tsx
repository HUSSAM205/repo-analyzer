"use client";

import { useEffect, useState } from "react";
import { FileTreeNode } from "./file-tree-node";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api-client";
import { useJobPolling } from "./use-job-polling";
import type { FileTreeEntry, FileTreeResponse } from "@/lib/types";

export function FileTree({
  repoId,
  jobId,
  selectedPath,
  onSelectFile,
}: {
  repoId: string;
  jobId?: string;
  selectedPath: string | null;
  onSelectFile: (path: string) => void;
}) {
  const [entries, setEntries] = useState<FileTreeEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // A freshly-submitted repo lands here with `jobId` set while analysis is
  // still running in the background worker -- fetching the file tree once on
  // mount (the naive approach) races the ingestion job and permanently shows
  // "No files found", even after the job completes, because nothing here
  // re-triggers the fetch. `polling` (from the same hook RepoHeader uses to
  // drive its status dot) flips from true to false the moment the job
  // reaches a terminal state, so re-running the fetch when it changes picks
  // up the real file list right when analysis actually finishes. When no
  // jobId is passed (browsing an already-analyzed repo), polling is false
  // from the start and this behaves exactly like a single fetch-on-mount.
  const { polling } = useJobPolling(jobId);

  useEffect(() => {
    let cancelled = false;
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
