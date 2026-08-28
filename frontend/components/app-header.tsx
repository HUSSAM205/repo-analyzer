"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Github } from "lucide-react";
import { SubmitRepoForm } from "@/components/submit-repo-form";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/utils";

const HEALTH_POLL_INTERVAL_MS = 15000;

export function AppHeader() {
  const [healthy, setHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function checkHealth() {
      try {
        const res = await fetch("/api/health", { cache: "no-store" });
        if (!cancelled) setHealthy(res.ok);
      } catch {
        if (!cancelled) setHealthy(false);
      }
    }

    checkHealth();
    const interval = setInterval(checkHealth, HEALTH_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const githubUrl = process.env.NEXT_PUBLIC_GITHUB_REPO_URL;

  return (
    <header className="sticky top-0 z-40 flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border bg-background/80 px-4 py-3 backdrop-blur-md sm:h-16 sm:flex-nowrap sm:py-0">
      {/* No brand logo here -- AppSidebar (always present alongside this
          header, see components/layout/app-shell.tsx) is the sole home for
          it now, so this stays the submit-form/status/theme row only. A
          little left padding on mobile keeps the row clear of the
          sidebar's floating hamburger trigger, which sits on top of this
          header (z-[60] vs. this header's z-40). */}
      <div className="w-full min-w-0 pl-10 sm:flex-1 sm:pl-0">
        <div className="mx-auto w-full max-w-2xl px-4">
          <SubmitRepoForm compact />
        </div>
      </div>
      <div className="flex items-center gap-3">
        {healthy === null ? null : healthy ? (
          <motion.span
            aria-label="Backend healthy"
            className="h-2 w-2 rounded-full bg-emerald-400"
            animate={{ opacity: [1, 0.4, 1] }}
            transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
          />
        ) : (
          <span aria-label="Backend unreachable" className="h-2 w-2 rounded-full bg-destructive" />
        )}
        {githubUrl && (
          <a
            href={githubUrl}
            target="_blank"
            rel="noreferrer"
            className={cn(
              "flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
            )}
          >
            <Github className="h-3.5 w-3.5" /> Star
          </a>
        )}
        <ThemeToggle />
      </div>
    </header>
  );
}
