"use client";

import Link from "next/link";
import { motion } from "framer-motion";
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
    <ul className="space-y-2">
      {repos.map((repo, index) => (
        <motion.li
          key={repo.id}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.15, delay: index * 0.03 }}
        >
          <Link
            href={`/repos/${repo.id}`}
            className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3 transition-colors hover:border-primary/40"
          >
            <span className="font-mono text-sm">{repo.name}</span>
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_STYLES[repo.status]}`}>
              {repo.status}
            </span>
          </Link>
        </motion.li>
      ))}
    </ul>
  );
}
