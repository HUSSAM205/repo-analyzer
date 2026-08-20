"use client";

import { motion } from "framer-motion";
import type { Job, Repo } from "@/lib/types";

// `job`/`polling`/`pollingFailed` come from a single `useJobPolling` call
// owned by the parent page and shared with `FileTree`, rather than this
// component running its own independent poll of the same
// `GET /api/jobs/{id}` -- see page.tsx.
export function RepoHeader({
  repo,
  job,
  polling,
  pollingFailed = false,
}: {
  repo: Repo;
  job: Job | null;
  polling: boolean;
  pollingFailed?: boolean;
}) {
  // `job` only exists while `useJobPolling` is actively tracking a job from
  // a `?job=` query param set at submission time -- on a reload, bookmark,
  // or shared link without that param, `job` is null. Fall back to
  // `repo.latest_job` (added by the backend) so the status dot and any
  // failure reason are still visible in that case, not just right after
  // submission. Optional-chained throughout since older backend responses
  // may not carry `latest_job` yet.
  const effectiveJob = job ?? repo.latest_job ?? null;
  const status = effectiveJob?.status ?? repo.status;

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-zinc-800/60 px-4">
      <div className="flex items-center gap-3">
        <span className="font-mono text-sm font-medium text-zinc-100">{repo.name}</span>
        {pollingFailed ? (
          <span
            aria-label="Lost connection to analysis job"
            className="h-2 w-2 rounded-full bg-amber-500"
          />
        ) : (
          (polling || status === "running" || status === "pending") && (
            <motion.span
              className="h-2 w-2 rounded-full bg-yellow-400"
              animate={{ opacity: [1, 0.4, 1] }}
              transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
            />
          )
        )}
        {status === "ready" || status === "completed" ? (
          <span data-testid="repo-status" className="h-2 w-2 rounded-full bg-emerald-400" />
        ) : null}
        {status === "failed" && <span className="h-2 w-2 rounded-full bg-destructive" />}
      </div>
      <div className="flex items-center gap-3">
        {pollingFailed ? (
          <span className="text-xs text-amber-400">Lost connection to analysis job. Try reloading the page.</span>
        ) : (
          effectiveJob &&
          effectiveJob.status !== "completed" &&
          effectiveJob.status !== "failed" && (
            <span className="text-xs text-zinc-400">Analyzing... {effectiveJob.progress}%</span>
          )
        )}
        {status === "failed" && (
          <span className="text-xs text-destructive">{effectiveJob?.error_message ?? "Analysis failed"}</span>
        )}
      </div>
    </header>
  );
}
