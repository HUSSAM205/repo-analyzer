"use client";

import { useEffect, useState } from "react";
import { notFound, useSearchParams } from "next/navigation";
import { RepoHeader } from "@/components/workspace/repo-header";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { FileTree } from "@/components/workspace/file-tree";
import { CodeViewer } from "@/components/workspace/code-viewer";
import { apiFetch } from "@/lib/api-client";
import type { Repo } from "@/lib/types";

export default function RepoWorkspacePage({ params }: { params: { repoId: string } }) {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job") ?? undefined;

  const [repo, setRepo] = useState<Repo | null | undefined>(undefined);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  useEffect(() => {
    apiFetch("/api/repos", { cache: "no-store" })
      .then((res) => (res.ok ? (res.json() as Promise<Repo[]>) : []))
      .then((repos) => setRepo(repos.find((r) => r.id === params.repoId) ?? null));
  }, [params.repoId]);

  if (repo === null) {
    notFound();
  }

  if (repo === undefined) {
    return <div className="p-8 text-sm text-muted-foreground">Loading...</div>;
  }

  return (
    <>
      <RepoHeader repo={repo} jobId={jobId} />
      <WorkspaceShell
        left={<FileTree repoId={params.repoId} selectedPath={selectedPath} onSelectFile={setSelectedPath} />}
        center={<CodeViewer repoId={params.repoId} path={selectedPath} />}
        right={<div className="p-4 text-sm text-muted-foreground">Chat (Tasks 8-9)</div>}
      />
    </>
  );
}
