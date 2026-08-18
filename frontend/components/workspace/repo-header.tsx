"use client";

import { motion } from "framer-motion";
import type { Job, Repo } from "@/lib/types";

// `job`/`polling` come from a single `useJobPolling` call owned by the
// parent page and shared with `FileTree`, rather than this component
// running its own independent poll of the same `GET /api/jobs/{id}` --
// see page.tsx.
export function RepoHeader({ repo, job, polling }: { repo: Repo; job: Job | null; polling: boolean }) {
  const status = job?.status ?? repo.status;

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-zinc-800/60 px-4">
      <div className="flex items-center gap-3">
        <span className="font-mono text-sm font-medium text-zinc-100">{repo.name}</span>
        {(polling || status === "running" || status === "pending") && (
          <motion.span
            className="h-2 w-2 rounded-full bg-yellow-400"
            animate={{ opacity: [1, 0.4, 1] }}
            transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
          />
        )}
        {status === "ready" || status === "completed" ? (
          <span data-testid="repo-status" className="h-2 w-2 rounded-full bg-emerald-400" />
        ) : null}
        {status === "failed" && <span className="h-2 w-2 rounded-full bg-destructive" />}
      </div>
      <div className="flex items-center gap-3">
        {job && job.status !== "completed" && job.status !== "failed" && (
          <span className="text-xs text-zinc-400">Analyzing... {job.progress}%</span>
        )}
        {job?.status === "failed" && (
          <span className="text-xs text-destructive">{job.error_message ?? "Analysis failed"}</span>
        )}
      </div>
    </header>
  );
}
