"use client";

import { useEffect, useState } from "react";
import { FileTreeNode } from "./file-tree-node";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api-client";
import type { FileTreeEntry, FileTreeResponse } from "@/lib/types";

export function FileTree({
  repoId,
  selectedPath,
  onSelectFile,
}: {
  repoId: string;
  selectedPath: string | null;
  onSelectFile: (path: string) => void;
}) {
  const [entries, setEntries] = useState<FileTreeEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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
  }, [repoId]);

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
