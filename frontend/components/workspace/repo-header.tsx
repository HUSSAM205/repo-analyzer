"use client";

import { motion } from "framer-motion";
import { useJobPolling } from "./use-job-polling";
import type { Repo } from "@/lib/types";

export function RepoHeader({ repo, jobId }: { repo: Repo; jobId?: string }) {
  const { job, polling } = useJobPolling(jobId);
  const status = job?.status ?? repo.status;

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
      <div className="flex items-center gap-3">
        <span className="font-mono text-sm font-medium">{repo.name}</span>
        {(polling || status === "running" || status === "pending") && (
          <motion.span
            className="h-2 w-2 rounded-full bg-yellow-400"
            animate={{ opacity: [1, 0.4, 1] }}
            transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
          />
        )}
        {status === "ready" || status === "completed" ? (
          <span className="h-2 w-2 rounded-full bg-emerald-400" />
        ) : null}
        {status === "failed" && <span className="h-2 w-2 rounded-full bg-destructive" />}
      </div>
      {job && job.status !== "completed" && job.status !== "failed" && (
        <span className="text-xs text-muted-foreground">Analyzing... {job.progress}%</span>
      )}
      {job?.status === "failed" && (
        <span className="text-xs text-destructive">{job.error_message ?? "Analysis failed"}</span>
      )}
    </header>
  );
}
