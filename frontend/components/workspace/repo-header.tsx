"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Job, Repo } from "@/lib/types";

// `job`/`polling` come from a single `useJobPolling` call owned by the
// parent page and shared with `FileTree`, rather than this component
// running its own independent poll of the same `GET /api/jobs/{id}` --
// see page.tsx.
export function RepoHeader({ repo, job, polling }: { repo: Repo; job: Job | null; polling: boolean }) {
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);
  const status = job?.status ?? repo.status;

  // Mirrors the fetch-then-navigate pattern login/register use (see
  // app/(auth)/login/page.tsx): POST to the route handler that clears the
  // httpOnly session cookie (app/api/auth/logout/route.ts), then send the
  // user to /login. `router.refresh()` clears any cached RSC data for the
  // now-unauthenticated session, same as login does on the way in.
  async function handleLogout() {
    setLoggingOut(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch {
      // Ignore -- the user's intent to leave shouldn't get stuck behind a
      // network blip. Worst case the session cookie outlives this tab, same
      // as if they'd just closed it, and it still expires in an hour.
    } finally {
      router.push("/login");
      router.refresh();
    }
  }

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
      <div className="flex items-center gap-3">
        {job && job.status !== "completed" && job.status !== "failed" && (
          <span className="text-xs text-muted-foreground">Analyzing... {job.progress}%</span>
        )}
        {job?.status === "failed" && (
          <span className="text-xs text-destructive">{job.error_message ?? "Analysis failed"}</span>
        )}
        <Button
          size="sm"
          variant="ghost"
          onClick={handleLogout}
          disabled={loggingOut}
          aria-label="Sign out"
        >
          <LogOut className="mr-1 h-3.5 w-3.5" /> Sign out
        </Button>
      </div>
    </header>
  );
}
