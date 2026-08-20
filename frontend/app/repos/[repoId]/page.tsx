"use client";

import { useEffect, useState } from "react";
import { notFound, useSearchParams } from "next/navigation";
import { RepoHeader } from "@/components/workspace/repo-header";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { FileTree } from "@/components/workspace/file-tree";
import { CodeViewer } from "@/components/workspace/code-viewer";
import { ChatPanel } from "@/components/workspace/chat-panel";
import { useJobPolling } from "@/components/workspace/use-job-polling";
import { apiFetch } from "@/lib/api-client";
import type { Repo } from "@/lib/types";

export default function RepoWorkspacePage({ params }: { params: { repoId: string } }) {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job") ?? undefined;

  // Owned once here and passed down to both RepoHeader (status dot) and
  // FileTree (re-fetch trigger) so the same analysis job is only polled
  // once per page instead of each child running its own independent poll
  // of GET /api/jobs/{id}.
  const { job, polling, pollingFailed } = useJobPolling(jobId);

  const [repo, setRepo] = useState<Repo | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);

    apiFetch(`/api/repos/${params.repoId}`, { cache: "no-store" })
      .then((res) => {
        if (res.status === 404) {
          if (!cancelled) setRepo(null);
          return null;
        }
        if (!res.ok) throw new Error("Failed to load repository");
        return res.json() as Promise<Repo>;
      })
      .then((repo) => {
        if (!cancelled && repo) setRepo(repo);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load this repository.");
      });

    return () => {
      cancelled = true;
    };
  }, [params.repoId]);

  if (error) {
    return <div className="p-8 text-sm text-destructive">{error}</div>;
  }

  if (repo === null) {
    notFound();
  }

  if (repo === undefined) {
    return <div className="p-8 text-sm text-muted-foreground">Loading...</div>;
  }

  return (
    <>
      <RepoHeader repo={repo} job={job} polling={polling} pollingFailed={pollingFailed} />
      <WorkspaceShell
        left={<FileTree repoId={params.repoId} polling={polling} selectedPath={selectedPath} onSelectFile={setSelectedPath} />}
        center={<CodeViewer repoId={params.repoId} path={selectedPath} />}
        right={<ChatPanel repoId={params.repoId} />}
      />
    </>
  );
}
