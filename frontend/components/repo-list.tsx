"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { TiltCard } from "@/components/tilt-card";
import type { Repo } from "@/lib/types";

const STATUS_STYLES: Record<Repo["status"], string> = {
  pending: "bg-yellow-500/15 text-yellow-400",
  ready: "bg-emerald-500/15 text-emerald-400",
  failed: "bg-destructive/15 text-destructive",
};

export function RepoList({ repos }: { repos: Repo[] }) {
  if (repos.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
        No repositories yet. Submit one above to get started.
      </p>
    );
  }

  return (
    // A workbench-style grid rather than a stacked list -- at real desktop
    // widths (see ReposPage's widened max-w-6xl container), a single-column
    // list of short repo-name rows left most of the row empty and read more
    // like a marketing page than a dashboard. Caps at 3 columns even on
    // very wide screens: each card still needs enough width for the repo
    // name to not truncate immediately, and a URL's `name` (the last path
    // segment) can run long.
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {repos.map((repo, index) => (
        <motion.li
          key={repo.id}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.15, delay: index * 0.03 }}
        >
          <TiltCard className="h-full rounded-lg">
            <Link
              href={`/repos/${repo.id}`}
              className="flex h-full flex-col justify-between gap-3 rounded-lg border border-zinc-800/60 bg-card px-4 py-3.5 transition-colors hover:border-primary/40 hover:elevated-ring"
            >
              <span className="truncate font-mono text-sm text-foreground">{repo.name}</span>
              <span
                className={`w-fit rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_STYLES[repo.status]}`}
              >
                {repo.status}
              </span>
            </Link>
          </TiltCard>
        </motion.li>
      ))}
    </ul>
  );
}
