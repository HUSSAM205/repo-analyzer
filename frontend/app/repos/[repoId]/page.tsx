"use client";

import { useEffect, useState } from "react";
import { notFound, useSearchParams } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { RepoHeader } from "@/components/workspace/repo-header";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { FileTree } from "@/components/workspace/file-tree";
import { CodeViewer } from "@/components/workspace/code-viewer";
import { ChatPanel } from "@/components/workspace/chat-panel";
import { RepoBriefing } from "@/components/workspace/repo-briefing";
import { AnalysisProgress } from "@/components/workspace/analysis-progress";
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

  // Same fallback pattern as RepoHeader: `job` only exists while
  // `useJobPolling` is actively tracking a `?job=` query param set at
  // submission time. On a reload/bookmark/shared link without that param,
  // fall back to `repo.latest_job` so the staged progress UI is still
  // correct for a repo that's still analyzing.
  const effectiveJob = job ?? repo.latest_job ?? null;
  const status = effectiveJob?.status ?? repo.status;
  const isAnalyzing = status === "pending" || status === "running";

  return (
    <>
      <RepoHeader repo={repo} job={job} polling={polling} pollingFailed={pollingFailed} />
      <AnimatePresence mode="wait" initial={false}>
        {isAnalyzing ? (
          <motion.div
            key="progress"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
          >
            <AnalysisProgress stage={effectiveJob?.stage} />
          </motion.div>
        ) : status !== "failed" ? (
          <motion.div
            key="briefing"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
          >
            <RepoBriefing briefing={repo.domain_briefing} />
          </motion.div>
        ) : null}
      </AnimatePresence>
      <WorkspaceShell
        left={<FileTree repoId={params.repoId} polling={polling} selectedPath={selectedPath} onSelectFile={setSelectedPath} />}
        center={<CodeViewer repoId={params.repoId} path={selectedPath} />}
        right={<ChatPanel repoId={params.repoId} onCitationClick={setSelectedPath} />}
      />
    </>
  );
}
