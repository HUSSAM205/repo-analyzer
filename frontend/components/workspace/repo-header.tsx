"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { GitCompare } from "lucide-react";
import { DeepInsightsDrawer } from "./deep-insights-drawer";
import { RepoCompareModal } from "./repo-compare-modal";
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
  const isReady = status === "ready" || status === "completed";
  const [compareOpen, setCompareOpen] = useState(false);

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
        <DeepInsightsDrawer briefing={repo.domain_briefing} />
        {isReady && (
          <button
            type="button"
            onClick={() => setCompareOpen(true)}
            className="glow-pill glass flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            <GitCompare className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
            Compare
          </button>
        )}
      </div>
      {compareOpen && <RepoCompareModal repoId={repo.id} repoName={repo.name} onClose={() => setCompareOpen(false)} />}
    </header>
  );
}
